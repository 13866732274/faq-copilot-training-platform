from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import ensure_tenant_active, ensure_tenant_bound, get_current_user, is_platform_super_admin
from app.models import AuditLog, Department, Hospital, Tenant, User, UserDepartment, UserHospital
from app.schemas.auth import (
    ApiResponse,
    ImpersonationStartRequest,
    LoginData,
    LoginHistoryItem,
    LoginRequest,
    LoginUser,
    MenuAccessItem,
    MeData,
    PermissionPointItem,
    PermissionPointsData,
    PasswordChangeData,
    PasswordChangeRequest,
    ProfileUpdateData,
    ProfileUpdateRequest,
)
from app.services.audit import append_audit_log
from app.services.login_limiter import check_allowed, mark_failure, mark_success
from app.services.module_registry import get_enabled_module_ids
from app.services.permission_points import build_permission_context
from app.utils.security import create_access_token, hash_password, verify_password

router = APIRouter()


def _parse_menu_permissions(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(value, list):
        return None
    return [str(item) for item in value if isinstance(item, str)]


def _get_effective_tenant_id(user: User) -> int | None:
    tid = getattr(user, "_effective_tenant_id", None)
    if tid is not None:
        return int(tid)
    return int(user.tenant_id) if user.tenant_id is not None else None


def _get_impersonation_meta(user: User) -> tuple[bool, int | None, str | None, str | None, str | None]:
    is_impersonating = bool(getattr(user, "_is_impersonating", False))
    imp_tid = int(getattr(user, "_effective_tenant_id", 0) or 0) or None
    imp_tenant_name = str(getattr(user, "_effective_tenant_name", "") or "") or None
    imp_reason = str(getattr(user, "_impersonation_reason", "") or "") or None
    imp_exp = int(getattr(user, "_impersonation_exp", 0) or 0)
    imp_exp_str = None
    if imp_exp > 0:
        try:
            from datetime import datetime

            imp_exp_str = datetime.fromtimestamp(imp_exp).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            imp_exp_str = None
    return is_impersonating, imp_tid, imp_tenant_name, imp_exp_str, imp_reason


async def _build_login_user(db: AsyncSession, user: User) -> LoginUser:
    hospital_ids_rows = (await db.execute(select(UserHospital.hospital_id).where(UserHospital.user_id == user.id))).all()
    hospital_ids = sorted({int(r[0]) for r in hospital_ids_rows})
    if user.hospital_id and user.hospital_id not in hospital_ids:
        hospital_ids.append(int(user.hospital_id))
    department_ids_rows = (
        await db.execute(select(UserDepartment.department_id).where(UserDepartment.user_id == user.id))
    ).all()
    department_ids = sorted({int(r[0]) for r in department_ids_rows})
    if user.department_id and user.department_id not in department_ids:
        department_ids.append(int(user.department_id))

    effective_tenant_id = _get_effective_tenant_id(user)
    effective_tenant_name = None
    if bool(getattr(user, "_is_impersonating", False)):
        effective_tenant_name = str(getattr(user, "_effective_tenant_name", "") or "") or None
    elif getattr(user, "tenant", None):
        effective_tenant_name = user.tenant.name
    elif effective_tenant_id:
        tenant = (await db.execute(select(Tenant).where(Tenant.id == effective_tenant_id))).scalars().first()
        effective_tenant_name = tenant.name if tenant else None
    is_impersonating, imp_tid, imp_tenant_name, imp_exp_str, imp_reason = _get_impersonation_meta(user)
    enabled_modules = sorted(await get_enabled_module_ids(db, ensure_tenant_bound(user)))

    return LoginUser(
        id=user.id,
        username=user.username,
        real_name=user.real_name,
        role=user.role,
        hospital_id=user.hospital_id,
        hospital_name=user.hospital.name if user.hospital else None,
        hospital_ids=hospital_ids,
        department_id=user.department_id,
        department_name=user.department.name if user.department else None,
        department_ids=department_ids,
        menu_permissions=_parse_menu_permissions(user.menu_permissions),
        is_all_hospitals=bool(user.is_all_hospitals or user.role == "super_admin"),
        avatar=user.avatar,
        tenant_id=effective_tenant_id,
        tenant_name=effective_tenant_name,
        is_platform_super_admin=is_platform_super_admin(user),
        is_impersonating=is_impersonating,
        impersonation_tenant_id=imp_tid,
        impersonation_tenant_name=imp_tenant_name,
        impersonation_expires_at=imp_exp_str,
        impersonation_reason=imp_reason,
        enabled_modules=enabled_modules,
    )


@router.post("/login", response_model=ApiResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    forwarded = request.headers.get("x-forwarded-for") or ""
    client_ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")
    allowed, wait_minutes = check_allowed(client_ip, payload.username)
    if not allowed:
        await append_audit_log(
            db,
            action="login_fail",
            user_id=None,
            target_type="auth",
            detail={"username": payload.username, "reason": "rate_limited"},
            ip=client_ip,
        )
        await db.commit()
        raise HTTPException(status_code=429, detail=f"登录失败次数过多，请{wait_minutes}分钟后重试")

    login_filters = [User.username == payload.username]
    if payload.tenant_code:
        tenant_row = (
            await db.execute(select(Tenant).where(Tenant.code == payload.tenant_code))
        ).scalars().first()
        if not tenant_row:
            mark_failure(client_ip, payload.username)
            raise HTTPException(status_code=401, detail="租户编码不存在")
        if not tenant_row.is_active:
            mark_failure(client_ip, payload.username)
            raise HTTPException(status_code=401, detail="该租户已停用")
        login_filters.append(User.tenant_id == tenant_row.id)
    else:
        login_filters.append(User.tenant_id.is_(None))
    stmt = (
        select(User)
        .options(selectinload(User.hospital), selectinload(User.department), selectinload(User.tenant))
        .where(*login_filters)
    )
    user = (await db.execute(stmt)).scalars().first()
    if not user and not payload.tenant_code:
        stmt_fallback = (
            select(User)
            .options(selectinload(User.hospital), selectinload(User.department), selectinload(User.tenant))
            .where(User.username == payload.username)
            .limit(1)
        )
        user = (await db.execute(stmt_fallback)).scalars().first()
    if not user or not user.is_active:
        mark_failure(client_ip, payload.username)
        await append_audit_log(
            db,
            action="login_fail",
            user_id=user.id if user else None,
            target_type="auth",
            target_id=user.id if user else None,
            hospital_id=user.hospital_id if user else None,
            department_id=user.department_id if user else None,
            detail={"username": payload.username, "reason": "user_not_found_or_inactive"},
            ip=client_ip,
        )
        await db.commit()
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not verify_password(payload.password, user.password_hash):
        mark_failure(client_ip, payload.username)
        await append_audit_log(
            db,
            action="login_fail",
            user_id=user.id,
            target_type="auth",
            target_id=user.id,
            hospital_id=user.hospital_id,
            department_id=user.department_id,
            detail={"username": payload.username, "reason": "bad_password"},
            ip=client_ip,
        )
        await db.commit()
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    tenant = await ensure_tenant_active(user, db)
    mark_success(client_ip, payload.username)
    token_claims: dict = {}
    if tenant and user.tenant_id:
        token_claims = {
            "tid": int(user.tenant_id),
            "tsv": int(tenant.session_version or 1),
        }
    token = create_access_token(user.id, token_claims)
    await append_audit_log(
        db,
        action="login_success",
        user_id=user.id,
        target_type="auth",
        target_id=user.id,
        hospital_id=user.hospital_id,
        department_id=user.department_id,
        detail={"username": user.username, "role": user.role},
        ip=client_ip,
    )
    await db.commit()
    return ApiResponse(
        code=200,
        message="success",
        data=LoginData(
            access_token=token,
            user=await _build_login_user(db, user),
        ),
    )


@router.get("/me", response_model=ApiResponse)
async def me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    hospital_name = None
    department_name = None
    tenant_name = None
    effective_tenant_id = _get_effective_tenant_id(current_user)
    if bool(getattr(current_user, "_is_impersonating", False)):
        tenant_name = str(getattr(current_user, "_effective_tenant_name", "") or "") or None
    elif effective_tenant_id:
        tenant = (await db.execute(select(Tenant).where(Tenant.id == effective_tenant_id))).scalars().first()
        tenant_name = tenant.name if tenant else None
    if current_user.hospital_id:
        hospital = (
            await db.execute(select(Hospital).where(Hospital.id == current_user.hospital_id))
        ).scalars().first()
        hospital_name = hospital.name if hospital else None
    if current_user.department_id:
        department = (
            await db.execute(select(Department).where(Department.id == current_user.department_id))
        ).scalars().first()
        department_name = department.name if department else None
    hospital_ids_rows = (await db.execute(select(UserHospital.hospital_id).where(UserHospital.user_id == current_user.id))).all()
    hospital_ids = sorted({int(r[0]) for r in hospital_ids_rows})
    if current_user.hospital_id and current_user.hospital_id not in hospital_ids:
        hospital_ids.append(int(current_user.hospital_id))
    department_ids_rows = (
        await db.execute(select(UserDepartment.department_id).where(UserDepartment.user_id == current_user.id))
    ).all()
    department_ids = sorted({int(r[0]) for r in department_ids_rows})
    if current_user.department_id and current_user.department_id not in department_ids:
        department_ids.append(int(current_user.department_id))
    is_impersonating, imp_tid, imp_tenant_name, imp_exp_str, imp_reason = _get_impersonation_meta(current_user)
    enabled_modules = sorted(await get_enabled_module_ids(db, ensure_tenant_bound(current_user)))
    return ApiResponse(
        code=200,
        message="success",
        data=MeData(
            id=current_user.id,
            username=current_user.username,
            real_name=current_user.real_name,
            role=current_user.role,
            hospital_id=current_user.hospital_id,
            hospital_name=hospital_name,
            hospital_ids=hospital_ids,
            department_id=current_user.department_id,
            department_name=department_name,
            department_ids=department_ids,
            menu_permissions=_parse_menu_permissions(current_user.menu_permissions),
            is_all_hospitals=bool(current_user.is_all_hospitals or current_user.role == "super_admin"),
            is_active=current_user.is_active,
            avatar=current_user.avatar,
            tenant_id=effective_tenant_id,
            tenant_name=tenant_name,
            is_platform_super_admin=is_platform_super_admin(current_user),
            is_impersonating=is_impersonating,
            impersonation_tenant_id=imp_tid,
            impersonation_tenant_name=imp_tenant_name,
            impersonation_expires_at=imp_exp_str,
            impersonation_reason=imp_reason,
            enabled_modules=enabled_modules,
        ),
    )


@router.post("/impersonation/start", response_model=ApiResponse)
async def start_impersonation(
    payload: ImpersonationStartRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    if current_user.role != "super_admin" or bool(getattr(current_user, "_is_impersonating", False)):
        raise HTTPException(status_code=403, detail="仅非代入态超级管理员可开启租户代入")
    tenant = (await db.execute(select(Tenant).where(Tenant.id == payload.tenant_id))).scalars().first()
    if not tenant:
        raise HTTPException(status_code=404, detail="目标租户不存在")
    if not tenant.is_active:
        raise HTTPException(status_code=400, detail="目标租户已停用，不能代入")

    duration = max(5, min(int(payload.duration_minutes or 30), 120))
    reason = (payload.reason or "").strip()
    from datetime import datetime, timedelta, timezone

    imp_exp_dt = datetime.now(timezone.utc) + timedelta(minutes=duration)
    token = create_access_token(
        current_user.id,
        {
            "tid": int(tenant.id),
            "tsv": int(tenant.session_version or 1),
            "imp": 1,
            "imp_tid": int(tenant.id),
            "imp_tcode": tenant.code,
            "imp_tname": tenant.name,
            "imp_reason": reason,
            "imp_exp": int(imp_exp_dt.timestamp()),
        },
        expire_minutes=duration,
    )

    # Fill effective context for response payload.
    setattr(current_user, "_is_impersonating", True)
    setattr(current_user, "_effective_tenant_id", int(tenant.id))
    setattr(current_user, "_effective_tenant_name", tenant.name)
    setattr(current_user, "_impersonation_reason", reason)
    setattr(current_user, "_impersonation_exp", int(imp_exp_dt.timestamp()))

    forwarded = request.headers.get("x-forwarded-for") or ""
    client_ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")
    await append_audit_log(
        db,
        action="tenant_impersonation_start",
        user_id=current_user.id,
        target_type="tenant",
        target_id=tenant.id,
        tenant_id=tenant.id,
        detail={"tenant_code": tenant.code, "tenant_name": tenant.name, "duration_minutes": duration, "reason": reason},
        ip=client_ip,
    )
    await db.commit()
    return ApiResponse(
        code=200,
        message="success",
        data=LoginData(access_token=token, user=await _build_login_user(db, current_user)),
    )


@router.post("/impersonation/stop", response_model=ApiResponse)
async def stop_impersonation(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    if current_user.role != "super_admin" or not bool(getattr(current_user, "_is_impersonating", False)):
        raise HTTPException(status_code=400, detail="当前不在租户代入状态")
    base_token = create_access_token(current_user.id)
    imp_tid = int(getattr(current_user, "_effective_tenant_id", 0) or 0) or None
    imp_tname = str(getattr(current_user, "_effective_tenant_name", "") or "") or None
    imp_reason = str(getattr(current_user, "_impersonation_reason", "") or "") or None

    setattr(current_user, "_is_impersonating", False)
    setattr(current_user, "_effective_tenant_id", None)
    setattr(current_user, "_effective_tenant_name", None)
    setattr(current_user, "_impersonation_reason", None)
    setattr(current_user, "_impersonation_exp", None)

    forwarded = request.headers.get("x-forwarded-for") or ""
    client_ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")
    await append_audit_log(
        db,
        action="tenant_impersonation_stop",
        user_id=current_user.id,
        target_type="tenant",
        target_id=imp_tid,
        tenant_id=imp_tid,
        detail={"tenant_name": imp_tname, "reason": imp_reason},
        ip=client_ip,
    )
    await db.commit()
    return ApiResponse(
        code=200,
        message="success",
        data=LoginData(access_token=base_token, user=await _build_login_user(db, current_user)),
    )


@router.put("/password", response_model=ApiResponse)
async def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="当前密码不正确")
    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=400, detail="新密码不能与当前密码相同")
    if len(payload.new_password or "") < 6:
        raise HTTPException(status_code=400, detail="新密码长度不能少于6位")
    current_user.password_hash = hash_password(payload.new_password)
    await append_audit_log(
        db,
        action="user_permission_change",
        user_id=current_user.id,
        target_type="auth",
        target_id=current_user.id,
        hospital_id=current_user.hospital_id,
        department_id=current_user.department_id,
        detail={"type": "change_password"},
        ip=(request.client.host if request.client else "unknown"),
    )
    await db.commit()
    return ApiResponse(code=200, message="密码修改成功", data=PasswordChangeData(updated=True))


@router.put("/profile", response_model=ApiResponse)
async def update_profile(
    payload: ProfileUpdateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    if payload.real_name is not None:
        name = payload.real_name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="姓名不能为空")
        current_user.real_name = name
    if payload.avatar is not None:
        avatar = payload.avatar.strip()
        current_user.avatar = avatar or None
    await append_audit_log(
        db,
        action="user_permission_change",
        user_id=current_user.id,
        target_type="profile",
        target_id=current_user.id,
        hospital_id=current_user.hospital_id,
        department_id=current_user.department_id,
        detail={"type": "update_profile"},
        ip=(request.client.host if request.client else "unknown"),
    )
    await db.commit()
    await db.refresh(current_user)
    return ApiResponse(
        code=200,
        message="资料更新成功",
        data=ProfileUpdateData(
            id=current_user.id,
            username=current_user.username,
            real_name=current_user.real_name,
            avatar=current_user.avatar,
        ),
    )


@router.get("/login-history", response_model=ApiResponse)
async def login_history(
    limit: int = 5,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    safe_limit = min(max(int(limit or 5), 1), 20)
    stmt = (
        select(AuditLog)
        .where(AuditLog.user_id == current_user.id, AuditLog.action.in_(["login_success", "login_fail"]))
        .order_by(AuditLog.id.desc())
        .limit(safe_limit)
    )
    logs = (await db.execute(stmt)).scalars().all()
    items = [
        LoginHistoryItem(
            id=log.id,
            status="success" if log.action == "login_success" else "fail",
            ip=log.ip,
            reason=((log.detail or {}).get("reason") if isinstance(log.detail, dict) else None),
            created_at=log.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        )
        for log in logs
    ]
    return ApiResponse(code=200, message="success", data=items)


@router.get("/permission-points", response_model=ApiResponse)
async def permission_points(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    point_decisions, menu_decisions = await build_permission_context(current_user, db)
    return ApiResponse(
        code=200,
        message="success",
        data=PermissionPointsData(
            points=[
                PermissionPointItem(point=item.point, allowed=item.allowed, reason=item.reason)
                for item in point_decisions
            ],
            menus=[
                MenuAccessItem(menu_key=item.menu_key, allowed=item.allowed, reason=item.reason)
                for item in menu_decisions
            ],
        ),
    )
