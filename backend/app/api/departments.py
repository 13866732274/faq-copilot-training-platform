from __future__ import annotations

import hashlib
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import ensure_tenant_bound, get_accessible_department_ids, require_admin, require_super_admin
from app.models import Department, Hospital, User, UserDepartment, UserHospital
from app.schemas.department import (
    ApiResponse,
    DepartmentAssignUsersRequest,
    DepartmentCreateRequest,
    DepartmentItem,
    DepartmentUpdateRequest,
)
from app.services.audit import append_audit_log, get_request_ip
from app.services.rbac import enforce_rbac

router = APIRouter()


def _build_code_base(hospital_name: str, department_name: str) -> str:
    lowered = f"{hospital_name.strip()}-{department_name.strip()}".lower()
    ascii_slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    if len(ascii_slug) >= 2:
        return ascii_slug[:40]
    digest = hashlib.sha1(f"{hospital_name}-{department_name}".encode("utf-8")).hexdigest()[:10]
    return f"dept-{digest}"


async def _generate_unique_code(db: AsyncSession, hospital_name: str, department_name: str) -> str:
    base = _build_code_base(hospital_name, department_name)
    candidate = base
    idx = 1
    while True:
        existed = (await db.execute(select(Department.id).where(Department.code == candidate))).scalars().first()
        if not existed:
            return candidate
        idx += 1
        suffix = f"-{idx}"
        candidate = f"{base[: max(2, 50 - len(suffix))]}{suffix}"


def _to_item(row: Department, hospital_name: str | None = None) -> DepartmentItem:
    return DepartmentItem(
        id=row.id,
        hospital_id=row.hospital_id,
        hospital_name=hospital_name,
        code=row.code,
        name=row.name,
        is_active=row.is_active,
        created_at=row.created_at,
    )


@router.get("", response_model=ApiResponse)
async def list_departments(
    request: Request,
    hospital_id: int | None = None,
    active_only: bool = Query(default=False),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="department:list",
        required_roles={"admin", "super_admin"},
        request=request,
        target_tenant_id=(int(current_user.tenant_id) if current_user.tenant_id else None),
        target_hospital_id=hospital_id,
        target_type="department",
        extra_detail={"active_only": bool(active_only)},
    )
    tenant_id = ensure_tenant_bound(current_user)
    filters = [Department.tenant_id == tenant_id]
    if hospital_id:
        filters.append(Department.hospital_id == hospital_id)
    if active_only:
        filters.append(Department.is_active.is_(True))
    if current_user.role != "super_admin" and not current_user.is_all_hospitals:
        ids = await get_accessible_department_ids(current_user, db)
        filters.append(Department.id.in_(ids))
    rows = (await db.execute(select(Department).where(*filters).order_by(Department.id.asc()))).scalars().all()
    hospital_ids = sorted({r.hospital_id for r in rows})
    hospital_map: dict[int, str] = {}
    if hospital_ids:
        hospitals = (await db.execute(select(Hospital).where(Hospital.id.in_(hospital_ids)))).scalars().all()
        hospital_map = {h.id: h.name for h in hospitals}
    data = [_to_item(r, hospital_map.get(r.hospital_id)) for r in rows]
    return ApiResponse(code=200, message="success", data=data)


@router.post("", response_model=ApiResponse)
async def create_department(
    payload: DepartmentCreateRequest,
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    tenant_id = ensure_tenant_bound(current_user)
    hospital = (
        await db.execute(select(Hospital).where(Hospital.id == payload.hospital_id, Hospital.tenant_id == tenant_id))
    ).scalars().first()
    if not hospital:
        raise HTTPException(status_code=404, detail="所属医院不存在")
    name = payload.name.strip()
    existed = (
        await db.execute(
            select(Department).where(
                Department.hospital_id == payload.hospital_id,
                Department.tenant_id == tenant_id,
                Department.name == name,
            )
        )
    ).scalars().first()
    if existed:
        raise HTTPException(status_code=400, detail="该医院下科室名称已存在")
    code = payload.code.strip() if payload.code else await _generate_unique_code(db, hospital.name, name)
    if payload.code:
        code_exists = (await db.execute(select(Department.id).where(Department.code == code))).scalars().first()
        if code_exists:
            raise HTTPException(status_code=400, detail="科室编码已存在")
    row = Department(hospital_id=payload.hospital_id, code=code, name=name, is_active=True, tenant_id=tenant_id)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return ApiResponse(code=200, message="success", data=_to_item(row, hospital.name))


@router.put("/{department_id}", response_model=ApiResponse)
async def update_department(
    department_id: int,
    payload: DepartmentUpdateRequest,
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    tenant_id = ensure_tenant_bound(current_user)
    row = (
        await db.execute(select(Department).where(Department.id == department_id, Department.tenant_id == tenant_id))
    ).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="科室不存在")
    if payload.code is not None:
        code = payload.code.strip()
        existed = (
            await db.execute(select(Department).where(Department.code == code, Department.id != department_id))
        ).scalars().first()
        if existed:
            raise HTTPException(status_code=400, detail="科室编码已存在")
        row.code = code
    if payload.name is not None:
        name = payload.name.strip()
        existed = (
            await db.execute(
                select(Department).where(
                    Department.hospital_id == row.hospital_id,
                    Department.tenant_id == tenant_id,
                    Department.name == name,
                    Department.id != department_id,
                )
            )
        ).scalars().first()
        if existed:
            raise HTTPException(status_code=400, detail="该医院下科室名称已存在")
        row.name = name
    if payload.is_active is not None:
        row.is_active = payload.is_active
    await db.commit()
    await db.refresh(row)
    hospital = (await db.execute(select(Hospital).where(Hospital.id == row.hospital_id))).scalars().first()
    return ApiResponse(code=200, message="success", data=_to_item(row, hospital.name if hospital else None))


@router.put("/{department_id}/assign-users", response_model=ApiResponse)
async def assign_users_to_department(
    department_id: int,
    payload: DepartmentAssignUsersRequest,
    request: Request,
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    tenant_id = ensure_tenant_bound(current_user)
    user_ids = sorted({int(uid) for uid in payload.user_ids if uid})
    mode = payload.mode
    row = (
        await db.execute(
            select(Department).where(Department.id == department_id, Department.tenant_id == tenant_id)
        )
    ).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="科室不存在")
    if not user_ids:
        hospital = (
            await db.execute(select(Hospital).where(Hospital.id == row.hospital_id, Hospital.tenant_id == tenant_id))
        ).scalars().first()
        return ApiResponse(code=200, message="success", data=_to_item(row, hospital.name if hospital else None))

    users = (
        await db.execute(select(User).where(User.id.in_(user_ids), User.tenant_id == tenant_id))
    ).scalars().all()
    touched_user_ids = [u.id for u in users]
    for user in users:
        if user.role == "student":
            user.department_id = row.id
            user.hospital_id = row.hospital_id
            old_deps = (await db.execute(select(UserDepartment).where(UserDepartment.user_id == user.id))).scalars().all()
            for link in old_deps:
                await db.delete(link)
            db.add(UserDepartment(user_id=user.id, department_id=row.id))
            old_hospitals = (await db.execute(select(UserHospital).where(UserHospital.user_id == user.id))).scalars().all()
            for link in old_hospitals:
                await db.delete(link)
            db.add(UserHospital(user_id=user.id, hospital_id=row.hospital_id))
        elif user.role in {"admin", "super_admin"}:
            if mode == "replace":
                old_deps = (
                    await db.execute(select(UserDepartment).where(UserDepartment.user_id == user.id))
                ).scalars().all()
                for link in old_deps:
                    await db.delete(link)
            exists_dep = (
                await db.execute(
                    select(UserDepartment).where(
                        UserDepartment.user_id == user.id,
                        UserDepartment.department_id == row.id,
                    )
                )
            ).scalars().first()
            if not exists_dep:
                db.add(UserDepartment(user_id=user.id, department_id=row.id))

            exists_hospital = (
                await db.execute(
                    select(UserHospital).where(
                        UserHospital.user_id == user.id,
                        UserHospital.hospital_id == row.hospital_id,
                    )
                )
            ).scalars().first()
            if not exists_hospital:
                db.add(UserHospital(user_id=user.id, hospital_id=row.hospital_id))
            if not user.department_id:
                user.department_id = row.id
            if not user.hospital_id:
                user.hospital_id = row.hospital_id

    await append_audit_log(
        db,
        action="department_assign",
        user_id=current_user.id,
        target_type="department",
        target_id=row.id,
        hospital_id=row.hospital_id,
        department_id=row.id,
        detail={"mode": mode, "user_ids": touched_user_ids, "requested_user_ids": user_ids},
        ip=get_request_ip(request),
    )
    await db.commit()
    hospital = (
        await db.execute(select(Hospital).where(Hospital.id == row.hospital_id, Hospital.tenant_id == tenant_id))
    ).scalars().first()
    return ApiResponse(code=200, message="success", data=_to_item(row, hospital.name if hospital else None))


@router.delete("/{department_id}", response_model=ApiResponse)
async def toggle_department(
    department_id: int,
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    tenant_id = ensure_tenant_bound(current_user)
    row = (
        await db.execute(select(Department).where(Department.id == department_id, Department.tenant_id == tenant_id))
    ).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="科室不存在")
    row.is_active = not row.is_active
    await db.commit()
    await db.refresh(row)
    hospital = (
        await db.execute(select(Hospital).where(Hospital.id == row.hospital_id, Hospital.tenant_id == tenant_id))
    ).scalars().first()
    return ApiResponse(code=200, message="success", data=_to_item(row, hospital.name if hospital else None))
