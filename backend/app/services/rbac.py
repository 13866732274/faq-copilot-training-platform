from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_accessible_department_ids, get_accessible_hospital_ids
from app.models import User
from app.services.audit import append_audit_log, get_request_ip


@dataclass
class RbacDecision:
    action: str
    allowed: bool
    reason: str
    role_ok: bool
    tenant_ok: bool
    scope_ok: bool
    required_roles: list[str]
    actor_role: str


def evaluate_rbac_decision(
    *,
    actor: User,
    action: str,
    required_roles: set[str],
    target_tenant_id: int | None = None,
    target_hospital_id: int | None = None,
    target_department_id: int | None = None,
    accessible_hospital_ids: list[int] | None = None,
    accessible_department_ids: list[int] | None = None,
) -> RbacDecision:
    actor_role = str(actor.role or "")
    role_ok = actor_role in required_roles or actor_role == "super_admin"

    # super_admin can跨租户跨范围管理，是平台级例外
    if actor_role == "super_admin":
        tenant_ok = True
        scope_ok = True
    else:
        tenant_ok = True
        if target_tenant_id is not None and actor.tenant_id is not None:
            tenant_ok = int(target_tenant_id) == int(actor.tenant_id)

        scope_ok = True
        if not bool(actor.is_all_hospitals):
            if target_hospital_id is not None and accessible_hospital_ids is not None:
                scope_ok = int(target_hospital_id) in {int(x) for x in accessible_hospital_ids}
            if scope_ok and target_department_id is not None and accessible_department_ids is not None:
                scope_ok = int(target_department_id) in {int(x) for x in accessible_department_ids}

    allowed = role_ok and tenant_ok and scope_ok
    if allowed:
        reason = "allowed"
    elif not role_ok:
        reason = "角色不满足要求"
    elif not tenant_ok:
        reason = "超出租户范围"
    else:
        reason = "超出医院/科室数据范围"

    return RbacDecision(
        action=action,
        allowed=allowed,
        reason=reason,
        role_ok=role_ok,
        tenant_ok=tenant_ok,
        scope_ok=scope_ok,
        required_roles=sorted(required_roles),
        actor_role=actor_role,
    )


async def enforce_rbac(
    *,
    db: AsyncSession,
    actor: User,
    action: str,
    required_roles: set[str],
    request: Request | None = None,
    target_tenant_id: int | None = None,
    target_hospital_id: int | None = None,
    target_department_id: int | None = None,
    target_type: str = "rbac_action",
    target_id: int | None = None,
    extra_detail: dict[str, Any] | None = None,
) -> None:
    hospital_ids: list[int] | None = None
    department_ids: list[int] | None = None
    if actor.role != "super_admin" and not bool(actor.is_all_hospitals):
        hospital_ids = await get_accessible_hospital_ids(actor, db)
        department_ids = await get_accessible_department_ids(actor, db)

    decision = evaluate_rbac_decision(
        actor=actor,
        action=action,
        required_roles=required_roles,
        target_tenant_id=target_tenant_id,
        target_hospital_id=target_hospital_id,
        target_department_id=target_department_id,
        accessible_hospital_ids=hospital_ids,
        accessible_department_ids=department_ids,
    )
    if decision.allowed:
        return

    detail = {
        "action": action,
        "reason": decision.reason,
        "role_ok": decision.role_ok,
        "tenant_ok": decision.tenant_ok,
        "scope_ok": decision.scope_ok,
        "required_roles": decision.required_roles,
        "actor_role": decision.actor_role,
        "actor_tenant_id": actor.tenant_id,
        "target_tenant_id": target_tenant_id,
        "target_hospital_id": target_hospital_id,
        "target_department_id": target_department_id,
    }
    if extra_detail:
        detail.update(extra_detail)
    await append_audit_log(
        db,
        action="rbac_deny",
        user_id=actor.id,
        target_type=target_type,
        target_id=target_id,
        hospital_id=target_hospital_id,
        department_id=target_department_id,
        tenant_id=target_tenant_id or actor.tenant_id,
        detail=detail,
        ip=get_request_ip(request),
    )
    await db.commit()
    raise HTTPException(status_code=403, detail=f"无权执行该操作：{decision.reason}")
