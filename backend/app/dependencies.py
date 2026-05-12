from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Department, Tenant, User, UserDepartment, UserHospital
from app.services.module_registry import is_module_enabled
from app.utils.security import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)
PLATFORM_TENANT_ID = 1


@dataclass
class TenantContext:
    tenant_id: int | None
    tenant_code: str | None
    tenant_name: str | None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not credentials:
        raise HTTPException(status_code=401, detail="未提供登录凭证")

    try:
        payload = decode_access_token(credentials.credentials)
        user_id = int(payload.get("sub", "0"))
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="登录凭证无效")

    stmt = select(User).where(User.id == user_id)
    user = (await db.execute(stmt)).scalars().first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="用户不存在或已被禁用")
    impersonation_tid = payload.get("imp_tid")
    impersonation_enabled = bool(payload.get("imp") and impersonation_tid is not None)
    if impersonation_enabled:
        if user.role != "super_admin":
            raise HTTPException(status_code=401, detail="代入凭证无效")
        try:
            effective_tenant_id = int(impersonation_tid)
        except (TypeError, ValueError):
            raise HTTPException(status_code=401, detail="代入凭证无效")
        tenant_row = (await db.execute(select(Tenant).where(Tenant.id == effective_tenant_id))).scalars().first()
        if not tenant_row:
            raise HTTPException(status_code=401, detail="代入租户不存在")
        if not tenant_row.is_active:
            raise HTTPException(status_code=403, detail="代入租户已停用")
        setattr(user, "_is_impersonating", True)
        setattr(user, "_effective_tenant_id", effective_tenant_id)
        setattr(user, "_effective_tenant_code", tenant_row.code)
        setattr(user, "_effective_tenant_name", tenant_row.name)
        setattr(user, "_impersonation_reason", str(payload.get("imp_reason") or ""))
        setattr(user, "_impersonation_exp", int(payload.get("imp_exp") or 0))
    else:
        setattr(user, "_is_impersonating", False)
    tenant = await ensure_tenant_active(user, db)
    await ensure_tenant_session_valid(user, payload, db, tenant=tenant)
    return user


async def ensure_tenant_active(user: User, db: AsyncSession) -> Tenant | None:
    """Block disabled-tenant accounts from using authenticated APIs.

    Super admin is exempted to avoid total lockout in emergency cases.
    """
    if is_platform_super_admin(user):
        return None
    tenant_id = int(getattr(user, "_effective_tenant_id", user.tenant_id) or 0)
    if not tenant_id:
        return None
    tenant = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalars().first()
    if tenant and not tenant.is_active:
        raise HTTPException(status_code=403, detail="所属租户已停用，请联系平台管理员")
    return tenant


async def ensure_tenant_session_valid(
    user: User,
    token_payload: dict,
    db: AsyncSession,
    *,
    tenant: Tenant | None = None,
) -> None:
    """Validate tenant-scoped session version to support mass logout."""
    is_impersonating = bool(getattr(user, "_is_impersonating", False))
    if is_platform_super_admin(user) and not is_impersonating:
        return
    effective_tenant_id = int(getattr(user, "_effective_tenant_id", user.tenant_id) or 0)
    if not effective_tenant_id:
        return
    current_tenant = tenant or (
        await db.execute(select(Tenant).where(Tenant.id == effective_tenant_id))
    ).scalars().first()
    if not current_tenant:
        return
    current_version = int(current_tenant.session_version or 1)
    token_tid = token_payload.get("tid")
    token_tsv = token_payload.get("tsv")

    # Backward compatibility: old tokens without tenant claims are only accepted
    # when tenant session version is still initial.
    if token_tid is None or token_tsv is None:
        if current_version > 1:
            raise HTTPException(status_code=401, detail="登录会话已失效，请重新登录")
        return
    try:
        token_tenant_id = int(token_tid)
        token_session_version = int(token_tsv)
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="登录会话已失效，请重新登录")

    if token_tenant_id != int(current_tenant.id) or token_session_version != current_version:
        raise HTTPException(status_code=401, detail="登录会话已失效，请重新登录")


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in {"admin", "super_admin"}:
        raise HTTPException(status_code=403, detail="无管理员权限")
    return current_user


async def require_super_admin(current_user: User = Depends(get_current_user)) -> User:
    if bool(getattr(current_user, "_is_impersonating", False)):
        raise HTTPException(status_code=403, detail="代入模式下不允许执行超级管理员操作，请先退出代入")
    if current_user.role != "super_admin":
        raise HTTPException(status_code=403, detail="仅超级管理员可执行该操作")
    return current_user


def is_platform_super_admin(user: User) -> bool:
    if getattr(user, "role", None) != "super_admin":
        return False
    if bool(getattr(user, "_is_impersonating", False)):
        return False
    effective_tenant_id = getattr(user, "_effective_tenant_id", None)
    tenant_id = effective_tenant_id if effective_tenant_id is not None else getattr(user, "tenant_id", None)
    return tenant_id in (None, PLATFORM_TENANT_ID)


async def require_platform_super_admin(current_user: User = Depends(get_current_user)) -> User:
    if not is_platform_super_admin(current_user):
        raise HTTPException(status_code=403, detail="仅平台超级管理员可执行该操作")
    return current_user


def require_module(module_id: str):
    async def checker(
        current_user: User = Depends(require_admin),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        # 平台超管（非代入态）默认放行，避免平台被配置锁死
        if is_platform_super_admin(current_user):
            return current_user
        tenant_id = ensure_tenant_bound(current_user)
        if not await is_module_enabled(db, tenant_id, module_id):
            raise HTTPException(status_code=403, detail=f"当前租户未开通模块：{module_id}")
        return current_user

    return checker


async def get_current_tenant_context(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TenantContext:
    if not current_user.tenant_id:
        return TenantContext(tenant_id=None, tenant_code=None, tenant_name=None)
    tenant = (await db.execute(select(Tenant).where(Tenant.id == current_user.tenant_id))).scalars().first()
    if not tenant:
        return TenantContext(tenant_id=current_user.tenant_id, tenant_code=None, tenant_name=None)
    return TenantContext(tenant_id=tenant.id, tenant_code=tenant.code, tenant_name=tenant.name)


def is_super_admin(user: User) -> bool:
    return user.role == "super_admin"


def ensure_hospital_bound(user: User, *, for_role: str = "当前账号") -> int:
    if user.hospital_id is None:
        raise HTTPException(status_code=400, detail=f"{for_role}未绑定医院，请先在用户管理中设置医院")
    return user.hospital_id


def ensure_department_bound(user: User, *, for_role: str = "当前账号") -> int:
    if user.department_id is None:
        raise HTTPException(status_code=400, detail=f"{for_role}未绑定科室，请先在用户管理中设置科室")
    return user.department_id


def ensure_tenant_bound(user: User, *, for_role: str = "当前账号") -> int:
    effective_tenant_id = getattr(user, "_effective_tenant_id", None)
    if effective_tenant_id is not None:
        return int(effective_tenant_id)
    if user.tenant_id is not None:
        return int(user.tenant_id)
    if getattr(user, "role", None) == "super_admin":
        return 1
    raise HTTPException(status_code=400, detail=f"{for_role}未绑定租户，请联系平台管理员")


async def get_accessible_department_ids(user: User, db: AsyncSession) -> list[int]:
    tenant_id = ensure_tenant_bound(user)
    if user.role == "super_admin" or user.is_all_hospitals:
        rows = (
            await db.execute(
                select(Department.id).where(Department.is_active.is_(True), Department.tenant_id == tenant_id)
            )
        ).all()
        return sorted({int(r[0]) for r in rows})

    ids: set[int] = set()
    if user.department_id:
        ids.add(int(user.department_id))

    dep_rows = (
        await db.execute(select(UserDepartment.department_id).where(UserDepartment.user_id == user.id))
    ).all()
    ids.update(int(r[0]) for r in dep_rows)

    # 兼容旧授权数据：如尚未迁移到 user_departments，尝试从医院权限反推科室
    hospital_ids: set[int] = set()
    if user.hospital_id:
        hospital_ids.add(int(user.hospital_id))
    hospital_rows = (
        await db.execute(select(UserHospital.hospital_id).where(UserHospital.user_id == user.id))
    ).all()
    hospital_ids.update(int(r[0]) for r in hospital_rows)
    if hospital_ids:
        mapped = (
            await db.execute(
                select(Department.id).where(
                    Department.hospital_id.in_(sorted(hospital_ids)),
                    Department.tenant_id == tenant_id,
                )
            )
        ).all()
        ids.update(int(r[0]) for r in mapped)

    if not ids and user.role in {"admin", "student"}:
        raise HTTPException(status_code=400, detail="当前账号未分配可管理科室，请联系超级管理员")
    return sorted(ids)


async def get_accessible_hospital_ids(user: User, db: AsyncSession) -> list[int]:
    tenant_id = ensure_tenant_bound(user)
    ids: set[int] = set()
    dept_ids = await get_accessible_department_ids(user, db)
    if dept_ids:
        rows = (
            await db.execute(
                select(Department.hospital_id).where(Department.id.in_(dept_ids), Department.tenant_id == tenant_id)
            )
        ).all()
        ids.update(int(r[0]) for r in rows if r[0] is not None)

    # 兼容旧数据：保留原 hospital 直连授权
    if user.hospital_id:
        ids.add(int(user.hospital_id))
    rows = (await db.execute(select(UserHospital.hospital_id).where(UserHospital.user_id == user.id))).all()
    ids.update(int(r[0]) for r in rows)
    if not ids and user.role in {"admin", "student"}:
        raise HTTPException(status_code=400, detail="当前账号未分配可管理医院，请联系超级管理员")
    return sorted(ids)
