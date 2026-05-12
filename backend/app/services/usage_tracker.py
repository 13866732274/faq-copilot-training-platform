from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UsageRecord
from app.utils.security import decode_access_token


@dataclass
class UsageContext:
    tenant_id: int | None
    user_id: int | None
    module_id: str | None


def _resolve_module_id(path: str) -> str | None:
    if path.startswith("/api/v1/faq"):
        return "mod_faq"
    if path.startswith("/api/v1/system/exports"):
        return "mod_export"
    if path.startswith("/api/v1/audit-logs"):
        return "mod_audit"
    if path.startswith("/api/v1/stats"):
        return "mod_stats"
    if path.startswith("/api/v1/practice/") and path.endswith("/ai-score"):
        return "mod_ai_scoring"
    if path.startswith("/api/v1/quizzes"):
        return "mod_training"
    if path.startswith("/api/v1/practice"):
        return "mod_training"
    if path.startswith("/api/v1/records"):
        return "mod_training"
    if path.startswith("/api/v1/import-tasks"):
        return "mod_training"
    return None


def should_track_usage(path: str, method: str) -> bool:
    if method.upper() == "OPTIONS":
        return False
    if not path.startswith("/api/v1/"):
        return False
    if path in {"/api/v1/health", "/openapi.json", "/docs", "/redoc"}:
        return False
    return _resolve_module_id(path) is not None


def _extract_auth_context(request: Request) -> tuple[int | None, int | None]:
    auth = str(request.headers.get("authorization") or "")
    if not auth.lower().startswith("bearer "):
        return None, None
    token = auth.split(" ", 1)[1].strip()
    if not token:
        return None, None
    try:
        payload = decode_access_token(token)
    except ValueError:
        return None, None

    try:
        user_id = int(payload.get("sub", "0"))
    except (TypeError, ValueError):
        user_id = None

    tenant_claim = payload.get("imp_tid", payload.get("tid"))
    try:
        tenant_id = int(tenant_claim) if tenant_claim is not None else 1
    except (TypeError, ValueError):
        tenant_id = 1
    return tenant_id, user_id


def build_usage_context(request: Request) -> UsageContext:
    path = request.url.path
    module_id = _resolve_module_id(path)
    tenant_id, user_id = _extract_auth_context(request)
    return UsageContext(tenant_id=tenant_id, user_id=user_id, module_id=module_id)


async def append_request_usage(
    db: AsyncSession,
    *,
    request: Request,
    status_code: int,
    elapsed_ms: float,
) -> None:
    if int(status_code) >= 400:
        return
    context = build_usage_context(request)
    if not context.module_id:
        return
    if context.user_id is None:
        # 未登录请求不计费
        return

    db.add(
        UsageRecord(
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            module_id=context.module_id,
            action="api_request",
            endpoint=request.url.path[:255],
            method=request.method.upper()[:10],
            status_code=int(status_code),
            duration_ms=max(0, int(round(elapsed_ms))),
            quantity=1,
            unit="request",
            meta_json={
                "query": str(request.url.query or "")[:1024],
            },
        )
    )

