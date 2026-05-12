from __future__ import annotations

import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import ensure_tenant_bound, get_accessible_department_ids, get_accessible_hospital_ids, require_admin
from app.models import Department, Hospital, ImportTask, User
from app.services.rbac import enforce_rbac
from app.schemas.import_task import (
    ApiResponse,
    ImportTaskCreateRequest,
    ImportTaskFinishRequest,
    ImportTaskItem,
    ImportTaskPageData,
)

router = APIRouter()


def _to_csv_response(filename: str, rows: list[list[str]]) -> StreamingResponse:
    output = io.StringIO()
    writer = csv.writer(output)
    for row in rows:
        writer.writerow(row)
    content = output.getvalue()
    output.close()
    return StreamingResponse(
        iter([content.encode("utf-8-sig")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def _accessible_scope(
    current_user: User,
    db: AsyncSession,
) -> tuple[list[int], list[int]]:
    if current_user.role == "super_admin" or current_user.is_all_hospitals:
        return [], []
    hospital_ids = await get_accessible_hospital_ids(current_user, db)
    department_ids = await get_accessible_department_ids(current_user, db)
    return hospital_ids, department_ids


async def _ensure_scope_access(
    current_user: User,
    db: AsyncSession,
    *,
    scope: str,
    hospital_id: int | None,
    department_id: int | None,
) -> None:
    if scope == "common":
        if current_user.role != "super_admin":
            raise HTTPException(status_code=403, detail="仅超级管理员可创建通用案例库导入任务")
        return
    if current_user.role == "super_admin" or current_user.is_all_hospitals:
        return
    hospital_ids, department_ids = await _accessible_scope(current_user, db)
    if scope == "hospital":
        if not hospital_id or hospital_id not in hospital_ids:
            raise HTTPException(status_code=403, detail="无权操作该医院导入任务")
    if scope == "department":
        if not department_id or department_id not in department_ids:
            raise HTTPException(status_code=403, detail="无权操作该科室导入任务")


def _to_import_task_item(
    task: ImportTask,
    operator_map: dict[int, str],
    hospital_map: dict[int, str],
    department_map: dict[int, str],
) -> ImportTaskItem:
    return ImportTaskItem(
        id=int(task.id),
        operator_id=task.operator_id,
        operator_name=operator_map.get(task.operator_id),
        scope=task.scope,  # type: ignore[arg-type]
        hospital_id=task.hospital_id,
        hospital_name=hospital_map.get(task.hospital_id or 0),
        department_id=task.department_id,
        department_name=department_map.get(task.department_id or 0),
        total=task.total,
        success=task.success,
        duplicate=task.duplicate,
        failed=task.failed,
        updated=task.updated,
        status=task.status,  # type: ignore[arg-type]
        detail=task.detail,
        started_at=task.started_at,
        finished_at=task.finished_at,
        created_at=task.created_at,
    )


async def _preload_name_maps(
    db: AsyncSession, tasks: list[ImportTask]
) -> tuple[dict[int, str], dict[int, str], dict[int, str]]:
    op_ids = sorted({t.operator_id for t in tasks if t.operator_id})
    h_ids = sorted({t.hospital_id for t in tasks if t.hospital_id})
    d_ids = sorted({t.department_id for t in tasks if t.department_id})
    operator_map: dict[int, str] = {}
    hospital_map: dict[int, str] = {}
    department_map: dict[int, str] = {}
    if op_ids:
        rows = (await db.execute(select(User.id, User.real_name).where(User.id.in_(op_ids)))).all()
        operator_map = {int(r[0]): str(r[1]) for r in rows}
    if h_ids:
        rows = (await db.execute(select(Hospital.id, Hospital.name).where(Hospital.id.in_(h_ids)))).all()
        hospital_map = {int(r[0]): str(r[1]) for r in rows}
    if d_ids:
        rows = (await db.execute(select(Department.id, Department.name).where(Department.id.in_(d_ids)))).all()
        department_map = {int(r[0]): str(r[1]) for r in rows}
    return operator_map, hospital_map, department_map


async def _build_item(task: ImportTask, db: AsyncSession) -> ImportTaskItem:
    op_map, h_map, d_map = await _preload_name_maps(db, [task])
    return _to_import_task_item(task, op_map, h_map, d_map)


@router.post("", response_model=ApiResponse)
async def create_import_task(
    request: Request,
    payload: ImportTaskCreateRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="import_task:create",
        required_roles={"admin", "super_admin"},
        request=request,
        target_tenant_id=(int(current_user.tenant_id) if current_user.tenant_id else None),
        target_hospital_id=payload.hospital_id,
        target_department_id=payload.department_id,
        target_type="import_task",
    )
    tenant_id = ensure_tenant_bound(current_user)
    await _ensure_scope_access(
        current_user,
        db,
        scope=payload.scope,
        hospital_id=payload.hospital_id,
        department_id=payload.department_id,
    )
    task = ImportTask(
        tenant_id=tenant_id,
        operator_id=current_user.id,
        scope=payload.scope,
        hospital_id=payload.hospital_id,
        department_id=payload.department_id,
        total=payload.total,
        success=0,
        duplicate=0,
        failed=0,
        updated=0,
        status="running",
        detail=payload.detail,
        started_at=datetime.now(),
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    item = await _build_item(task, db)
    return ApiResponse(code=200, message="success", data=item)


@router.put("/{task_id}/finish", response_model=ApiResponse)
async def finish_import_task(
    task_id: int,
    payload: ImportTaskFinishRequest,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    tenant_id = ensure_tenant_bound(current_user)
    task = (
        await db.execute(select(ImportTask).where(ImportTask.id == task_id, ImportTask.tenant_id == tenant_id))
    ).scalars().first()
    if not task:
        raise HTTPException(status_code=404, detail="导入任务不存在")
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="import_task:finish",
        required_roles={"admin", "super_admin"},
        request=request,
        target_tenant_id=tenant_id,
        target_hospital_id=task.hospital_id,
        target_department_id=task.department_id,
        target_type="import_task",
        target_id=task_id,
    )
    await _ensure_scope_access(
        current_user,
        db,
        scope=task.scope,
        hospital_id=task.hospital_id,
        department_id=task.department_id,
    )
    if current_user.role != "super_admin" and task.operator_id != current_user.id:
        raise HTTPException(status_code=403, detail="仅可完成自己创建的导入任务")
    task.success = payload.success
    task.duplicate = payload.duplicate
    task.failed = payload.failed
    task.updated = payload.updated
    task.detail = payload.detail
    task.status = "partial_fail" if payload.failed > 0 else "completed"
    task.finished_at = datetime.now()
    await db.commit()
    await db.refresh(task)
    item = await _build_item(task, db)
    return ApiResponse(code=200, message="success", data=item)


@router.get("", response_model=ApiResponse)
async def list_import_tasks(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    scope: str | None = Query(default=None, pattern="^(common|hospital|department)$"),
    status: str | None = Query(default=None, pattern="^(running|completed|partial_fail)$"),
    operator_id: int | None = Query(default=None),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="import_task:list",
        required_roles={"admin", "super_admin"},
        request=request,
        target_tenant_id=(int(current_user.tenant_id) if current_user.tenant_id else None),
        target_type="import_task",
        extra_detail={"scope": scope, "status": status, "operator_id": operator_id},
    )
    tenant_id = ensure_tenant_bound(current_user)
    filters = []
    filters.append(ImportTask.tenant_id == tenant_id)
    if scope:
        filters.append(ImportTask.scope == scope)
    if status:
        filters.append(ImportTask.status == status)
    if operator_id:
        filters.append(ImportTask.operator_id == operator_id)

    if current_user.role != "super_admin" and not current_user.is_all_hospitals:
        hospital_ids, department_ids = await _accessible_scope(current_user, db)
        filters.append(
            (ImportTask.scope == "common")
            | (ImportTask.hospital_id.in_(hospital_ids))
            | (ImportTask.department_id.in_(department_ids))
        )

    total = int((await db.execute(select(func.count(ImportTask.id)).where(*filters))).scalar_one())
    rows = (
        await db.execute(
            select(ImportTask)
            .where(*filters)
            .order_by(ImportTask.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    op_map, h_map, d_map = await _preload_name_maps(db, list(rows))
    items = [_to_import_task_item(row, op_map, h_map, d_map) for row in rows]
    return ApiResponse(
        code=200,
        message="success",
        data=ImportTaskPageData(items=items, total=total, page=page, page_size=page_size),
    )


@router.get("/{task_id}", response_model=ApiResponse)
async def get_import_task(
    task_id: int,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    tenant_id = ensure_tenant_bound(current_user)
    task = (
        await db.execute(select(ImportTask).where(ImportTask.id == task_id, ImportTask.tenant_id == tenant_id))
    ).scalars().first()
    if not task:
        raise HTTPException(status_code=404, detail="导入任务不存在")
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="import_task:read",
        required_roles={"admin", "super_admin"},
        request=request,
        target_tenant_id=tenant_id,
        target_hospital_id=task.hospital_id,
        target_department_id=task.department_id,
        target_type="import_task",
        target_id=task_id,
    )
    await _ensure_scope_access(
        current_user,
        db,
        scope=task.scope,
        hospital_id=task.hospital_id,
        department_id=task.department_id,
    )
    item = await _build_item(task, db)
    return ApiResponse(code=200, message="success", data=item)


@router.get("/{task_id}/export")
async def export_import_task_failures(
    task_id: int,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    tenant_id = ensure_tenant_bound(current_user)
    task = (
        await db.execute(select(ImportTask).where(ImportTask.id == task_id, ImportTask.tenant_id == tenant_id))
    ).scalars().first()
    if not task:
        raise HTTPException(status_code=404, detail="导入任务不存在")
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="import_task:export_failures",
        required_roles={"admin", "super_admin"},
        request=request,
        target_tenant_id=tenant_id,
        target_hospital_id=task.hospital_id,
        target_department_id=task.department_id,
        target_type="import_task",
        target_id=task_id,
    )
    await _ensure_scope_access(
        current_user,
        db,
        scope=task.scope,
        hospital_id=task.hospital_id,
        department_id=task.department_id,
    )
    detail = task.detail or {}
    failed_items = detail.get("failed_items") if isinstance(detail, dict) else None
    rows: list[list[str]] = [["文件名", "标题", "聊天类型", "消息数", "状态", "说明"]]
    if isinstance(failed_items, list):
        for item in failed_items:
            if not isinstance(item, dict):
                continue
            rows.append(
                [
                    str(item.get("file_name") or ""),
                    str(item.get("title") or ""),
                    str(item.get("chat_type") or ""),
                    str(item.get("message_count") or 0),
                    str(item.get("status") or ""),
                    str(item.get("result_text") or ""),
                ]
            )
    filename = f"import-task-{task.id}-failed-items.csv"
    return _to_csv_response(filename, rows)
