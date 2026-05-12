"""FAQ Knowledge Base API endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import SessionLocal, get_db
from app.dependencies import ensure_tenant_bound, require_admin, require_module, require_super_admin
from app.models import AuditLog, Message, Quiz, User
from app.models.faq_answer import FaqAnswer
from app.models.faq_cluster import FaqCluster
from app.models.faq_copilot_log import FaqCopilotLog
from app.models.faq_question import FaqQuestion
from app.models.faq_task import FaqTask
from app.models.system_setting import SystemSetting
from app.services.faq_llm import copilot_answer, copilot_answer_stream, get_single_embedding
from app.services.faq_pipeline import run_pipeline, semantic_search

router = APIRouter(dependencies=[Depends(require_module("mod_faq"))])
logger = logging.getLogger("chattrainer.faq_api")

_SEARCH_SPLIT_RE = re.compile(r"[\s,，。;；:：/\\|、\-_]+")
_SEARCH_REMOVE_CHARS = (" ", "　", "与", "和", "及", "、", "/", "\\", "-", "_", "，", "。", "；", ";")
_KEYWORD_SYNONYMS: dict[str, list[str]] = {
    "资质": ["资质", "性质", "资历"],
    "性质": ["性质", "资质"],
    "位置": ["位置", "地址", "地点"],
    "地址": ["地址", "位置", "地点"],
}


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _normalize_search_text(text: str) -> str:
    result = (text or "").strip().lower()
    for ch in _SEARCH_REMOVE_CHARS:
        result = result.replace(ch, "")
    return result


def _normalize_sql_expr(expr):
    out = func.lower(expr)
    for ch in _SEARCH_REMOVE_CHARS:
        out = func.replace(out, ch, "")
    return out


def _expand_keyword_terms(keyword: str) -> list[str]:
    text = (keyword or "").strip()
    if not text:
        return []
    parts = [p.strip() for p in _SEARCH_SPLIT_RE.split(text) if p and p.strip()]
    terms: list[str]
    if len(parts) >= 2:
        terms = [p for p in parts if len(p) >= 2] or [text]
    elif _has_cjk(text) and len(text) >= 4:
        # 中文长词按“前2字 + 后2字”拆分，提升“医院资质/医院性质与资质”这类匹配能力
        terms = [text[:2], text[-2:]]
    else:
        terms = [text]

    deduped: list[str] = []
    for t in terms:
        if t and t not in deduped:
            deduped.append(t)
    return deduped


def _build_cluster_keyword_filter(keyword: str):
    text = (keyword or "").strip()
    if not text:
        return None

    search_fields = [
        FaqCluster.title,
        FaqCluster.representative_question,
        FaqCluster.best_answer,
        FaqCluster.summary,
        FaqCluster.category,
        FaqCluster.tags,
    ]
    normalized_fields = [_normalize_sql_expr(f) for f in search_fields]

    terms = _expand_keyword_terms(text)
    grouped_conditions = []
    for term in terms:
        alts = _KEYWORD_SYNONYMS.get(term, [term])
        alt_conditions = []
        for alt in alts:
            if not alt:
                continue
            alt_norm = _normalize_search_text(alt)
            alt_conditions.extend([f.contains(alt) for f in search_fields])
            if alt_norm:
                alt_conditions.extend([nf.contains(alt_norm) for nf in normalized_fields])
        if alt_conditions:
            grouped_conditions.append(or_(*alt_conditions))

    raw_norm = _normalize_search_text(text)
    raw_conditions = [f.contains(text) for f in search_fields]
    if raw_norm:
        raw_conditions.extend([nf.contains(raw_norm) for nf in normalized_fields])
    raw_or = or_(*raw_conditions)

    if grouped_conditions:
        return or_(and_(*grouped_conditions), raw_or)
    return raw_or


def _resolve_copilot_quality_mode(payload: dict) -> str:
    mode = str(payload.get("quality_mode", "auto")).strip().lower()
    if mode in {"auto", "fast", "balanced", "quality"}:
        return mode
    return "auto"


_DEFAULT_RISK_KEYWORDS = (
    "费用", "价格", "多少钱", "收费", "医保", "报销", "疗程", "疗效", "副作用",
    "禁忌", "复发", "手术", "住院", "风险", "药物", "孕妇", "儿童", "老人",
)


def _parse_risk_keywords(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return _DEFAULT_RISK_KEYWORDS
    keywords = [k.strip() for k in raw.replace("，", ",").split(",") if k.strip()]
    return tuple(keywords) if keywords else _DEFAULT_RISK_KEYWORDS


def _resolve_effective_quality_mode(
    query_text: str,
    requested_mode: str,
    risk_keywords: tuple[str, ...] | None = None,
) -> tuple[str, str]:
    """Resolve auto mode to effective quality mode with reason.

    Routing strategy:
    - manual (fast/balanced/quality): respect user choice
    - auto: short queries (<=4 chars) → fast, risk keywords → quality, else → balanced
    """
    if requested_mode in {"fast", "balanced", "quality"}:
        return requested_mode, f"manual:{requested_mode}"

    text = (query_text or "").strip().lower()
    kws = risk_keywords or _DEFAULT_RISK_KEYWORDS

    if len(text) <= 4 and not any(k in text for k in kws):
        return "fast", "auto:short_query"

    if any(k in text for k in kws):
        return "quality", "auto:risk_keyword"

    return "balanced", "auto:default_balanced"


def _resolve_copilot_topk(mode: str) -> int:
    if mode == "quality":
        return 8
    if mode == "fast":
        return 5
    return 6


def _build_quick_reply_candidates(
    *,
    query_text: str,
    base_reply: str,
    matched_faqs: list[dict],
) -> list[str]:
    """Build 3 ready-to-send quick reply candidates."""
    reply = (base_reply or "").strip()
    if not reply:
        reply = "您好，我先帮您核实一下具体情况，稍后给您准确回复。"
    brief = reply
    if len(brief) > 72:
        brief = f"{brief[:72].rstrip('，,。.;；')}。"
    if matched_faqs:
        best = matched_faqs[0]
        tail = str(best.get("title") or best.get("category") or "").strip()
        guided = f"{reply}\n如需我帮您直接安排下一步（如预约/到院路线/资料准备），可继续告诉我。"
        if tail:
            guided = f"{guided}\n（已按“{tail}”场景为您匹配）"
    else:
        guided = f"{reply}\n如您愿意，我可以继续问您1-2个关键信息后给出更精准建议。"
    return [reply, brief, guided][:3]


# ─── Processing ────────────────────────────────────────────────────


class FaqProcessRequest(BaseModel):
    quiz_ids: list[int] | None = None


def _classify_task_error(error_message: str | None) -> tuple[str, str]:
    """Classify task failure reason by error text."""
    text = (error_message or "").lower()
    if not text:
        return "unknown", "未知原因"

    if "429" in text or "rate limit" in text or "too many requests" in text or "quota" in text:
        return "api_rate_limit", "API 限流/配额"
    if "服务重启" in text or "被中断" in text or "restart" in text:
        return "service_restart", "服务重启中断"
    if "心跳超时" in text or "阶段变化" in text or "heartbeat" in text:
        return "heartbeat_timeout", "心跳超时判死"
    if "timeout" in text or "timed out" in text:
        return "timeout", "请求超时"
    if "connection" in text or "network" in text or "name or service not known" in text:
        return "network", "网络连接异常"
    if "embedding api 返回" in text or "embeddings" in text:
        return "embedding_api", "Embedding 接口异常"
    if "llm api error" in text or "chat/completions" in text:
        return "llm_api", "LLM 接口异常"
    if "json" in text or "parse" in text:
        return "parse_error", "解析失败"
    if "no such table" in text or "sql" in text or "database" in text:
        return "database", "数据库异常"
    if "valueerror" in text or "invalidparameter" in text:
        return "invalid_parameter", "参数不合法"
    return "unknown", "未知原因"


def _resolve_timeout_source(task: FaqTask) -> tuple[str, str]:
    """Resolve where task timeout threshold comes from."""
    if task.retry_from_task_id:
        return "retry_inherited", "重试继承"
    if task.heartbeat_timeout_minutes in {5, 15, 30}:
        return "system_setting_snapshot", "系统设置快照"
    return "unknown", "未知来源"


def _extract_dispatch_warnings(task: FaqTask) -> list[dict]:
    if not task.config_json:
        return []
    try:
        cfg = json.loads(task.config_json)
        if isinstance(cfg, dict) and isinstance(cfg.get("dispatch_warnings"), list):
            return cfg["dispatch_warnings"][-10:]
    except Exception:
        return []
    return []


def _try_celery_dispatch(task_name: str, args: tuple, priority: int = 5) -> tuple[bool, str | None]:
    """Try to dispatch via Celery; return (queued, celery_task_id)."""
    try:
        from app.tasks.faq_tasks import celery_app
        result = celery_app.send_task(task_name, args=args, priority=priority)
        logger.info("Dispatched to Celery: %s id=%s priority=%d", task_name, result.id, priority)
        return True, str(result.id)
    except Exception:
        logger.debug("Celery unavailable, falling back to BackgroundTasks")
        return False, None


def _is_unregistered_task_error(detail: str) -> bool:
    text = (detail or "").lower()
    return (
        "unregistered task" in text
        or "notregistered" in text
        or "keyerror" in text
        or "unknown task" in text
    )


async def _append_dispatch_warning(task_id: int, warning: str) -> None:
    """Persist dispatch warning into task.config_json for ops tracing."""
    try:
        async with SessionLocal() as db:
            task = (await db.execute(select(FaqTask).where(FaqTask.id == task_id))).scalars().first()
            if not task:
                return
            config: dict = {}
            if task.config_json:
                try:
                    parsed = json.loads(task.config_json)
                    if isinstance(parsed, dict):
                        config = parsed
                except Exception:
                    config = {}
            warnings = config.get("dispatch_warnings")
            if not isinstance(warnings, list):
                warnings = []
            warnings.append({
                "time": datetime.utcnow().isoformat(),
                "message": warning,
            })
            config["dispatch_warnings"] = warnings[-30:]
            task.config_json = json.dumps(config, ensure_ascii=False)
            await db.commit()
    except Exception:
        logger.exception("Failed to append dispatch warning for task=%d", task_id)


async def _monitor_celery_dispatch_and_fallback(
    *,
    task_id: int,
    celery_task_id: str,
    runner: str,
    tenant_id: int | None,
    quiz_ids: list[int] | None,
) -> None:
    """If Celery task fails with unregistered/unknown task, auto fallback to local runner."""
    await asyncio.sleep(2.5)
    try:
        from app.tasks.faq_tasks import celery_app
        result = celery_app.AsyncResult(celery_task_id)
        state = str(result.state or "")
        if state not in {"FAILURE", "REVOKED"}:
            return
        detail = str(result.result or result.info or "")
        if not _is_unregistered_task_error(detail):
            return

        warning = (
            f"Celery 派发异常({state})，命中 unregistered task 特征，已自动回退 BackgroundTasks。"
            f" celery_task_id={celery_task_id}, detail={detail[:200]}"
        )
        logger.warning(warning)
        await _append_dispatch_warning(task_id, warning)

        if runner == "full":
            await _run_pipeline_background(task_id, tenant_id, quiz_ids)
        else:
            await _run_incremental_pipeline_background(task_id, tenant_id, quiz_ids or [])
    except Exception:
        logger.exception("Failed in celery fallback monitor: task=%d", task_id)


async def _run_pipeline_background(task_id: int, tenant_id: int | None, quiz_ids: list[int] | None) -> None:
    """Background task wrapper that creates its own DB session."""
    async with SessionLocal() as db:
        task = (await db.execute(select(FaqTask).where(FaqTask.id == task_id))).scalars().first()
        if not task:
            return
        await run_pipeline(db, task, tenant_id, quiz_ids)


async def _resolve_timeout_minutes(db: AsyncSession, tenant_id: int | None) -> int:
    default_timeout = 15
    if tenant_id is None:
        return default_timeout
    settings = (
        await db.execute(
            select(SystemSetting).where(SystemSetting.tenant_id == tenant_id).order_by(SystemSetting.id.asc()).limit(1)
        )
    ).scalars().first()
    configured = int(settings.faq_task_timeout_minutes) if settings and settings.faq_task_timeout_minutes else default_timeout
    return configured if configured in {5, 15, 30} else default_timeout


@router.post("/process")
async def start_faq_processing(
    background_tasks: BackgroundTasks,
    payload: FaqProcessRequest | None = None,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Trigger FAQ extraction pipeline on selected (or all) quizzes."""
    tenant_id = ensure_tenant_bound(admin)
    quiz_ids = payload.quiz_ids if payload else None
    timeout_minutes = await _resolve_timeout_minutes(db, tenant_id)

    task = FaqTask(
        tenant_id=tenant_id,
        operator_id=admin.id,
        retry_from_task_id=None,
        heartbeat_timeout_minutes=timeout_minutes,
        stage_changed_at=datetime.utcnow(),
        config_json=json.dumps({"quiz_ids": quiz_ids}) if quiz_ids else None,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    dispatched, celery_task_id = _try_celery_dispatch(
        "faq.run_pipeline", (task.id, tenant_id, quiz_ids), priority=3,
    )
    if not dispatched:
        background_tasks.add_task(_run_pipeline_background, task.id, tenant_id, quiz_ids)
    elif celery_task_id:
        background_tasks.add_task(
            _monitor_celery_dispatch_and_fallback,
            task_id=task.id,
            celery_task_id=celery_task_id,
            runner="full",
            tenant_id=tenant_id,
            quiz_ids=quiz_ids,
        )

    return {
        "code": 200,
        "message": "FAQ 处理任务已启动",
        "data": {"task_id": task.id, "status": task.status},
    }


@router.post("/process-incremental")
async def start_faq_incremental(
    background_tasks: BackgroundTasks,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Incremental FAQ update: only process quizzes not yet in the knowledge base."""
    tenant_id = ensure_tenant_bound(admin)

    quiz_filters = [Quiz.is_deleted.is_(False), Quiz.is_active.is_(True), Quiz.tenant_id == tenant_id]
    all_quiz_ids_rows = (
        await db.execute(select(Quiz.id).where(*quiz_filters))
    ).scalars().all()
    all_quiz_ids = set(all_quiz_ids_rows)

    processed_ids_rows = (
        await db.execute(
            select(FaqQuestion.quiz_id).where(
                FaqQuestion.tenant_id == tenant_id,
                FaqQuestion.quiz_id.isnot(None),
            ).distinct()
        )
    ).scalars().all()
    processed_ids = set(processed_ids_rows)

    new_quiz_ids = sorted(all_quiz_ids - processed_ids)

    if not new_quiz_ids:
        return {
            "code": 200,
            "message": "没有新的未处理对话",
            "data": {
                "task_id": 0,
                "status": "skipped",
                "new_quiz_count": 0,
                "skipped_reason": f"所有 {len(all_quiz_ids)} 个对话已处理，无需增量更新",
            },
        }

    timeout_minutes = await _resolve_timeout_minutes(db, tenant_id)
    task = FaqTask(
        tenant_id=tenant_id,
        operator_id=admin.id,
        retry_from_task_id=None,
        heartbeat_timeout_minutes=timeout_minutes,
        stage_changed_at=datetime.utcnow(),
        config_json=json.dumps({"quiz_ids": new_quiz_ids, "mode": "incremental"}),
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    dispatched, celery_task_id = _try_celery_dispatch(
        "faq.run_incremental", (task.id, tenant_id, new_quiz_ids), priority=7,
    )
    if not dispatched:
        background_tasks.add_task(
            _run_incremental_pipeline_background, task.id, tenant_id, new_quiz_ids,
        )
    elif celery_task_id:
        background_tasks.add_task(
            _monitor_celery_dispatch_and_fallback,
            task_id=task.id,
            celery_task_id=celery_task_id,
            runner="incremental",
            tenant_id=tenant_id,
            quiz_ids=new_quiz_ids,
        )

    return {
        "code": 200,
        "message": f"增量处理任务已启动，待处理 {len(new_quiz_ids)} 个新对话",
        "data": {
            "task_id": task.id,
            "status": task.status,
            "new_quiz_count": len(new_quiz_ids),
        },
    }


async def _run_incremental_pipeline_background(
    task_id: int, tenant_id: int | None, quiz_ids: list[int],
) -> None:
    """Background wrapper for incremental pipeline (no delete, append-only)."""
    from app.services.faq_pipeline import run_pipeline_incremental

    async with SessionLocal() as db:
        task = (await db.execute(select(FaqTask).where(FaqTask.id == task_id))).scalars().first()
        if not task:
            return
        await run_pipeline_incremental(db, task, tenant_id, quiz_ids)


@router.get("/tasks")
async def list_faq_tasks(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """List FAQ processing tasks."""
    tenant_id = admin.tenant_id
    filters = []
    if tenant_id is not None:
        filters.append(FaqTask.tenant_id == tenant_id)

    total = (await db.execute(select(func.count(FaqTask.id)).where(*filters))).scalar() or 0
    rows = (
        await db.execute(
            select(FaqTask)
            .where(*filters)
            .order_by(FaqTask.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    items = [
        {
            "id": t.id,
            "retry_from_task_id": t.retry_from_task_id,
            "status": t.status,
            "heartbeat_timeout_minutes": t.heartbeat_timeout_minutes,
            "heartbeat_timeout_source_code": _resolve_timeout_source(t)[0],
            "heartbeat_timeout_source_label": _resolve_timeout_source(t)[1],
            "total_quizzes": t.total_quizzes,
            "total_messages": t.total_messages,
            "extracted_pairs": t.extracted_pairs,
            "clusters_created": t.clusters_created,
            "clusters_updated": t.clusters_updated,
            "error_message": t.error_message,
            "failure_reason_code": _classify_task_error(t.error_message)[0] if t.status == "failed" else None,
            "failure_reason_label": _classify_task_error(t.error_message)[1] if t.status == "failed" else None,
            "stage_durations_json": t.stage_durations_json,
            "dispatch_warnings": _extract_dispatch_warnings(t),
            "started_at": t.started_at.isoformat() if t.started_at else None,
            "stage_changed_at": t.stage_changed_at.isoformat() if t.stage_changed_at else None,
            "finished_at": t.finished_at.isoformat() if t.finished_at else None,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in rows
    ]

    return {"code": 200, "message": "success", "data": {"items": items, "total": total}}


@router.get("/tasks/eta-benchmarks")
async def get_faq_task_eta_benchmarks(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return average stage durations from recent completed tasks for ETA estimation."""
    tenant_id = admin.tenant_id
    filters = [FaqTask.status == "completed", FaqTask.stage_durations_json.isnot(None)]
    if tenant_id is not None:
        filters.append(FaqTask.tenant_id == tenant_id)

    rows = (
        await db.execute(
            select(FaqTask)
            .where(*filters)
            .order_by(FaqTask.id.desc())
            .limit(20)
        )
    ).scalars().all()

    if not rows:
        return {"code": 200, "message": "success", "data": {"benchmarks": None, "sample_count": 0}}

    stage_names = ["extracting", "embedding", "clustering", "refining"]
    accum: dict[str, list[dict]] = {s: [] for s in stage_names}

    for t in rows:
        try:
            durations = json.loads(t.stage_durations_json)
        except (json.JSONDecodeError, TypeError):
            continue
        quizzes = max(1, t.total_quizzes)
        pairs = max(1, t.extracted_pairs)
        for s in stage_names:
            if s in durations:
                accum[s].append({
                    "seconds": durations[s],
                    "quizzes": quizzes,
                    "pairs": pairs,
                })

    benchmarks: dict[str, dict] = {}
    for s in stage_names:
        items = accum[s]
        if not items:
            continue
        avg_sec = round(sum(x["seconds"] for x in items) / len(items), 1)
        avg_quizzes = round(sum(x["quizzes"] for x in items) / len(items), 1)
        avg_per_quiz = round(avg_sec / avg_quizzes, 2) if avg_quizzes else 0
        benchmarks[s] = {
            "avg_seconds": avg_sec,
            "avg_per_quiz": avg_per_quiz,
            "sample_count": len(items),
        }

    return {
        "code": 200,
        "message": "success",
        "data": {"benchmarks": benchmarks, "sample_count": len(rows)},
    }


@router.get("/tasks/failure-stats")
async def get_faq_task_failure_stats(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    days: int = Query(30, ge=1, le=365),
):
    """Get failure reason stats for FAQ tasks."""
    tenant_id = admin.tenant_id
    filters = [FaqTask.status == "failed"]
    if tenant_id is not None:
        filters.append(FaqTask.tenant_id == tenant_id)

    rows = (
        await db.execute(
            select(FaqTask)
            .where(*filters)
            .order_by(FaqTask.id.desc())
            .limit(1000)
        )
    ).scalars().all()

    from datetime import timedelta

    cutoff = datetime.utcnow() - timedelta(days=days)
    reason_map: dict[str, dict] = {}
    total_failed = 0

    for t in rows:
        ref_time = t.finished_at or t.created_at
        if ref_time and ref_time < cutoff:
            continue
        total_failed += 1
        code, label = _classify_task_error(t.error_message)
        item = reason_map.setdefault(code, {
            "code": code,
            "label": label,
            "count": 0,
            "latest_task_id": 0,
            "latest_at": None,
            "sample_error": None,
        })
        item["count"] += 1
        if t.id > item["latest_task_id"]:
            item["latest_task_id"] = t.id
            item["latest_at"] = ref_time.isoformat() if ref_time else None
            item["sample_error"] = (t.error_message or "")[:200]

    items = sorted(reason_map.values(), key=lambda x: x["count"], reverse=True)

    return {
        "code": 200,
        "message": "success",
        "data": {
            "days": days,
            "total_failed": total_failed,
            "items": items,
        },
    }


@router.get("/tasks/{task_id}")
async def get_faq_task(
    task_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    task = (await db.execute(select(FaqTask).where(FaqTask.id == task_id))).scalars().first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {
        "code": 200,
        "message": "success",
        "data": {
            "id": task.id,
            "retry_from_task_id": task.retry_from_task_id,
            "status": task.status,
            "heartbeat_timeout_minutes": task.heartbeat_timeout_minutes,
            "heartbeat_timeout_source_code": _resolve_timeout_source(task)[0],
            "heartbeat_timeout_source_label": _resolve_timeout_source(task)[1],
            "total_quizzes": task.total_quizzes,
            "total_messages": task.total_messages,
            "extracted_pairs": task.extracted_pairs,
            "clusters_created": task.clusters_created,
            "dispatch_warnings": _extract_dispatch_warnings(task),
            "error_message": task.error_message,
            "failure_reason_code": _classify_task_error(task.error_message)[0] if task.status == "failed" else None,
            "failure_reason_label": _classify_task_error(task.error_message)[1] if task.status == "failed" else None,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "stage_changed_at": task.stage_changed_at.isoformat() if task.stage_changed_at else None,
            "finished_at": task.finished_at.isoformat() if task.finished_at else None,
        },
    }


@router.post("/tasks/{task_id}/retry")
async def retry_faq_task(
    task_id: int,
    background_tasks: BackgroundTasks,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Retry a failed FAQ processing task with its previous config."""
    old_task = (await db.execute(select(FaqTask).where(FaqTask.id == task_id))).scalars().first()
    if not old_task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if admin.tenant_id is not None and old_task.tenant_id != admin.tenant_id:
        raise HTTPException(status_code=403, detail="无权操作该任务")

    if old_task.status != "failed":
        raise HTTPException(status_code=400, detail="仅失败任务支持重试")

    quiz_ids: list[int] | None = None
    if old_task.config_json:
        try:
            config = json.loads(old_task.config_json)
            if isinstance(config, dict) and isinstance(config.get("quiz_ids"), list):
                quiz_ids = [int(v) for v in config["quiz_ids"]]
        except Exception:
            # 兼容历史脏数据：配置解析失败时回退为全量处理
            quiz_ids = None

    new_task = FaqTask(
        tenant_id=old_task.tenant_id,
        operator_id=admin.id,
        retry_from_task_id=old_task.id,
        heartbeat_timeout_minutes=old_task.heartbeat_timeout_minutes or await _resolve_timeout_minutes(db, old_task.tenant_id),
        stage_changed_at=datetime.utcnow(),
        config_json=json.dumps({"quiz_ids": quiz_ids}) if quiz_ids else None,
    )
    db.add(new_task)
    await db.commit()
    await db.refresh(new_task)

    background_tasks.add_task(_run_pipeline_background, new_task.id, old_task.tenant_id, quiz_ids)

    return {
        "code": 200,
        "message": "FAQ 任务已重新提交",
        "data": {
            "task_id": new_task.id,
            "status": new_task.status,
            "retry_from_task_id": old_task.id,
        },
    }


@router.delete("/tasks/{task_id}")
async def delete_faq_task(
    task_id: int,
    admin: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a completed/failed FAQ task."""
    filters = [FaqTask.id == task_id]
    if admin.tenant_id is not None:
        filters.append(FaqTask.tenant_id == admin.tenant_id)
    task = (await db.execute(select(FaqTask).where(*filters))).scalars().first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在或无权限删除")
    if task.status not in {"completed", "failed"}:
        raise HTTPException(status_code=400, detail="仅已完成或失败任务允许删除")
    await db.delete(task)
    await db.commit()
    return {"code": 200, "message": "删除成功"}


@router.post("/tasks/batch-delete")
async def batch_delete_faq_tasks(
    payload: dict,
    admin: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """Batch delete completed/failed FAQ tasks."""
    ids_raw = payload.get("ids")
    if not isinstance(ids_raw, list):
        raise HTTPException(status_code=400, detail="ids 必须是数组")
    ids = sorted({int(v) for v in ids_raw if str(v).strip().isdigit()})
    if not ids:
        raise HTTPException(status_code=400, detail="请至少选择一条任务")
    filters = [FaqTask.id.in_(ids), FaqTask.status.in_(["completed", "failed"])]
    if admin.tenant_id is not None:
        filters.append(FaqTask.tenant_id == admin.tenant_id)
    result = await db.execute(delete(FaqTask).where(*filters))
    await db.commit()
    return {"code": 200, "message": "批量删除成功", "data": {"deleted": int(result.rowcount or 0)}}


@router.post("/tasks/clear-history")
async def clear_faq_task_history(
    payload: dict | None = None,
    admin: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """Clear historical completed/failed tasks while keeping recent N days."""
    keep_days_raw = (payload or {}).get("keep_days", 7)
    try:
        keep_days = int(keep_days_raw)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="keep_days 必须是数字") from exc
    if keep_days < 0 or keep_days > 3650:
        raise HTTPException(status_code=400, detail="keep_days 必须在 0~3650 之间")

    cutoff = datetime.utcnow() - timedelta(days=keep_days)
    filters = [
        FaqTask.status.in_(["completed", "failed"]),
        FaqTask.created_at < cutoff,
    ]
    if admin.tenant_id is not None:
        filters.append(FaqTask.tenant_id == admin.tenant_id)

    result = await db.execute(delete(FaqTask).where(*filters))
    await db.commit()
    return {
        "code": 200,
        "message": "历史任务清理完成",
        "data": {"deleted": int(result.rowcount or 0), "keep_days": keep_days},
    }


# ─── Clusters CRUD ─────────────────────────────────────────────────

@router.get("/clusters")
async def list_faq_clusters(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str | None = None,
    keyword: str | None = None,
    is_active: bool | None = None,
):
    """List FAQ clusters with optional filters."""
    tenant_id = admin.tenant_id
    filters = []
    if tenant_id is not None:
        filters.append(FaqCluster.tenant_id == tenant_id)
    if category:
        filters.append(FaqCluster.category == category)
    if keyword:
        keyword_filter = _build_cluster_keyword_filter(keyword)
        if keyword_filter is not None:
            filters.append(keyword_filter)
    if is_active is not None:
        filters.append(FaqCluster.is_active == is_active)

    total = (await db.execute(select(func.count(FaqCluster.id)).where(*filters))).scalar() or 0
    rows = (
        await db.execute(
            select(FaqCluster)
            .where(*filters)
            .order_by(FaqCluster.question_count.desc(), FaqCluster.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    items = [
        {
            "id": c.id,
            "title": c.title,
            "summary": c.summary,
            "category": c.category,
            "tags": c.tags,
            "representative_question": c.representative_question,
            "best_answer": c.best_answer,
            "question_count": c.question_count,
            "answer_count": c.answer_count,
            "is_active": c.is_active,
            "is_locked": c.is_locked,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        }
        for c in rows
    ]

    categories_rows = (
        await db.execute(
            select(FaqCluster.category, func.count(FaqCluster.id))
            .where(
                FaqCluster.category.isnot(None),
                FaqCluster.is_active.is_(True),
                *( [FaqCluster.tenant_id == tenant_id] if tenant_id is not None else [] ),
            )
            .group_by(FaqCluster.category)
        )
    ).all()
    categories = [{"name": r[0], "count": r[1]} for r in categories_rows if r[0]]

    return {
        "code": 200,
        "message": "success",
        "data": {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "categories": categories,
        },
    }


@router.get("/clusters/{cluster_id}")
async def get_faq_cluster_detail(
    cluster_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get cluster detail including all questions and answers."""
    cluster = (
        await db.execute(select(FaqCluster).where(FaqCluster.id == cluster_id))
    ).scalars().first()
    if not cluster:
        raise HTTPException(status_code=404, detail="FAQ 条目不存在")

    questions = (
        await db.execute(
            select(FaqQuestion)
            .where(FaqQuestion.cluster_id == cluster_id)
            .order_by(FaqQuestion.is_representative.desc(), FaqQuestion.id.asc())
        )
    ).scalars().all()

    answers = (
        await db.execute(
            select(FaqAnswer)
            .where(FaqAnswer.cluster_id == cluster_id)
            .order_by(FaqAnswer.is_best.desc(), FaqAnswer.quality_score.desc(), FaqAnswer.id.asc())
        )
    ).scalars().all()

    return {
        "code": 200,
        "message": "success",
        "data": {
            "cluster": {
                "id": cluster.id,
                "title": cluster.title,
                "summary": cluster.summary,
                "category": cluster.category,
                "tags": cluster.tags,
                "representative_question": cluster.representative_question,
                "best_answer": cluster.best_answer,
                "question_count": cluster.question_count,
                "answer_count": cluster.answer_count,
                "is_active": cluster.is_active,
                "is_locked": cluster.is_locked,
                "created_at": cluster.created_at.isoformat() if cluster.created_at else None,
            },
            "questions": [
                {
                    "id": q.id,
                    "content": q.content,
                    "quiz_id": q.quiz_id,
                    "is_representative": q.is_representative,
                    "similarity_score": q.similarity_score,
                    "source_context": q.source_context,
                }
                for q in questions
            ],
            "answers": [
                {
                    "id": a.id,
                    "content": a.content,
                    "quiz_id": a.quiz_id,
                    "quality_score": a.quality_score,
                    "is_best": a.is_best,
                    "upvotes": a.upvotes,
                    "source_context": a.source_context,
                }
                for a in answers
            ],
        },
    }


@router.put("/clusters/{cluster_id}")
async def update_faq_cluster(
    cluster_id: int,
    payload: dict,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update cluster metadata (title, category, best_answer, etc.)."""
    cluster = (
        await db.execute(select(FaqCluster).where(FaqCluster.id == cluster_id))
    ).scalars().first()
    if not cluster:
        raise HTTPException(status_code=404, detail="FAQ 条目不存在")

    updatable = {"title", "summary", "category", "tags", "best_answer", "is_active", "is_locked"}
    for key in updatable:
        if key in payload:
            setattr(cluster, key, payload[key])

    await db.commit()
    return {"code": 200, "message": "更新成功"}


@router.delete("/clusters/{cluster_id}")
async def delete_faq_cluster(
    cluster_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a FAQ cluster and its questions/answers."""
    cluster = (
        await db.execute(select(FaqCluster).where(FaqCluster.id == cluster_id))
    ).scalars().first()
    if not cluster:
        raise HTTPException(status_code=404, detail="FAQ 条目不存在")

    await db.execute(delete(FaqQuestion).where(FaqQuestion.cluster_id == cluster_id))
    await db.execute(delete(FaqAnswer).where(FaqAnswer.cluster_id == cluster_id))
    await db.delete(cluster)
    await db.commit()
    return {"code": 200, "message": "已删除"}


@router.post("/clusters/merge")
async def merge_faq_clusters(
    payload: dict,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Merge multiple clusters into one (keep the first, absorb the rest)."""
    cluster_ids = payload.get("cluster_ids", [])
    if len(cluster_ids) < 2:
        raise HTTPException(status_code=400, detail="至少需要选择两个 FAQ 条目进行合并")

    target_id = cluster_ids[0]
    source_ids = cluster_ids[1:]

    target = (await db.execute(select(FaqCluster).where(FaqCluster.id == target_id))).scalars().first()
    if not target:
        raise HTTPException(status_code=404, detail="目标 FAQ 不存在")

    await db.execute(
        update(FaqQuestion).where(FaqQuestion.cluster_id.in_(source_ids)).values(cluster_id=target_id)
    )
    await db.execute(
        update(FaqAnswer).where(FaqAnswer.cluster_id.in_(source_ids)).values(cluster_id=target_id)
    )

    q_count = (await db.execute(
        select(func.count(FaqQuestion.id)).where(FaqQuestion.cluster_id == target_id)
    )).scalar() or 0
    a_count = (await db.execute(
        select(func.count(FaqAnswer.id)).where(FaqAnswer.cluster_id == target_id)
    )).scalar() or 0

    target.question_count = q_count
    target.answer_count = a_count

    if payload.get("title"):
        target.title = payload["title"]

    await db.execute(delete(FaqCluster).where(FaqCluster.id.in_(source_ids)))
    await db.commit()

    return {"code": 200, "message": f"已合并 {len(source_ids)} 个条目", "data": {"target_id": target_id}}


@router.post("/answers/{answer_id}/best")
async def toggle_best_answer(
    answer_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Toggle an answer as best/not-best."""
    answer = (await db.execute(select(FaqAnswer).where(FaqAnswer.id == answer_id))).scalars().first()
    if not answer:
        raise HTTPException(status_code=404, detail="答案不存在")

    answer.is_best = not answer.is_best
    await db.commit()
    return {"code": 200, "message": "已更新", "data": {"is_best": answer.is_best}}


@router.post("/answers/{answer_id}/upvote")
async def upvote_answer(
    answer_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Upvote an answer."""
    answer = (await db.execute(select(FaqAnswer).where(FaqAnswer.id == answer_id))).scalars().first()
    if not answer:
        raise HTTPException(status_code=404, detail="答案不存在")

    answer.upvotes = (answer.upvotes or 0) + 1
    await db.commit()
    return {"code": 200, "message": "已点赞", "data": {"upvotes": answer.upvotes}}


# ─── Search & Copilot ──────────────────────────────────────────────

@router.post("/search")
async def faq_search(
    payload: dict,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Semantic search over FAQ clusters."""
    query_text = str(payload.get("query", "")).strip()
    if not query_text:
        raise HTTPException(status_code=400, detail="请输入搜索内容")

    t0 = time.monotonic()
    top_k = min(int(payload.get("top_k", 10)), 20)
    query_embedding = await get_single_embedding(query_text)
    results = await semantic_search(db, query_embedding, admin.tenant_id, top_k)
    latency_ms = int((time.monotonic() - t0) * 1000)

    log = FaqCopilotLog(
        tenant_id=admin.tenant_id,
        user_id=admin.id,
        mode="search",
        query=query_text,
        reply=None,
        confidence=0.0,
        matched_count=len(results),
        latency_ms=latency_ms,
    )
    db.add(log)
    await db.commit()

    return {"code": 200, "message": "success", "data": {"results": results, "query": query_text, "latency_ms": latency_ms}}


async def _load_tenant_risk_keywords(db: AsyncSession, tenant_id: int | None) -> tuple[str, ...]:
    """Load risk keywords from system settings, fallback to defaults."""
    if tenant_id is None:
        return _DEFAULT_RISK_KEYWORDS
    row = (
        await db.execute(
            select(SystemSetting.copilot_risk_keywords)
            .where(SystemSetting.tenant_id == tenant_id)
            .limit(1)
        )
    ).scalar()
    return _parse_risk_keywords(row)


@router.post("/copilot")
async def faq_copilot(
    payload: dict,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Copilot: semantic search + LLM-generated recommended reply (non-streaming)."""
    query_text = str(payload.get("query", "")).strip()
    if not query_text:
        raise HTTPException(status_code=400, detail="请输入患者问题")
    requested_quality_mode = _resolve_copilot_quality_mode(payload)
    risk_kws = await _load_tenant_risk_keywords(db, admin.tenant_id)
    quality_mode, route_reason = _resolve_effective_quality_mode(query_text, requested_quality_mode, risk_kws)

    t0 = time.monotonic()
    query_embedding = await get_single_embedding(query_text)
    search_results = await semantic_search(db, query_embedding, admin.tenant_id, top_k=_resolve_copilot_topk(quality_mode))
    result = await copilot_answer(query_text, search_results, quality_mode=quality_mode)
    latency_ms = int((time.monotonic() - t0) * 1000)

    log = FaqCopilotLog(
        tenant_id=admin.tenant_id,
        user_id=admin.id,
        mode=f"copilot:{requested_quality_mode}->{quality_mode}",
        query=query_text,
        reply=result.recommended_reply[:2000],
        confidence=result.confidence,
        sources_json=json.dumps(result.sources, ensure_ascii=False) if result.sources else None,
        matched_count=len(search_results),
        latency_ms=latency_ms,
    )
    db.add(log)
    await db.commit()

    return {
        "code": 200,
        "message": "success",
        "data": {
            "recommended_reply": result.recommended_reply,
            "confidence": result.confidence,
            "sources": result.sources,
            "note": result.note,
            "matched_faqs": search_results,
            "quality_mode_requested": requested_quality_mode,
            "quality_mode_effective": quality_mode,
            "quality_route_reason": route_reason,
            "latency_ms": latency_ms,
        },
    }


@router.post("/copilot/panel")
async def faq_copilot_panel(
    payload: dict,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Copilot quick-reply panel: return 3 send-ready candidates."""
    query_text = str(payload.get("query", "")).strip()
    if not query_text:
        raise HTTPException(status_code=400, detail="请输入患者问题")
    requested_quality_mode = _resolve_copilot_quality_mode(payload)
    risk_kws = await _load_tenant_risk_keywords(db, admin.tenant_id)
    quality_mode, route_reason = _resolve_effective_quality_mode(query_text, requested_quality_mode, risk_kws)
    conversation_id = str(payload.get("conversation_id") or "").strip() or None
    channel = str(payload.get("channel") or "").strip() or "console"

    t0 = time.monotonic()
    query_embedding = await get_single_embedding(query_text)
    search_results = await semantic_search(db, query_embedding, admin.tenant_id, top_k=_resolve_copilot_topk(quality_mode))
    result = await copilot_answer(query_text, search_results, quality_mode=quality_mode)
    latency_ms = int((time.monotonic() - t0) * 1000)

    candidates = _build_quick_reply_candidates(
        query_text=query_text,
        base_reply=result.recommended_reply,
        matched_faqs=search_results,
    )

    log = FaqCopilotLog(
        tenant_id=admin.tenant_id,
        user_id=admin.id,
        mode=f"copilot_panel:{requested_quality_mode}->{quality_mode}",
        query=query_text,
        reply=result.recommended_reply[:2000] if result.recommended_reply else None,
        confidence=result.confidence,
        sources_json=json.dumps({
            "sources": result.sources or [],
            "panel_candidates": candidates,
            "conversation_id": conversation_id,
            "channel": channel,
        }, ensure_ascii=False),
        matched_count=len(search_results),
        latency_ms=latency_ms,
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)

    return {
        "code": 200,
        "message": "success",
        "data": {
            "panel_id": log.id,
            "query": query_text,
            "candidates": candidates,
            "matched_faqs": search_results,
            "confidence": result.confidence,
            "quality_mode_requested": requested_quality_mode,
            "quality_mode_effective": quality_mode,
            "quality_route_reason": route_reason,
            "latency_ms": latency_ms,
        },
    }


@router.post("/copilot/feedback")
async def faq_copilot_feedback(
    payload: dict,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Record quick-reply adoption feedback for efficiency analytics."""
    action = str(payload.get("action") or "").strip().lower()
    if action not in {"accepted", "edited", "rejected"}:
        raise HTTPException(status_code=400, detail="action 必须是 accepted/edited/rejected")
    log_id = int(payload.get("panel_id") or payload.get("log_id") or 0)
    if log_id <= 0:
        raise HTTPException(status_code=400, detail="panel_id 必填")
    log = (await db.execute(
        select(FaqCopilotLog).where(FaqCopilotLog.id == log_id)
    )).scalars().first()
    if not log:
        raise HTTPException(status_code=404, detail="面板日志不存在")
    if admin.tenant_id is not None and log.tenant_id != admin.tenant_id:
        raise HTTPException(status_code=403, detail="无权操作该日志")

    detail = {
        "action": action,
        "panel_id": log_id,
        "conversation_id": str(payload.get("conversation_id") or "").strip() or None,
        "channel": str(payload.get("channel") or "").strip() or "console",
        "candidate_index": int(payload.get("candidate_index") or 0),
        "final_reply": str(payload.get("final_reply") or "")[:2000] or None,
        "first_response_ms": int(payload.get("first_response_ms") or 0),
        "session_duration_ms": int(payload.get("session_duration_ms") or 0),
        "message_count": int(payload.get("message_count") or 0),
    }
    db.add(
        AuditLog(
            tenant_id=admin.tenant_id,
            user_id=admin.id,
            action="copilot_feedback",
            target_type="faq_copilot_log",
            target_id=log_id,
            hospital_id=admin.hospital_id,
            department_id=admin.department_id,
            detail=detail,
            ip=None,
        )
    )
    await db.commit()
    return {"code": 200, "message": "反馈已记录", "data": detail}


@router.post("/copilot/stream")
async def faq_copilot_stream(
    payload: dict,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Copilot SSE: stream the AI reply token by token."""
    query_text = str(payload.get("query", "")).strip()
    if not query_text:
        raise HTTPException(status_code=400, detail="请输入患者问题")
    requested_quality_mode = _resolve_copilot_quality_mode(payload)
    risk_kws = await _load_tenant_risk_keywords(db, admin.tenant_id)
    quality_mode, route_reason = _resolve_effective_quality_mode(query_text, requested_quality_mode, risk_kws)

    t0 = time.monotonic()
    query_embedding = await get_single_embedding(query_text)
    search_results = await semantic_search(db, query_embedding, admin.tenant_id, top_k=_resolve_copilot_topk(quality_mode))

    collected: list[str] = []

    async def event_generator():
        faq_data = json.dumps(search_results, ensure_ascii=False)
        yield f"data: {json.dumps({'type': 'faqs', 'matched_faqs': search_results}, ensure_ascii=False)}\n\n"

        async for token in copilot_answer_stream(query_text, search_results, quality_mode=quality_mode):
            collected.append(token)
            yield f"data: {json.dumps({'type': 'token', 'content': token}, ensure_ascii=False)}\n\n"

        latency_ms = int((time.monotonic() - t0) * 1000)
        full_reply = "".join(collected)
        yield f"data: {json.dumps({'type': 'done', 'latency_ms': latency_ms, 'quality_mode_requested': requested_quality_mode, 'quality_mode_effective': quality_mode, 'quality_route_reason': route_reason}, ensure_ascii=False)}\n\n"

        try:
            async with SessionLocal() as log_db:
                log = FaqCopilotLog(
                    tenant_id=admin.tenant_id,
                    user_id=admin.id,
                    mode=f"copilot_stream:{requested_quality_mode}->{quality_mode}",
                    query=query_text,
                    reply=full_reply[:2000],
                    confidence=0.0,
                    sources_json=None,
                    matched_count=len(search_results),
                    latency_ms=latency_ms,
                )
                log_db.add(log)
                await log_db.commit()
        except Exception:
            logger.exception("Failed to save copilot stream log")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ─── Copilot Logs ──────────────────────────────────────────────────

@router.get("/copilot/logs")
async def list_copilot_logs(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """List copilot query logs."""
    tenant_id = admin.tenant_id
    filters = []
    if tenant_id is not None:
        filters.append(FaqCopilotLog.tenant_id == tenant_id)

    total = (await db.execute(select(func.count(FaqCopilotLog.id)).where(*filters))).scalar() or 0
    rows = (
        await db.execute(
            select(FaqCopilotLog)
            .where(*filters)
            .order_by(FaqCopilotLog.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    from app.models import User as UserModel

    user_ids = sorted({r.user_id for r in rows if r.user_id})
    user_map: dict[int, str] = {}
    if user_ids:
        users = (await db.execute(select(UserModel).where(UserModel.id.in_(user_ids)))).scalars().all()
        user_map = {u.id: u.real_name or u.username for u in users}

    items = [
        {
            "id": r.id,
            "user_id": r.user_id,
            "username": user_map.get(r.user_id, "—") if r.user_id else "—",
            "mode": r.mode,
            "query": r.query,
            "reply": r.reply,
            "confidence": r.confidence,
            "sources_json": r.sources_json,
            "matched_count": r.matched_count,
            "latency_ms": r.latency_ms,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]

    avg_latency = round(sum(r.latency_ms for r in rows) / len(rows)) if rows else 0

    return {
        "code": 200,
        "message": "success",
        "data": {
            "items": items,
            "total": total,
            "avg_latency_ms": avg_latency,
        },
    }


@router.delete("/copilot/logs/{log_id}")
async def delete_copilot_log(
    log_id: int,
    admin: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    filters = [FaqCopilotLog.id == log_id]
    if admin.tenant_id is not None:
        filters.append(FaqCopilotLog.tenant_id == admin.tenant_id)
    log = (await db.execute(select(FaqCopilotLog).where(*filters))).scalars().first()
    if not log:
        raise HTTPException(status_code=404, detail="日志不存在或无权限删除")
    await db.delete(log)
    await db.commit()
    return {"code": 200, "message": "删除成功"}


@router.post("/copilot/logs/batch-delete")
async def batch_delete_copilot_logs(
    payload: dict,
    admin: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    ids_raw = payload.get("ids")
    if not isinstance(ids_raw, list):
        raise HTTPException(status_code=400, detail="ids 必须是数组")
    ids = sorted({int(v) for v in ids_raw if str(v).strip().isdigit()})
    if not ids:
        raise HTTPException(status_code=400, detail="请至少选择一条日志")
    filters = [FaqCopilotLog.id.in_(ids)]
    if admin.tenant_id is not None:
        filters.append(FaqCopilotLog.tenant_id == admin.tenant_id)
    stmt = delete(FaqCopilotLog).where(*filters)
    result = await db.execute(stmt)
    await db.commit()
    return {"code": 200, "message": "批量删除成功", "data": {"deleted": int(result.rowcount or 0)}}


@router.post("/copilot/logs/clear")
async def clear_copilot_logs(
    admin: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    filters = []
    if admin.tenant_id is not None:
        filters.append(FaqCopilotLog.tenant_id == admin.tenant_id)
    count_before = (await db.execute(select(func.count(FaqCopilotLog.id)).where(*filters))).scalar() or 0
    await db.execute(delete(FaqCopilotLog).where(*filters))
    await db.commit()
    return {
        "code": 200,
        "message": "已清空日志",
        "data": {"deleted": int(count_before)},
    }


# ─── Stats ─────────────────────────────────────────────────────────

@router.get("/stats")
async def faq_stats(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get FAQ knowledge base statistics."""
    tenant_id = admin.tenant_id
    filters = []
    if tenant_id is not None:
        filters.append(FaqCluster.tenant_id == tenant_id)

    total_clusters = (await db.execute(
        select(func.count(FaqCluster.id)).where(*filters)
    )).scalar() or 0

    active_clusters = (await db.execute(
        select(func.count(FaqCluster.id)).where(*filters, FaqCluster.is_active.is_(True))
    )).scalar() or 0

    total_questions = (await db.execute(
        select(func.count(FaqQuestion.id)).where(
            *(([FaqQuestion.tenant_id == tenant_id] if tenant_id else []))
        )
    )).scalar() or 0

    total_answers = (await db.execute(
        select(func.count(FaqAnswer.id)).where(
            *(([FaqAnswer.tenant_id == tenant_id] if tenant_id else []))
        )
    )).scalar() or 0

    categories = (await db.execute(
        select(FaqCluster.category, func.count(FaqCluster.id))
        .where(*filters, FaqCluster.category.isnot(None))
        .group_by(FaqCluster.category)
        .order_by(func.count(FaqCluster.id).desc())
    )).all()

    recent_tasks = (await db.execute(
        select(FaqTask)
        .where(*(([FaqTask.tenant_id == tenant_id] if tenant_id else [])))
        .order_by(FaqTask.id.desc())
        .limit(5)
    )).scalars().all()

    # 今日 AI 问答统计（按北京时间自然日）
    now_utc = datetime.utcnow()
    now_bj = now_utc + timedelta(hours=8)
    day_start_bj = now_bj.replace(hour=0, minute=0, second=0, microsecond=0)
    day_start_utc = day_start_bj - timedelta(hours=8)
    day_end_utc = day_start_utc + timedelta(days=1)

    copilot_base_filters = [
        FaqCopilotLog.mode.like("copilot%"),
        FaqCopilotLog.created_at >= day_start_utc,
        FaqCopilotLog.created_at < day_end_utc,
    ]
    if tenant_id is not None:
        copilot_base_filters.append(FaqCopilotLog.tenant_id == tenant_id)

    copilot_total_calls = (await db.execute(
        select(func.count(FaqCopilotLog.id)).where(*copilot_base_filters)
    )).scalar() or 0

    copilot_avg_latency = (await db.execute(
        select(func.avg(FaqCopilotLog.latency_ms)).where(*copilot_base_filters)
    )).scalar()
    copilot_avg_latency_ms = int(round(float(copilot_avg_latency))) if copilot_avg_latency is not None else 0

    quality_hit_calls = (await db.execute(
        select(func.count(FaqCopilotLog.id)).where(
            *copilot_base_filters,
            or_(
                FaqCopilotLog.mode.like("%->quality"),
                FaqCopilotLog.mode.like("%:quality"),
            ),
        )
    )).scalar() or 0

    failed_calls = (await db.execute(
        select(func.count(FaqCopilotLog.id)).where(
            *copilot_base_filters,
            or_(
                FaqCopilotLog.reply.is_(None),
                FaqCopilotLog.reply == "",
                FaqCopilotLog.reply.like("AI 未配置%"),
                FaqCopilotLog.reply.like("AI 服务暂时不可用%"),
                FaqCopilotLog.reply.like("AI 回复解析失败%"),
                FaqCopilotLog.reply.like("AI 服务异常%"),
            ),
        )
    )).scalar() or 0

    quality_hit_rate = round((quality_hit_calls / copilot_total_calls) * 100, 1) if copilot_total_calls else 0.0
    failure_rate = round((failed_calls / copilot_total_calls) * 100, 1) if copilot_total_calls else 0.0

    # 最近7天趋势（北京时间自然日，含今日）
    trend_start_bj = day_start_bj - timedelta(days=6)
    trend_start_utc = trend_start_bj - timedelta(hours=8)
    trend_end_utc = day_end_utc
    trend_filters = [
        FaqCopilotLog.mode.like("copilot%"),
        FaqCopilotLog.created_at >= trend_start_utc,
        FaqCopilotLog.created_at < trend_end_utc,
    ]
    if tenant_id is not None:
        trend_filters.append(FaqCopilotLog.tenant_id == tenant_id)

    trend_rows = (
        await db.execute(
            select(FaqCopilotLog.created_at, FaqCopilotLog.latency_ms, FaqCopilotLog.reply)
            .where(*trend_filters)
        )
    ).all()

    bucket: dict[str, dict[str, float]] = defaultdict(lambda: {"calls": 0.0, "latency_sum": 0.0, "failed": 0.0})
    for created_at, latency_ms, reply in trend_rows:
        if not created_at:
            continue
        day_bj = (created_at + timedelta(hours=8)).date().isoformat()
        b = bucket[day_bj]
        b["calls"] += 1
        b["latency_sum"] += float(latency_ms or 0)
        reply_text = str(reply or "")
        if (
            reply_text == ""
            or reply_text.startswith("AI 未配置")
            or reply_text.startswith("AI 服务暂时不可用")
            or reply_text.startswith("AI 回复解析失败")
            or reply_text.startswith("AI 服务异常")
        ):
            b["failed"] += 1

    copilot_7d_trend = []
    for i in range(7):
        day = (trend_start_bj + timedelta(days=i)).date().isoformat()
        b = bucket.get(day, {"calls": 0.0, "latency_sum": 0.0, "failed": 0.0})
        calls = int(b["calls"])
        avg_ms = int(round(b["latency_sum"] / calls)) if calls > 0 else 0
        fail_rate = round((b["failed"] / calls) * 100, 1) if calls > 0 else 0.0
        copilot_7d_trend.append({
            "date_bj": day,
            "calls": calls,
            "avg_latency_ms": avg_ms,
            "failure_rate": fail_rate,
        })

    return {
        "code": 200,
        "message": "success",
        "data": {
            "total_clusters": total_clusters,
            "active_clusters": active_clusters,
            "total_questions": total_questions,
            "total_answers": total_answers,
            "categories": [{"name": c[0], "count": c[1]} for c in categories if c[0]],
            "recent_tasks": [
                {
                    "id": t.id,
                    "status": t.status,
                    "clusters_created": t.clusters_created,
                    "extracted_pairs": t.extracted_pairs,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                }
                for t in recent_tasks
            ],
            "copilot_today": {
                "date_bj": day_start_bj.date().isoformat(),
                "total_calls": int(copilot_total_calls),
                "avg_latency_ms": copilot_avg_latency_ms,
                "quality_hit_calls": int(quality_hit_calls),
                "quality_hit_rate": quality_hit_rate,
                "failed_calls": int(failed_calls),
                "failure_rate": failure_rate,
            },
            "copilot_7d_trend": copilot_7d_trend,
        },
    }


@router.get("/copilot/efficiency-7d")
async def copilot_efficiency_7d(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """7-day practical efficiency report from copilot feedback events."""
    tenant_id = admin.tenant_id
    now_utc = datetime.utcnow()
    start_utc = now_utc - timedelta(days=7)
    filters = [AuditLog.action == "copilot_feedback", AuditLog.created_at >= start_utc]
    if tenant_id is not None:
        filters.append(AuditLog.tenant_id == tenant_id)
    rows = (
        await db.execute(select(AuditLog).where(*filters).order_by(AuditLog.created_at.desc()))
    ).scalars().all()

    accepted = edited = rejected = 0
    first_response_values: list[int] = []
    session_duration_values: list[int] = []
    trend_bucket: dict[str, dict[str, int]] = defaultdict(lambda: {"accepted": 0, "edited": 0, "rejected": 0})

    for row in rows:
        detail = row.detail if isinstance(row.detail, dict) else {}
        action = str(detail.get("action") or "").lower()
        if action == "accepted":
            accepted += 1
        elif action == "edited":
            edited += 1
        elif action == "rejected":
            rejected += 1
        fr = int(detail.get("first_response_ms") or 0)
        sd = int(detail.get("session_duration_ms") or 0)
        if fr > 0:
            first_response_values.append(fr)
        if sd > 0:
            session_duration_values.append(sd)
        if row.created_at:
            day_bj = (row.created_at + timedelta(hours=8)).date().isoformat()
            trend_bucket[day_bj][action if action in {"accepted", "edited", "rejected"} else "rejected"] += 1

    total = accepted + edited + rejected
    accept_rate = round((accepted / total) * 100, 1) if total else 0.0
    avg_first_response_ms = int(sum(first_response_values) / len(first_response_values)) if first_response_values else 0
    avg_session_duration_ms = int(sum(session_duration_values) / len(session_duration_values)) if session_duration_values else 0

    baseline_first_response_ms = 45000
    labor_reduction_pct = 0.0
    if avg_first_response_ms > 0:
        labor_reduction_pct = round(max(0.0, (baseline_first_response_ms - avg_first_response_ms) / baseline_first_response_ms * 100), 1)

    trend = []
    day0_bj = (now_utc + timedelta(hours=8)).date()
    for i in range(6, -1, -1):
        day = (day0_bj - timedelta(days=i)).isoformat()
        b = trend_bucket.get(day, {"accepted": 0, "edited": 0, "rejected": 0})
        day_total = b["accepted"] + b["edited"] + b["rejected"]
        trend.append({
            "date_bj": day,
            "accepted": b["accepted"],
            "edited": b["edited"],
            "rejected": b["rejected"],
            "total": day_total,
            "accept_rate": round((b["accepted"] / day_total) * 100, 1) if day_total else 0.0,
        })

    return {
        "code": 200,
        "message": "success",
        "data": {
            "window_days": 7,
            "total_feedback": total,
            "accepted": accepted,
            "edited": edited,
            "rejected": rejected,
            "accept_rate": accept_rate,
            "avg_first_response_ms": avg_first_response_ms,
            "avg_session_duration_ms": avg_session_duration_ms,
            "baseline_first_response_ms": baseline_first_response_ms,
            "labor_reduction_pct": labor_reduction_pct,
            "trend": trend,
        },
    }


@router.get("/data-quality")
async def faq_data_quality(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Operations dashboard: imported data quality overview."""
    tenant_id = admin.tenant_id
    t_filters = [Quiz.is_deleted.is_(False)]
    if tenant_id is not None:
        t_filters.append(Quiz.tenant_id == tenant_id)

    total_quizzes = (await db.execute(
        select(func.count(Quiz.id)).where(*t_filters)
    )).scalar() or 0

    active_quizzes = (await db.execute(
        select(func.count(Quiz.id)).where(*t_filters, Quiz.is_active.is_(True))
    )).scalar() or 0

    m_filters = []
    if tenant_id is not None:
        m_filters.append(Message.tenant_id == tenant_id)

    total_messages = (await db.execute(
        select(func.count(Message.id)).where(*m_filters)
    )).scalar() or 0

    patient_count = (await db.execute(
        select(func.count(Message.id)).where(*m_filters, Message.role == "patient")
    )).scalar() or 0

    counselor_count = (await db.execute(
        select(func.count(Message.id)).where(*m_filters, Message.role == "counselor")
    )).scalar() or 0

    text_count = (await db.execute(
        select(func.count(Message.id)).where(*m_filters, Message.content_type == "text")
    )).scalar() or 0

    image_count = (await db.execute(
        select(func.count(Message.id)).where(*m_filters, Message.content_type == "image")
    )).scalar() or 0

    audio_count = (await db.execute(
        select(func.count(Message.id)).where(*m_filters, Message.content_type == "audio")
    )).scalar() or 0

    patient_ratio = round((patient_count / total_messages) * 100, 1) if total_messages else 0.0
    text_ratio = round((text_count / total_messages) * 100, 1) if total_messages else 0.0
    avg_msg_per_quiz = round(total_messages / total_quizzes, 1) if total_quizzes else 0.0

    cluster_filters = [FaqCluster.is_active.is_(True)]
    if tenant_id is not None:
        cluster_filters.append(FaqCluster.tenant_id == tenant_id)
    faq_clusters = (await db.execute(
        select(func.count(FaqCluster.id)).where(*cluster_filters)
    )).scalar() or 0

    locked_clusters = (await db.execute(
        select(func.count(FaqCluster.id)).where(
            *cluster_filters, FaqCluster.is_locked.is_(True)
        )
    )).scalar() or 0

    coverage = round((faq_clusters / total_quizzes) * 100, 1) if total_quizzes else 0.0

    health_score = 1.0
    warnings = []
    if total_quizzes == 0:
        health_score = 0.0
        warnings.append("尚未导入任何对话数据")
    else:
        if patient_ratio < 20 or patient_ratio > 80:
            health_score -= 0.2
            warnings.append(f"患者消息占比异常 ({patient_ratio}%)，建议检查角色识别")
        if text_ratio < 40:
            health_score -= 0.15
            warnings.append(f"文本消息占比偏低 ({text_ratio}%)，大量图片/语音占位")
        if avg_msg_per_quiz < 3:
            health_score -= 0.15
            warnings.append(f"平均每对话仅 {avg_msg_per_quiz} 条消息，数据量偏少")
        if faq_clusters == 0:
            health_score -= 0.2
            warnings.append("尚未生成 FAQ 知识库")

    return {
        "code": 200,
        "message": "success",
        "data": {
            "conversations": {
                "total": total_quizzes,
                "active": active_quizzes,
                "avg_messages": avg_msg_per_quiz,
            },
            "messages": {
                "total": total_messages,
                "patient": patient_count,
                "counselor": counselor_count,
                "text": text_count,
                "image": image_count,
                "audio": audio_count,
                "patient_ratio": patient_ratio,
                "text_ratio": text_ratio,
            },
            "faq": {
                "clusters": faq_clusters,
                "locked": locked_clusters,
                "coverage_pct": coverage,
            },
            "health_score": round(max(0.0, min(1.0, health_score)), 2),
            "warnings": warnings,
        },
    }
