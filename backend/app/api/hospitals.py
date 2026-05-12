from __future__ import annotations

import hashlib
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import ensure_tenant_bound, get_accessible_hospital_ids, require_admin, require_super_admin
from app.models import Department, Hospital, User, UserDepartment, UserHospital
from app.services.audit import append_audit_log, get_request_ip
from app.services.rbac import enforce_rbac
from app.schemas.hospital import (
    ApiResponse,
    HospitalAssignUsersRequest,
    HospitalCreateRequest,
    HospitalItem,
    HospitalUpdateRequest,
)

router = APIRouter()


def _build_code_base(name: str) -> str:
    lowered = name.strip().lower()
    ascii_slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    if len(ascii_slug) >= 2:
        return ascii_slug[:40]
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:10]
    return f"hospital-{digest}"


def _derive_short_name(name: str) -> str:
    text = name.strip()
    short = re.sub(r"耳鼻咽喉科$", "", text).strip()
    return short or text


async def _generate_unique_code(db: AsyncSession, name: str) -> str:
    base = _build_code_base(name)
    candidate = base
    idx = 1
    while True:
        existed = (await db.execute(select(Hospital.id).where(Hospital.code == candidate))).scalars().first()
        if not existed:
            return candidate
        idx += 1
        suffix = f"-{idx}"
        candidate = f"{base[: max(2, 50 - len(suffix))]}{suffix}"


@router.get("", response_model=ApiResponse)
async def list_hospitals(
    request: Request,
    active_only: bool = Query(default=False),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="hospital:list",
        required_roles={"admin", "super_admin"},
        request=request,
        target_tenant_id=(int(current_user.tenant_id) if current_user.tenant_id else None),
        target_type="hospital",
        extra_detail={"active_only": bool(active_only)},
    )
    tenant_id = ensure_tenant_bound(current_user)
    filters = [Hospital.tenant_id == tenant_id]
    if active_only:
        filters.append(Hospital.is_active.is_(True))
    if current_user.role != "super_admin" and not current_user.is_all_hospitals:
        ids = await get_accessible_hospital_ids(current_user, db)
        filters.append(Hospital.id.in_(ids))
    stmt = select(Hospital).where(*filters).order_by(Hospital.id.asc())
    rows = (await db.execute(stmt)).scalars().all()
    data = [
        HospitalItem(
            id=h.id,
            code=h.code,
            name=h.name,
            short_name=h.short_name,
            is_active=h.is_active,
            created_at=h.created_at,
        )
        for h in rows
    ]
    return ApiResponse(code=200, message="success", data=data)


@router.post("", response_model=ApiResponse)
async def create_hospital(
    payload: HospitalCreateRequest,
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    tenant_id = ensure_tenant_bound(current_user)
    name = payload.name.strip()
    short_name = payload.short_name.strip() if payload.short_name else _derive_short_name(name)
    if not short_name:
        short_name = _derive_short_name(name)
    existed = (
        await db.execute(select(Hospital).where(Hospital.name == name, Hospital.tenant_id == tenant_id))
    ).scalars().first()
    if existed:
        raise HTTPException(status_code=400, detail="医院名称已存在")
    code = payload.code.strip() if payload.code else await _generate_unique_code(db, name)
    if payload.code:
        code_exists = (await db.execute(select(Hospital.id).where(Hospital.code == code))).scalars().first()
        if code_exists:
            raise HTTPException(status_code=400, detail="医院编码已存在")
    row = Hospital(code=code, name=name, short_name=short_name, is_active=True, tenant_id=tenant_id)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return ApiResponse(
        code=200,
        message="success",
        data=HospitalItem(
            id=row.id,
            code=row.code,
            name=row.name,
            short_name=row.short_name,
            is_active=row.is_active,
            created_at=row.created_at,
        ),
    )


@router.put("/{hospital_id}", response_model=ApiResponse)
async def update_hospital(
    hospital_id: int,
    payload: HospitalUpdateRequest,
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    tenant_id = ensure_tenant_bound(current_user)
    row = (
        await db.execute(select(Hospital).where(Hospital.id == hospital_id, Hospital.tenant_id == tenant_id))
    ).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="医院不存在")
    if payload.code is not None:
        code = payload.code.strip()
        existed = (
            await db.execute(select(Hospital).where(Hospital.code == code, Hospital.id != hospital_id))
        ).scalars().first()
        if existed:
            raise HTTPException(status_code=400, detail="医院编码已存在")
        row.code = code
    if payload.name is not None:
        name = payload.name.strip()
        existed = (
            await db.execute(select(Hospital).where(Hospital.name == name, Hospital.id != hospital_id))
        ).scalars().first()
        if existed:
            raise HTTPException(status_code=400, detail="医院名称已存在")
        row.name = name
        if not row.short_name:
            row.short_name = _derive_short_name(name)
    if payload.short_name is not None:
        row.short_name = payload.short_name.strip() or _derive_short_name(row.name)
    if payload.is_active is not None:
        row.is_active = payload.is_active
    await db.commit()
    await db.refresh(row)
    return ApiResponse(
        code=200,
        message="success",
        data=HospitalItem(
            id=row.id,
            code=row.code,
            name=row.name,
            short_name=row.short_name,
            is_active=row.is_active,
            created_at=row.created_at,
        ),
    )


@router.put("/{hospital_id}/assign-users", response_model=ApiResponse)
async def assign_users_to_hospital(
    hospital_id: int,
    payload: HospitalAssignUsersRequest,
    request: Request,
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    tenant_id = ensure_tenant_bound(current_user)
    user_ids = sorted({int(uid) for uid in payload.user_ids if uid})
    mode = payload.mode
    row = (
        await db.execute(select(Hospital).where(Hospital.id == hospital_id, Hospital.tenant_id == tenant_id))
    ).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="医院不存在")
    if not user_ids:
        return ApiResponse(code=200, message="success", data=row)

    users = (
        await db.execute(select(User).where(User.id.in_(user_ids), User.tenant_id == tenant_id))
    ).scalars().all()
    default_department_id = (
        await db.execute(
            select(Department.id)
            .where(Department.hospital_id == hospital_id, Department.tenant_id == tenant_id)
            .order_by(Department.id.asc())
            .limit(1)
        )
    ).scalars().first()
    touched_user_ids = [u.id for u in users]
    for user in users:
        if user.role == "student":
            user.hospital_id = hospital_id
            if default_department_id:
                user.department_id = int(default_department_id)
                old_dep_links = (
                    await db.execute(select(UserDepartment).where(UserDepartment.user_id == user.id))
                ).scalars().all()
                for link in old_dep_links:
                    await db.delete(link)
                db.add(UserDepartment(user_id=user.id, department_id=int(default_department_id)))
        elif user.role in {"admin", "super_admin"}:
            if mode == "replace":
                old_links = (
                    await db.execute(select(UserHospital).where(UserHospital.user_id == user.id))
                ).scalars().all()
                for link in old_links:
                    await db.delete(link)
            exists = (
                await db.execute(
                    select(UserHospital).where(
                        UserHospital.user_id == user.id,
                        UserHospital.hospital_id == hospital_id,
                    )
                )
            ).scalars().first()
            if not exists:
                db.add(UserHospital(user_id=user.id, hospital_id=hospital_id))
            if default_department_id:
                dep_exists = (
                    await db.execute(
                        select(UserDepartment).where(
                            UserDepartment.user_id == user.id,
                            UserDepartment.department_id == int(default_department_id),
                        )
                    )
                ).scalars().first()
                if not dep_exists:
                    db.add(UserDepartment(user_id=user.id, department_id=int(default_department_id)))
            if not user.hospital_id:
                user.hospital_id = hospital_id
            if not user.department_id and default_department_id:
                user.department_id = int(default_department_id)

    await append_audit_log(
        db,
        action="hospital_assign",
        user_id=current_user.id,
        target_type="hospital",
        target_id=row.id,
        hospital_id=row.id,
        department_id=int(default_department_id) if default_department_id else None,
        detail={"mode": mode, "user_ids": touched_user_ids, "requested_user_ids": user_ids},
        ip=get_request_ip(request),
    )
    await db.commit()
    await db.refresh(row)
    return ApiResponse(
        code=200,
        message="success",
        data=HospitalItem(
            id=row.id,
            code=row.code,
            name=row.name,
            short_name=row.short_name,
            is_active=row.is_active,
            created_at=row.created_at,
        ),
    )


@router.delete("/{hospital_id}", response_model=ApiResponse)
async def toggle_hospital(
    hospital_id: int,
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    tenant_id = ensure_tenant_bound(current_user)
    row = (
        await db.execute(select(Hospital).where(Hospital.id == hospital_id, Hospital.tenant_id == tenant_id))
    ).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="医院不存在")
    row.is_active = not row.is_active
    await db.commit()
    await db.refresh(row)
    return ApiResponse(
        code=200,
        message="success",
        data=HospitalItem(
            id=row.id,
            code=row.code,
            name=row.name,
            short_name=row.short_name,
            is_active=row.is_active,
            created_at=row.created_at,
        ),
    )
