from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from app.models import AuditLog, User


def get_request_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    forwarded = request.headers.get("x-forwarded-for") or ""
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    if request.client:
        return request.client.host
    return None


def build_user_snapshot(
    *,
    role: str | None,
    real_name: str | None,
    hospital_id: int | None,
    department_id: int | None = None,
) -> dict[str, Any]:
    return {
        "role": role,
        "real_name": real_name,
        "hospital_id": hospital_id,
        "department_id": department_id,
    }


async def append_audit_log(
    db: AsyncSession,
    *,
    action: str,
    user_id: int | None,
    target_type: str = "system",
    target_id: int | None = None,
    hospital_id: int | None = None,
    department_id: int | None = None,
    tenant_id: int | None = None,
    detail: dict[str, Any] | None = None,
    ip: str | None = None,
) -> None:
    resolved_tenant_id = tenant_id
    if resolved_tenant_id is None and user_id:
        resolved_tenant_id = (
            await db.execute(select(User.tenant_id).where(User.id == user_id))
        ).scalar_one_or_none()
    db.add(
        AuditLog(
            tenant_id=resolved_tenant_id,
            user_id=user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            hospital_id=hospital_id,
            department_id=department_id,
            detail=detail,
            ip=ip,
        )
    )
