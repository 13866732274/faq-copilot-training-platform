from __future__ import annotations

import csv
import io
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import (
    ensure_tenant_bound,
    get_accessible_department_ids,
    get_accessible_hospital_ids,
    get_current_user,
    require_admin,
    require_module,
    require_super_admin,
)
from app.models import AuditLog, Department, Hospital, Practice, Quiz, SystemSetting, Tenant, User
from app.schemas.system import (
    ApiResponse,
    PublicSystemSettingsItem,
    SystemSettingsItem,
    SystemSettingsUpdateRequest,
)
from app.services.audit import append_audit_log, get_request_ip
from app.services.rbac import enforce_rbac

router = APIRouter()

HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
RGB_COLOR_RE = re.compile(
    r"^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})(?:\s*,\s*(0|1|0?\.\d+))?\s*\)$",
    re.IGNORECASE,
)


def _normalize_brand_accent(raw: str) -> str:
    color = (raw or "").strip()
    if HEX_COLOR_RE.match(color):
        if len(color) == 4:
            # #RGB -> #RRGGBB
            r, g, b = color[1], color[2], color[3]
            return f"#{r}{r}{g}{g}{b}{b}".lower()
        return color.lower()
    rgb_match = RGB_COLOR_RE.match(color)
    if rgb_match:
        channels = [int(rgb_match.group(i)) for i in (1, 2, 3)]
        if any(ch < 0 or ch > 255 for ch in channels):
            raise HTTPException(status_code=400, detail="品牌主色 RGB 取值必须在 0~255")
        return "#{:02x}{:02x}{:02x}".format(*channels)
    raise HTTPException(status_code=400, detail="品牌主色格式不正确，请使用 #RGB/#RRGGBB 或 rgb()/rgba()")


async def _get_or_create_settings(db: AsyncSession, tenant_id: int) -> SystemSetting:
    row = (
        await db.execute(
            select(SystemSetting).where(SystemSetting.tenant_id == tenant_id).order_by(SystemSetting.id.asc()).limit(1)
        )
    ).scalars().first()
    if row:
        return row
    row = SystemSetting(tenant_id=tenant_id)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


def _to_item(row: SystemSetting) -> SystemSettingsItem:
    return SystemSettingsItem(
        site_name=row.site_name,
        site_subtitle=row.site_subtitle,
        logo_url=row.logo_url,
        brand_accent=row.brand_accent,
        enable_ai_scoring=row.enable_ai_scoring,
        enable_export_center=row.enable_export_center,
        enable_audit_enhanced=row.enable_audit_enhanced,
        admin_menu_template_lock=row.admin_menu_template_lock,
        faq_task_timeout_minutes=row.faq_task_timeout_minutes,
        updated_at=row.updated_at,
    )


def _to_public_item(row: SystemSetting) -> PublicSystemSettingsItem:
    return PublicSystemSettingsItem(
        site_name=row.site_name,
        site_subtitle=row.site_subtitle,
        logo_url=row.logo_url,
        brand_accent=row.brand_accent,
    )


def _csv_response(filename: str, rows: list[list[str]]) -> StreamingResponse:
    output = io.StringIO()
    writer = csv.writer(output)
    for row in rows:
        writer.writerow(row)
    data = output.getvalue()
    output.close()
    return StreamingResponse(
        iter([data.encode("utf-8-sig")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def _ensure_export_enabled(db: AsyncSession, tenant_id: int) -> None:
    settings = await _get_or_create_settings(db, tenant_id)
    if not settings.enable_export_center:
        raise HTTPException(status_code=403, detail="导出中心已被系统管理员关闭")


async def _resolve_scope_filters(
    *,
    current_user: User,
    db: AsyncSession,
    hospital_id: int | None,
    department_id: int | None,
) -> tuple[list[int], list[int], int | None, int | None]:
    if current_user.role == "super_admin" or current_user.is_all_hospitals:
        return [], [], hospital_id, department_id

    accessible_hospital_ids = await get_accessible_hospital_ids(current_user, db)
    accessible_department_ids = await get_accessible_department_ids(current_user, db)
    if hospital_id and hospital_id not in accessible_hospital_ids:
        raise HTTPException(status_code=403, detail="无权导出该医院数据")
    if department_id and department_id not in accessible_department_ids:
        raise HTTPException(status_code=403, detail="无权导出该科室数据")
    return accessible_hospital_ids, accessible_department_ids, hospital_id, department_id


def _date_range_filter(stmt: Select, column, start_date: str | None, end_date: str | None) -> Select:
    if start_date:
        stmt = stmt.where(func.date(column) >= start_date)
    if end_date:
        stmt = stmt.where(func.date(column) <= end_date)
    return stmt


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


@router.get("/settings/public", response_model=ApiResponse)
async def get_public_settings(db: AsyncSession = Depends(get_db)) -> ApiResponse:
    row = await _get_or_create_settings(db, 1)
    item = _to_public_item(row)

    active_tenants = (
        await db.execute(
            select(Tenant.id, Tenant.code).where(Tenant.is_active.is_(True)).order_by(Tenant.id.asc()).limit(3)
        )
    ).all()
    if len(active_tenants) == 1:
        item.default_tenant_code = str(active_tenants[0][1])
        item.show_tenant_input = False
    elif len(active_tenants) > 1:
        item.show_tenant_input = True
    return ApiResponse(code=200, message="success", data=item)


@router.get("/settings", response_model=ApiResponse)
async def get_settings(
    request: Request,
    tenant_id: int | None = Query(default=None, description="仅 super_admin 可指定目标租户"),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    target_tenant_id = ensure_tenant_bound(current_user)
    if tenant_id is not None:
        if current_user.role != "super_admin":
            raise HTTPException(status_code=403, detail="仅超级管理员可切换目标租户设置")
        target_tenant_id = int(tenant_id)
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="system:settings:read",
        required_roles={"admin", "super_admin"},
        request=request,
        target_tenant_id=target_tenant_id,
        target_type="system",
    )
    row = await _get_or_create_settings(db, target_tenant_id)
    return ApiResponse(code=200, message="success", data=_to_item(row))


@router.put("/settings", response_model=ApiResponse)
async def update_settings(
    payload: SystemSettingsUpdateRequest,
    request: Request,
    tenant_id: int | None = Query(default=None, description="仅 super_admin 可指定目标租户"),
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    normalized_brand_accent = _normalize_brand_accent(payload.brand_accent)

    target_tenant_id = ensure_tenant_bound(current_user)
    if tenant_id is not None:
        target_tenant_id = int(tenant_id)
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="system:settings:update",
        required_roles={"super_admin"},
        request=request,
        target_tenant_id=target_tenant_id,
        target_type="system",
    )
    row = await _get_or_create_settings(db, target_tenant_id)
    before = _to_item(row).model_dump(mode="json")
    row.site_name = payload.site_name.strip()
    row.site_subtitle = payload.site_subtitle.strip()
    row.logo_url = payload.logo_url.strip() if payload.logo_url else None
    row.brand_accent = normalized_brand_accent
    row.enable_ai_scoring = payload.enable_ai_scoring
    row.enable_export_center = payload.enable_export_center
    row.enable_audit_enhanced = payload.enable_audit_enhanced
    row.admin_menu_template_lock = payload.admin_menu_template_lock
    row.faq_task_timeout_minutes = payload.faq_task_timeout_minutes
    row.updated_by = current_user.id

    await append_audit_log(
        db,
        action="system_settings_update",
        user_id=current_user.id,
        target_type="system",
        target_id=row.id,
        tenant_id=target_tenant_id,
        detail={"before": before, "after": _to_item(row).model_dump(mode="json")},
        ip=get_request_ip(request),
    )
    await db.commit()
    await db.refresh(row)
    return ApiResponse(code=200, message="success", data=_to_item(row))


@router.post("/permission-policy-events")
async def append_permission_policy_event(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Persist permission policy loading events (for diagnostics)."""
    tenant_id = ensure_tenant_bound(current_user)
    stage = str(payload.get("stage") or "").strip()
    if stage not in {"success", "retry", "failed"}:
        raise HTTPException(status_code=400, detail="stage 非法")
    event_detail = {
        "at": str(payload.get("at") or ""),
        "stage": stage,
        "attempt": _safe_int(payload.get("attempt"), 0),
        "duration_ms": _safe_int(payload.get("duration_ms"), 0),
        "error": (str(payload.get("error") or "")[:2000] or None),
    }
    row = AuditLog(
        tenant_id=tenant_id,
        user_id=current_user.id,
        action="permission_policy_event",
        target_type="permission_policy",
        target_id=None,
        hospital_id=current_user.hospital_id,
        department_id=current_user.department_id,
        detail=event_detail,
        ip=None,
    )
    db.add(row)
    await db.commit()
    return {"code": 200, "message": "success", "data": {"id": row.id}}


@router.get("/permission-policy-events")
async def list_permission_policy_events(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = ensure_tenant_bound(current_user)
    filters = [AuditLog.tenant_id == tenant_id, AuditLog.action == "permission_policy_event"]
    total = (await db.execute(select(func.count(AuditLog.id)).where(*filters))).scalar() or 0
    rows = (
        await db.execute(
            select(AuditLog)
            .where(*filters)
            .order_by(AuditLog.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    items = []
    for row in rows:
        detail = row.detail if isinstance(row.detail, dict) else {}
        items.append({
            "id": row.id,
            "at": (detail.get("at") or (row.created_at.isoformat() if row.created_at else "")),
            "stage": str(detail.get("stage") or "failed"),
            "attempt": _safe_int(detail.get("attempt"), 0),
            "duration_ms": _safe_int(detail.get("duration_ms"), 0),
            "error": str(detail.get("error") or ""),
            "created_at": row.created_at.isoformat() if row.created_at else None,
        })
    return {"code": 200, "message": "success", "data": {"items": items, "total": int(total)}}


@router.delete("/permission-policy-events/{event_id}")
async def delete_permission_policy_event(
    event_id: int,
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = ensure_tenant_bound(current_user)
    row = (
        await db.execute(
            select(AuditLog).where(
                AuditLog.id == event_id,
                AuditLog.tenant_id == tenant_id,
                AuditLog.action == "permission_policy_event",
            )
        )
    ).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="日志不存在")
    await db.delete(row)
    await db.commit()
    return {"code": 200, "message": "删除成功"}


@router.post("/permission-policy-events/batch-delete")
async def batch_delete_permission_policy_events(
    payload: dict,
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = ensure_tenant_bound(current_user)
    ids_raw = payload.get("ids")
    if not isinstance(ids_raw, list):
        raise HTTPException(status_code=400, detail="ids 必须为数组")
    ids = sorted({int(v) for v in ids_raw if str(v).strip().isdigit()})
    if not ids:
        raise HTTPException(status_code=400, detail="请至少选择一条日志")
    result = await db.execute(
        delete(AuditLog).where(
            AuditLog.tenant_id == tenant_id,
            AuditLog.action == "permission_policy_event",
            AuditLog.id.in_(ids),
        )
    )
    await db.commit()
    return {"code": 200, "message": "批量删除成功", "data": {"deleted": int(result.rowcount or 0)}}


@router.post("/permission-policy-events/clear")
async def clear_permission_policy_events(
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = ensure_tenant_bound(current_user)
    count_before = (
        await db.execute(
            select(func.count(AuditLog.id)).where(
                AuditLog.tenant_id == tenant_id,
                AuditLog.action == "permission_policy_event",
            )
        )
    ).scalar() or 0
    await db.execute(
        delete(AuditLog).where(
            AuditLog.tenant_id == tenant_id,
            AuditLog.action == "permission_policy_event",
        )
    )
    await db.commit()
    return {"code": 200, "message": "已清空诊断日志", "data": {"deleted": int(count_before)}}


@router.get("/exports/users")
async def export_users_csv(
    request: Request,
    hospital_id: int | None = Query(default=None),
    department_id: int | None = Query(default=None),
    role: str | None = Query(default=None),
    start_date: str | None = Query(default=None, description="YYYY-MM-DD"),
    end_date: str | None = Query(default=None, description="YYYY-MM-DD"),
    _: User = Depends(require_module("mod_export")),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="system:export:users",
        required_roles={"admin", "super_admin"},
        request=request,
        target_tenant_id=(int(current_user.tenant_id) if current_user.tenant_id else None),
        target_hospital_id=hospital_id,
        target_department_id=department_id,
        target_type="export",
    )
    tenant_id = ensure_tenant_bound(current_user)
    await _ensure_export_enabled(db, tenant_id)
    accessible_hospital_ids, accessible_department_ids, scoped_hospital_id, scoped_department_id = await _resolve_scope_filters(
        current_user=current_user,
        db=db,
        hospital_id=hospital_id,
        department_id=department_id,
    )
    stmt = (
        select(
            User.id,
            User.username,
            User.real_name,
            User.role,
            User.is_active,
            User.created_at,
            Hospital.name.label("hospital_name"),
            Department.name.label("department_name"),
        )
        .outerjoin(Hospital, Hospital.id == User.hospital_id)
        .outerjoin(Department, Department.id == User.department_id)
        .where(User.tenant_id == tenant_id)
    )
    if role:
        stmt = stmt.where(User.role == role)
    if scoped_hospital_id:
        stmt = stmt.where(User.hospital_id == scoped_hospital_id)
    elif accessible_hospital_ids:
        stmt = stmt.where(User.hospital_id.in_(accessible_hospital_ids))
    if scoped_department_id:
        stmt = stmt.where(User.department_id == scoped_department_id)
    elif accessible_department_ids:
        stmt = stmt.where(User.department_id.in_(accessible_department_ids))
    stmt = _date_range_filter(stmt, User.created_at, start_date, end_date).order_by(User.id.desc()).limit(50000)
    rows = (await db.execute(stmt)).mappings().all()
    csv_rows: list[list[str]] = [
        ["用户ID", "用户名", "姓名", "角色", "状态", "医院", "科室", "创建时间"],
    ]
    for row in rows:
        csv_rows.append(
            [
                str(row["id"]),
                str(row["username"] or ""),
                str(row["real_name"] or ""),
                str(row["role"] or ""),
                "启用" if bool(row["is_active"]) else "禁用",
                str(row["hospital_name"] or ""),
                str(row["department_name"] or ""),
                row["created_at"].strftime("%Y-%m-%d %H:%M:%S") if row["created_at"] else "",
            ]
        )
    return _csv_response("users-export.csv", csv_rows)


@router.get("/exports/practices")
async def export_practices_csv(
    request: Request,
    hospital_id: int | None = Query(default=None),
    department_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    start_date: str | None = Query(default=None, description="YYYY-MM-DD"),
    end_date: str | None = Query(default=None, description="YYYY-MM-DD"),
    _: User = Depends(require_module("mod_export")),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="system:export:practices",
        required_roles={"admin", "super_admin"},
        request=request,
        target_tenant_id=(int(current_user.tenant_id) if current_user.tenant_id else None),
        target_hospital_id=hospital_id,
        target_department_id=department_id,
        target_type="export",
    )
    tenant_id = ensure_tenant_bound(current_user)
    await _ensure_export_enabled(db, tenant_id)
    accessible_hospital_ids, accessible_department_ids, scoped_hospital_id, scoped_department_id = await _resolve_scope_filters(
        current_user=current_user,
        db=db,
        hospital_id=hospital_id,
        department_id=department_id,
    )
    stmt = (
        select(
            Practice.id,
            Practice.status,
            Practice.current_step,
            Practice.started_at,
            Practice.completed_at,
            Practice.created_at,
            User.username,
            User.real_name,
            Quiz.title.label("quiz_title"),
            Hospital.name.label("hospital_name"),
            Department.name.label("department_name"),
        )
        .join(User, User.id == Practice.user_id)
        .join(Quiz, Quiz.id == Practice.quiz_id)
        .outerjoin(Hospital, Hospital.id == Practice.hospital_id)
        .outerjoin(Department, Department.id == Practice.department_id)
        .where(Practice.tenant_id == tenant_id, User.tenant_id == tenant_id, Quiz.tenant_id == tenant_id)
    )
    if status:
        stmt = stmt.where(Practice.status == status)
    if scoped_hospital_id:
        stmt = stmt.where(Practice.hospital_id == scoped_hospital_id)
    elif accessible_hospital_ids:
        stmt = stmt.where(Practice.hospital_id.in_(accessible_hospital_ids))
    if scoped_department_id:
        stmt = stmt.where(Practice.department_id == scoped_department_id)
    elif accessible_department_ids:
        stmt = stmt.where(Practice.department_id.in_(accessible_department_ids))
    stmt = _date_range_filter(stmt, Practice.created_at, start_date, end_date).order_by(Practice.id.desc()).limit(50000)
    rows = (await db.execute(stmt)).mappings().all()
    csv_rows: list[list[str]] = [
        ["训练ID", "案例标题", "咨询员账号", "咨询员姓名", "状态", "进度步数", "医院", "科室", "开始时间", "完成时间", "创建时间"],
    ]
    for row in rows:
        csv_rows.append(
            [
                str(row["id"]),
                str(row["quiz_title"] or ""),
                str(row["username"] or ""),
                str(row["real_name"] or ""),
                str(row["status"] or ""),
                str(row["current_step"] or 0),
                str(row["hospital_name"] or ""),
                str(row["department_name"] or ""),
                row["started_at"].strftime("%Y-%m-%d %H:%M:%S") if row["started_at"] else "",
                row["completed_at"].strftime("%Y-%m-%d %H:%M:%S") if row["completed_at"] else "",
                row["created_at"].strftime("%Y-%m-%d %H:%M:%S") if row["created_at"] else "",
            ]
        )
    return _csv_response("practices-export.csv", csv_rows)


@router.get("/exports/quizzes")
async def export_quizzes_csv(
    request: Request,
    hospital_id: int | None = Query(default=None),
    department_id: int | None = Query(default=None),
    scope: str | None = Query(default=None),
    start_date: str | None = Query(default=None, description="YYYY-MM-DD"),
    end_date: str | None = Query(default=None, description="YYYY-MM-DD"),
    _: User = Depends(require_module("mod_export")),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="system:export:quizzes",
        required_roles={"admin", "super_admin"},
        request=request,
        target_tenant_id=(int(current_user.tenant_id) if current_user.tenant_id else None),
        target_hospital_id=hospital_id,
        target_department_id=department_id,
        target_type="export",
        extra_detail={"scope": scope},
    )
    tenant_id = ensure_tenant_bound(current_user)
    await _ensure_export_enabled(db, tenant_id)
    accessible_hospital_ids, accessible_department_ids, scoped_hospital_id, scoped_department_id = await _resolve_scope_filters(
        current_user=current_user,
        db=db,
        hospital_id=hospital_id,
        department_id=department_id,
    )
    stmt = (
        select(
            Quiz.id,
            Quiz.title,
            Quiz.scope,
            Quiz.category,
            Quiz.chat_type,
            Quiz.difficulty,
            Quiz.message_count,
            Quiz.is_active,
            Quiz.created_at,
            Hospital.name.label("hospital_name"),
            Department.name.label("department_name"),
        )
        .outerjoin(Hospital, Hospital.id == Quiz.hospital_id)
        .outerjoin(Department, Department.id == Quiz.department_id)
        .where(Quiz.is_deleted.is_(False), Quiz.tenant_id == tenant_id)
    )
    if scope:
        stmt = stmt.where(Quiz.scope == scope)
    if scoped_hospital_id:
        stmt = stmt.where((Quiz.scope == "common") | (Quiz.hospital_id == scoped_hospital_id))
    elif accessible_hospital_ids:
        stmt = stmt.where((Quiz.scope == "common") | (Quiz.hospital_id.in_(accessible_hospital_ids)))
    if scoped_department_id:
        stmt = stmt.where((Quiz.scope == "common") | (Quiz.department_id == scoped_department_id))
    elif accessible_department_ids:
        stmt = stmt.where((Quiz.scope == "common") | (Quiz.department_id.in_(accessible_department_ids)))
    stmt = _date_range_filter(stmt, Quiz.created_at, start_date, end_date).order_by(Quiz.id.desc()).limit(50000)
    rows = (await db.execute(stmt)).mappings().all()
    csv_rows: list[list[str]] = [
        ["案例ID", "标题", "范围", "分类", "聊天类型", "难度", "消息数", "状态", "医院", "科室", "创建时间"],
    ]
    for row in rows:
        csv_rows.append(
            [
                str(row["id"]),
                str(row["title"] or ""),
                str(row["scope"] or ""),
                str(row["category"] or ""),
                str(row["chat_type"] or ""),
                str(row["difficulty"] or 0),
                str(row["message_count"] or 0),
                "启用" if bool(row["is_active"]) else "停用",
                str(row["hospital_name"] or ""),
                str(row["department_name"] or ""),
                row["created_at"].strftime("%Y-%m-%d %H:%M:%S") if row["created_at"] else "",
            ]
        )
    return _csv_response("quizzes-export.csv", csv_rows)
