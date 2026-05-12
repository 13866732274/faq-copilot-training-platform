import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

logger = logging.getLogger("chattrainer.perf")

from app.api.audit import router as audit_router
from app.api.auth import router as auth_router
from app.api.billing import router as billing_router
from app.api.bot_webhook import router as bot_webhook_router
from app.api.bot_wechat_faq import router as bot_wechat_faq_router
from app.api.departments import router as departments_router
from app.api.hospitals import router as hospitals_router
from app.api.import_tasks import router as import_tasks_router
from app.api.practice import router as practice_router
from app.api.quizzes import router as quizzes_router
from app.api.records import router as records_router
from app.api.stats import router as stats_router
from app.api.system import router as system_router
from app.api.tenants import router as tenants_router
from app.api.faq import router as faq_router
from app.api.permission_audit import router as permission_audit_router
from app.api.users import router as users_router
from app.database import SessionLocal
from app.models.faq_task import FaqTask
from app.models.system_setting import SystemSetting
from app.services.audit import append_audit_log
from app.services.preview_store import cleanup_expired_previews
from app.services.usage_tracker import append_request_usage, should_track_usage


async def _preview_cleanup_worker() -> None:
    while True:
        try:
            async with SessionLocal() as db:
                await cleanup_expired_previews(db)
        except Exception:
            # 清理任务失败不影响主业务请求
            pass
        await asyncio.sleep(3600)


async def _recover_interrupted_faq_tasks() -> None:
    """Mark in-flight FAQ tasks as failed after service restart."""
    running_statuses = ("pending", "extracting", "embedding", "clustering", "refining")
    try:
        async with SessionLocal() as db:
            rows = (
                await db.execute(
                    select(FaqTask).where(
                        FaqTask.status.in_(running_statuses),
                        FaqTask.finished_at.is_(None),
                    )
                )
            ).scalars().all()
            if not rows:
                return

            now = datetime.utcnow()
            for task in rows:
                task.status = "failed"
                task.stage_changed_at = now
                task.finished_at = now
                base = (task.error_message or "").strip()
                recovered = "任务在服务重启时被中断，请使用一键重试继续处理。"
                task.error_message = f"{base} | {recovered}" if base else recovered

            await db.commit()
            logger.warning("recovered_interrupted_faq_tasks count=%d", len(rows))
    except Exception:
        logger.exception("recover_interrupted_faq_tasks_failed")


async def _faq_task_heartbeat_watchdog_worker() -> None:
    """Auto-fail FAQ tasks when stage does not change for too long."""
    running_statuses = ("pending", "extracting", "embedding", "clustering", "refining")
    default_timeout_minutes = 15
    check_interval_seconds = 60
    while True:
        try:
            async with SessionLocal() as db:
                rows = (
                    await db.execute(
                        select(FaqTask).where(
                            FaqTask.status.in_(running_statuses),
                            FaqTask.finished_at.is_(None),
                        )
                    )
                ).scalars().all()
                if rows:
                    now = datetime.utcnow()
                    tenant_ids = sorted({int(t.tenant_id) for t in rows if t.tenant_id is not None})
                    timeout_map: dict[int, int] = {}
                    if tenant_ids:
                        settings_rows = (
                            await db.execute(
                                select(SystemSetting).where(SystemSetting.tenant_id.in_(tenant_ids))
                            )
                        ).scalars().all()
                        timeout_map = {
                            int(s.tenant_id): int(s.faq_task_timeout_minutes or default_timeout_minutes)
                            for s in settings_rows
                            if s.tenant_id is not None
                        }
                    stale_count = 0
                    for task in rows:
                        timeout_minutes = int(task.heartbeat_timeout_minutes or 0)
                        if timeout_minutes not in {5, 15, 30}:
                            timeout_minutes = timeout_map.get(
                                int(task.tenant_id) if task.tenant_id is not None else -1,
                                default_timeout_minutes,
                            )
                        timeout_before = now - timedelta(minutes=timeout_minutes)
                        last_change = task.stage_changed_at or task.started_at or task.created_at
                        if not last_change or last_change >= timeout_before:
                            continue
                        task.status = "failed"
                        task.stage_changed_at = now
                        task.finished_at = now
                        base = (task.error_message or "").strip()
                        reason = f"任务阶段心跳超时（{timeout_minutes}分钟无阶段变化），系统已自动判定失败。"
                        task.error_message = f"{base} | {reason}" if base else reason
                        stale_count += 1
                    if stale_count > 0:
                        await db.commit()
                        logger.warning("faq_task_heartbeat_timeout_marked_failed count=%d", stale_count)
        except Exception:
            logger.exception("faq_task_heartbeat_watchdog_failed")
        await asyncio.sleep(check_interval_seconds)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await _recover_interrupted_faq_tasks()
    task_preview_cleanup = asyncio.create_task(_preview_cleanup_worker())
    task_faq_watchdog = asyncio.create_task(_faq_task_heartbeat_watchdog_worker())
    try:
        yield
    finally:
        task_preview_cleanup.cancel()
        task_faq_watchdog.cancel()
        try:
            await task_preview_cleanup
        except asyncio.CancelledError:
            pass
        try:
            await task_faq_watchdog
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="ChatTrainer API",
    version="0.1.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

SLOW_REQUEST_THRESHOLD_MS = 500


async def _append_slow_request_audit(request: Request, elapsed_ms: float, status_code: int) -> None:
    forwarded = request.headers.get("x-forwarded-for") or ""
    ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else None)
    async with SessionLocal() as db:
        await append_audit_log(
            db,
            action="slow_request",
            user_id=None,
            target_type="system",
            detail={
                "path": request.url.path,
                "method": request.method,
                "elapsed_ms": elapsed_ms,
                "status_code": status_code,
            },
            ip=ip,
        )
        await db.commit()


async def _append_usage_record(request: Request, elapsed_ms: float, status_code: int) -> None:
    if not should_track_usage(request.url.path, request.method):
        return
    async with SessionLocal() as db:
        await append_request_usage(
            db,
            request=request,
            status_code=status_code,
            elapsed_ms=elapsed_ms,
        )
        await db.commit()


class PerformanceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
        response.headers["X-Response-Time"] = f"{elapsed_ms}ms"
        if elapsed_ms > SLOW_REQUEST_THRESHOLD_MS:
            logger.warning(
                "slow_request path=%s method=%s elapsed_ms=%.1f status=%d",
                request.url.path,
                request.method,
                elapsed_ms,
                response.status_code,
            )
            try:
                await _append_slow_request_audit(request, elapsed_ms, response.status_code)
            except Exception:
                logger.exception("failed_to_write_slow_request_audit path=%s", request.url.path)
        try:
            await _append_usage_record(request, elapsed_ms, response.status_code)
        except Exception:
            logger.exception("failed_to_write_usage_record path=%s", request.url.path)
        return response


app.add_middleware(PerformanceMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:5174",
        "http://localhost:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Response-Time"],
)


@app.get("/api/v1/health")
def health_check() -> dict:
    return {"code": 200, "message": "success", "data": {"status": "ok"}}


app.include_router(quizzes_router, prefix="/api/v1/quizzes", tags=["quizzes"])
app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(audit_router, prefix="/api/v1/audit-logs", tags=["audit_logs"])
app.include_router(stats_router, prefix="/api/v1/stats", tags=["stats"])
app.include_router(practice_router, prefix="/api/v1/practice", tags=["practice"])
app.include_router(records_router, prefix="/api/v1/records", tags=["records"])
app.include_router(users_router, prefix="/api/v1/users", tags=["users"])
app.include_router(hospitals_router, prefix="/api/v1/hospitals", tags=["hospitals"])
app.include_router(departments_router, prefix="/api/v1/departments", tags=["departments"])
app.include_router(system_router, prefix="/api/v1/system", tags=["system"])
app.include_router(import_tasks_router, prefix="/api/v1/import-tasks", tags=["import_tasks"])
app.include_router(tenants_router, prefix="/api/v1/tenants", tags=["tenants"])
app.include_router(permission_audit_router, prefix="/api/v1/admin", tags=["permission_audit"])
app.include_router(faq_router, prefix="/api/v1/faq", tags=["faq"])
app.include_router(billing_router, prefix="/api/v1/billing", tags=["billing"])
app.include_router(bot_webhook_router, prefix="/api/v1/bot", tags=["bot_webhook"])
app.include_router(bot_wechat_faq_router, prefix="/api/v1/bot", tags=["bot_wechat_faq"])
