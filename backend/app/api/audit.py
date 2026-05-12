from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import ensure_tenant_bound, require_module, require_super_admin
from app.models import AuditLog, Department, Hospital, SystemSetting, User
from app.services.rbac import enforce_rbac
from app.schemas.audit import ApiResponse, AuditLogItem, AuditLogListData

router = APIRouter()


async def _ensure_audit_enabled(db: AsyncSession, tenant_id: int) -> None:
    settings = (
        await db.execute(
            select(SystemSetting)
            .where(SystemSetting.tenant_id == tenant_id)
            .order_by(SystemSetting.id.asc())
            .limit(1)
        )
    ).scalars().first()
    if settings and not settings.enable_audit_enhanced:
        raise HTTPException(status_code=403, detail="增强审计能力已被系统管理员关闭")


@router.get("", response_model=ApiResponse)
async def list_audit_logs(
    request: Request,
    _: User = Depends(require_module("mod_audit")),
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    action: str | None = None,
    user_id: int | None = None,
    hospital_id: int | None = None,
    department_id: int | None = None,
    keyword: str | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> ApiResponse:
    tenant_id = ensure_tenant_bound(current_user)
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="audit:list",
        required_roles={"super_admin"},
        request=request,
        target_tenant_id=tenant_id,
        target_type="audit_log",
        extra_detail={"action": action, "user_id": user_id, "hospital_id": hospital_id, "department_id": department_id},
    )
    await _ensure_audit_enabled(db, tenant_id)
    filters = [AuditLog.tenant_id == tenant_id]
    if action:
        filters.append(AuditLog.action == action)
    if user_id:
        filters.append(AuditLog.user_id == user_id)
    if hospital_id:
        filters.append(AuditLog.hospital_id == hospital_id)
    if department_id:
        filters.append(AuditLog.department_id == department_id)
    if start_at:
        filters.append(AuditLog.created_at >= start_at)
    if end_at:
        filters.append(AuditLog.created_at <= end_at)
    if keyword:
        kw = f"%{keyword.strip()}%"
        filters.append(or_(User.username.like(kw), User.real_name.like(kw)))

    count_stmt = (
        select(func.count(AuditLog.id))
        .select_from(AuditLog)
        .outerjoin(User, User.id == AuditLog.user_id)
        .where(*filters)
    )
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = (
        select(AuditLog, User.username, User.real_name, Hospital.name, Department.name)
        .outerjoin(User, User.id == AuditLog.user_id)
        .outerjoin(Hospital, Hospital.id == AuditLog.hospital_id)
        .outerjoin(Department, Department.id == AuditLog.department_id)
        .where(*filters)
        .order_by(AuditLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.execute(stmt)).all()
    items = [
        AuditLogItem(
            id=log.id,
            user_id=log.user_id,
            username=username,
            real_name=real_name,
            action=log.action,
            target_type=log.target_type,
            target_id=log.target_id,
            hospital_id=log.hospital_id,
            department_id=log.department_id,
            hospital_name=hospital_name,
            department_name=department_name,
            detail=log.detail,
            ip=log.ip,
            created_at=log.created_at,
        )
        for log, username, real_name, hospital_name, department_name in rows
    ]
    return ApiResponse(
        code=200,
        message="success",
        data=AuditLogListData(items=items, total=total, page=page, page_size=page_size),
    )


@router.delete("/{log_id}")
async def delete_audit_log(
    log_id: int,
    request: Request,
    _: User = Depends(require_module("mod_audit")),
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id = ensure_tenant_bound(current_user)
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="audit:delete",
        required_roles={"super_admin"},
        request=request,
        target_tenant_id=tenant_id,
        target_type="audit_log",
        target_id=log_id,
    )
    await _ensure_audit_enabled(db, tenant_id)
    row = (
        await db.execute(
            select(AuditLog).where(AuditLog.id == log_id, AuditLog.tenant_id == tenant_id)
        )
    ).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="日志不存在")
    await db.delete(row)
    await db.commit()
    return {"code": 200, "message": "删除成功", "data": {"deleted": 1}}


@router.post("/batch-delete")
async def batch_delete_audit_logs(
    payload: dict,
    request: Request,
    _: User = Depends(require_module("mod_audit")),
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id = ensure_tenant_bound(current_user)
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="audit:batch_delete",
        required_roles={"super_admin"},
        request=request,
        target_tenant_id=tenant_id,
        target_type="audit_log",
    )
    await _ensure_audit_enabled(db, tenant_id)
    ids_raw = payload.get("ids")
    if not isinstance(ids_raw, list):
        raise HTTPException(status_code=400, detail="ids 必须为数组")
    ids = sorted({int(v) for v in ids_raw if str(v).strip().isdigit()})
    if not ids:
        raise HTTPException(status_code=400, detail="请至少选择一条日志")
    result = await db.execute(
        delete(AuditLog).where(AuditLog.tenant_id == tenant_id, AuditLog.id.in_(ids))
    )
    await db.commit()
    return {"code": 200, "message": "批量删除成功", "data": {"deleted": int(result.rowcount or 0)}}


@router.post("/clear")
async def clear_audit_logs(
    request: Request,
    _: User = Depends(require_module("mod_audit")),
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id = ensure_tenant_bound(current_user)
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="audit:clear",
        required_roles={"super_admin"},
        request=request,
        target_tenant_id=tenant_id,
        target_type="audit_log",
    )
    await _ensure_audit_enabled(db, tenant_id)
    count_before = (
        await db.execute(select(func.count(AuditLog.id)).where(AuditLog.tenant_id == tenant_id))
    ).scalar_one()
    await db.execute(delete(AuditLog).where(AuditLog.tenant_id == tenant_id))
    await db.commit()
    return {"code": 200, "message": f"已清空 {count_before} 条审计日志", "data": {"deleted": int(count_before)}}
