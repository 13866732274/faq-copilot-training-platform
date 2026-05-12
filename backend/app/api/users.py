from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import (
    get_accessible_department_ids,
    get_accessible_hospital_ids,
    is_platform_super_admin,
    require_admin,
    require_super_admin,
)
from app.models import Department, Hospital, Tenant, User, UserDepartment, UserHospital
from app.schemas.user import (
    ApiResponse,
    BulkUserMenuPermissionsData,
    BulkUserMenuPermissionsRequest,
    BulkUserStatusData,
    BulkUserStatusRequest,
    BulkUserImportData,
    BulkUserImportRequest,
    UserCreateRequest,
    UserItem,
    UserListData,
    UserUpdateRequest,
)
from app.utils.security import hash_password
from app.services.audit import append_audit_log, build_user_snapshot, get_request_ip
from app.services.rbac import enforce_rbac

router = APIRouter()

VALID_ROLES = {"super_admin", "admin", "student"}
VALID_MENU_KEYS = {
    "quiz-import",
    "quiz-list",
    "user-manage",
    "hospital-manage",
    "department-manage",
    "stats",
}


def _parse_menu_permissions(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(value, list):
        return None
    deduped = sorted({str(item) for item in value if isinstance(item, str) and item in VALID_MENU_KEYS})
    if not deduped:
        return None
    if len(deduped) == len(VALID_MENU_KEYS):
        return None
    return deduped


def _serialize_menu_permissions(menu_permissions: list[str] | None) -> str | None:
    if menu_permissions is None:
        return None
    deduped = sorted({str(item) for item in menu_permissions if isinstance(item, str) and item in VALID_MENU_KEYS})
    if not deduped:
        return None
    if len(deduped) == len(VALID_MENU_KEYS):
        return None
    return json.dumps(deduped, ensure_ascii=False)


async def _load_hospital_name_map(db: AsyncSession, rows: list[User], tenant_id: int | None = None) -> dict[int, str]:
    ids = sorted({u.hospital_id for u in rows if u.hospital_id})
    if not ids:
        return {}
    filters = [Hospital.id.in_(ids)]
    if tenant_id:
        filters.append(Hospital.tenant_id == tenant_id)
    stmt = select(Hospital.id, Hospital.name).where(*filters)
    hospitals = (await db.execute(stmt)).all()
    return {int(h[0]): str(h[1]) for h in hospitals}


async def _load_department_name_map(db: AsyncSession, rows: list[User], tenant_id: int | None = None) -> dict[int, str]:
    ids = sorted({u.department_id for u in rows if u.department_id})
    if not ids:
        return {}
    filters = [Department.id.in_(ids)]
    if tenant_id:
        filters.append(Department.tenant_id == tenant_id)
    stmt = select(Department.id, Department.name).where(*filters)
    departments = (await db.execute(stmt)).all()
    return {int(d[0]): str(d[1]) for d in departments}


async def _load_tenant_name_map(db: AsyncSession, rows: list[User]) -> dict[int, str]:
    ids = sorted({u.tenant_id for u in rows if u.tenant_id})
    if not ids:
        return {}
    stmt = select(Tenant.id, Tenant.name).where(Tenant.id.in_(ids))
    tenants = (await db.execute(stmt)).all()
    return {int(t[0]): str(t[1]) for t in tenants}


async def _load_user_hospital_links(db: AsyncSession, user_ids: list[int]) -> dict[int, list[int]]:
    if not user_ids:
        return {}
    rows = (
        await db.execute(select(UserHospital.user_id, UserHospital.hospital_id).where(UserHospital.user_id.in_(user_ids)))
    ).all()
    result: dict[int, list[int]] = {}
    for uid, hid in rows:
        result.setdefault(int(uid), []).append(int(hid))
    for uid in result:
        result[uid] = sorted(set(result[uid]))
    return result


async def _load_user_department_links(db: AsyncSession, user_ids: list[int]) -> dict[int, list[int]]:
    if not user_ids:
        return {}
    rows = (
        await db.execute(
            select(UserDepartment.user_id, UserDepartment.department_id).where(UserDepartment.user_id.in_(user_ids))
        )
    ).all()
    result: dict[int, list[int]] = {}
    for uid, did in rows:
        result.setdefault(int(uid), []).append(int(did))
    for uid in result:
        result[uid] = sorted(set(result[uid]))
    return result


def _to_user_item(
    user: User,
    hospital_name: str | None,
    hospital_ids: list[int] | None = None,
    department_name: str | None = None,
    department_ids: list[int] | None = None,
    tenant_name: str | None = None,
) -> UserItem:
    return UserItem(
        id=user.id,
        username=user.username,
        real_name=user.real_name,
        role=user.role,
        hospital_id=user.hospital_id,
        hospital_name=hospital_name,
        hospital_ids=hospital_ids or [],
        department_id=user.department_id,
        department_name=department_name,
        department_ids=department_ids or [],
        menu_permissions=_parse_menu_permissions(user.menu_permissions),
        is_all_hospitals=bool(user.is_all_hospitals or user.role == "super_admin"),
        is_active=user.is_active,
        tenant_id=user.tenant_id,
        tenant_name=tenant_name,
        created_at=user.created_at,
    )


@router.get("", response_model=ApiResponse)
async def list_users(
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=500),
    keyword: str | None = None,
    role: str | None = None,
    hospital_id: int | None = None,
    department_id: int | None = None,
) -> ApiResponse:
    is_platform_admin = is_platform_super_admin(current_user)
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="user:list",
        required_roles={"admin", "super_admin"},
        request=request,
        target_tenant_id=(int(current_user.tenant_id) if current_user.tenant_id else None),
        target_hospital_id=hospital_id,
        target_department_id=department_id,
        target_type="user",
        extra_detail={"query_role": role, "query_keyword": keyword},
    )
    filters = []
    if keyword:
        filters.append(User.real_name.like(f"%{keyword}%"))
    if role:
        if role not in VALID_ROLES:
            raise HTTPException(status_code=400, detail="无效角色筛选")
        filters.append(User.role == role)
    if not is_platform_admin:
        filters.append(User.tenant_id == current_user.tenant_id)
    if department_id:
        filters.append(
            (User.department_id == department_id)
            | (User.id.in_(select(UserDepartment.user_id).where(UserDepartment.department_id == department_id)))
        )
    accessible_hospital_ids = await get_accessible_hospital_ids(current_user, db)
    accessible_department_ids = await get_accessible_department_ids(current_user, db)
    if current_user.role == "super_admin" or current_user.is_all_hospitals:
        if hospital_id:
            filters.append(
                (User.hospital_id == hospital_id)
                | (
                    User.id.in_(
                        select(UserHospital.user_id).where(UserHospital.hospital_id == hospital_id)
                    )
                )
            )
    else:
        filters.append(
            (User.department_id.in_(accessible_department_ids))
            | (User.hospital_id.in_(accessible_hospital_ids))
            | (
                User.id.in_(
                    select(UserHospital.user_id).where(UserHospital.hospital_id.in_(accessible_hospital_ids))
                )
            )
            | (
                User.id.in_(
                    select(UserDepartment.user_id).where(UserDepartment.department_id.in_(accessible_department_ids))
                )
            )
        )
    total = (await db.execute(select(func.count(User.id)).where(*filters))).scalar_one()
    stmt = (
        select(User)
        .where(*filters)
        .order_by(User.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.execute(stmt)).scalars().all()
    _tenant_id = current_user.tenant_id if not is_platform_admin else None
    hospital_name_map = await _load_hospital_name_map(db, rows, tenant_id=_tenant_id)
    department_name_map = await _load_department_name_map(db, rows, tenant_id=_tenant_id)
    tenant_name_map = await _load_tenant_name_map(db, rows)
    link_map = await _load_user_hospital_links(db, [u.id for u in rows])
    dep_link_map = await _load_user_department_links(db, [u.id for u in rows])
    items = [
        _to_user_item(
            u,
            hospital_name_map.get(u.hospital_id or 0),
            link_map.get(u.id, []),
            department_name_map.get(u.department_id or 0),
            dep_link_map.get(u.id, []),
            tenant_name_map.get(u.tenant_id or 0),
        )
        for u in rows
    ]
    return ApiResponse(code=200, message="success", data=UserListData(items=items, total=total, page=page, page_size=page_size))


@router.post("", response_model=ApiResponse)
async def create_user(
    payload: UserCreateRequest,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    is_platform_admin = is_platform_super_admin(current_user)
    if payload.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="无效角色")
    if payload.menu_permissions is not None and not is_platform_admin:
        raise HTTPException(status_code=403, detail="仅超级管理员可配置菜单权限")
    if not is_platform_admin and payload.role == "super_admin":
        raise HTTPException(status_code=403, detail="仅平台超级管理员可创建超级管理员")
    target_tenant_id = (
        int(payload.tenant_id)
        if payload.tenant_id
        else (int(current_user.tenant_id) if current_user.tenant_id else 1)
    )
    if not is_platform_admin and payload.tenant_id and payload.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="无权创建到其他租户")
    if target_tenant_id:
        tenant_exists = (await db.execute(select(Tenant.id).where(Tenant.id == target_tenant_id))).scalar_one_or_none()
        if not tenant_exists:
            raise HTTPException(status_code=404, detail="租户不存在")
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="user:create",
        required_roles={"admin", "super_admin"},
        request=request,
        target_tenant_id=target_tenant_id,
        target_hospital_id=payload.hospital_id,
        target_department_id=payload.department_id,
        target_type="user",
        extra_detail={"target_role": payload.role},
    )
    accessible_hospital_ids = await get_accessible_hospital_ids(current_user, db)
    accessible_department_ids = await get_accessible_department_ids(current_user, db)

    target_hospital_id: int | None = None
    target_department_id: int | None = None
    target_hospital_ids: list[int] = []
    target_department_ids: list[int] = []
    is_all_hospitals = bool(payload.is_all_hospitals and payload.role in {"admin", "super_admin"})

    if payload.role == "super_admin":
        if not is_platform_admin:
            raise HTTPException(status_code=403, detail="仅平台超级管理员可创建超级管理员")
        is_all_hospitals = True
    elif payload.role == "student":
        candidate_dep_id = payload.department_id or (payload.department_ids[0] if payload.department_ids else None)
        if not candidate_dep_id and payload.hospital_id:
            mapped = (
                await db.execute(
                    select(Department.id)
                    .where(Department.hospital_id == payload.hospital_id)
                    .order_by(Department.id.asc())
                    .limit(1)
                )
            ).scalars().first()
            candidate_dep_id = int(mapped) if mapped else None
        if not candidate_dep_id:
            raise HTTPException(status_code=400, detail="咨询员必须绑定一个所属科室")
        target_department_id = int(candidate_dep_id)
        target_department_ids = [target_department_id]
        if current_user.role != "super_admin" and not current_user.is_all_hospitals:
            if target_department_id not in accessible_department_ids:
                raise HTTPException(status_code=403, detail="无权分配到该科室")
    elif payload.role == "admin":
        if is_all_hospitals and current_user.role != "super_admin":
            raise HTTPException(status_code=403, detail="仅超级管理员可创建全医院管理员")
        if is_all_hospitals:
            target_hospital_ids = []
            target_department_ids = []
            target_hospital_id = None
            target_department_id = None
        else:
            candidate_department_ids = sorted(
                {
                    int(did)
                    for did in ([payload.department_id] if payload.department_id else []) + payload.department_ids
                    if did
                }
            )
            if not candidate_department_ids and payload.hospital_ids:
                rows = (
                    await db.execute(select(Department.id).where(Department.hospital_id.in_(payload.hospital_ids)))
                ).all()
                candidate_department_ids = sorted({int(r[0]) for r in rows})
            if not candidate_department_ids and payload.hospital_id:
                rows = (
                    await db.execute(select(Department.id).where(Department.hospital_id == payload.hospital_id))
                ).all()
                candidate_department_ids = sorted({int(r[0]) for r in rows})
            if not candidate_department_ids:
                raise HTTPException(status_code=400, detail="管理员至少需要分配一个负责科室")
            if current_user.role != "super_admin" and not current_user.is_all_hospitals:
                if any(did not in accessible_department_ids for did in candidate_department_ids):
                    raise HTTPException(status_code=403, detail="无权分配超出当前管理员范围的科室")
            target_department_ids = candidate_department_ids
            target_department_id = candidate_department_ids[0]

    exists = (
        await db.execute(
            select(User).where(User.username == payload.username, User.tenant_id == target_tenant_id)
        )
    ).scalars().first()
    if exists:
        raise HTTPException(status_code=400, detail="用户名已存在（同租户内不能重名）")
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        real_name=payload.real_name,
        role=payload.role,
        tenant_id=target_tenant_id,
        hospital_id=target_hospital_id,
        department_id=target_department_id,
        menu_permissions=(
            _serialize_menu_permissions(payload.menu_permissions)
            if payload.role == "admin"
            else None
        ),
        is_all_hospitals=is_all_hospitals,
        is_active=True,
    )
    db.add(user)
    await db.flush()

    primary_hospital_name = None
    primary_department_name = None
    if target_department_ids and payload.role in {"admin", "student"}:
        departments = (
            await db.execute(
                select(Department.id, Department.name, Department.hospital_id).where(
                    Department.id.in_(target_department_ids)
                )
            )
        ).all()
        existing_ids = {int(d[0]) for d in departments}
        missing = [did for did in target_department_ids if did not in existing_ids]
        if missing:
            raise HTTPException(status_code=404, detail=f"科室不存在: {missing}")
        department_hospital_ids = sorted({int(d[2]) for d in departments})
        target_hospital_ids = department_hospital_ids
        if target_hospital_id is None and department_hospital_ids:
            target_hospital_id = department_hospital_ids[0]
        if target_department_id is None:
            target_department_id = target_department_ids[0]
        user.hospital_id = target_hospital_id
        user.department_id = target_department_id
        for did in target_department_ids:
            db.add(UserDepartment(user_id=user.id, department_id=did))
        for hid in department_hospital_ids:
            db.add(UserHospital(user_id=user.id, hospital_id=hid))
        department_name_map = {int(d[0]): str(d[1]) for d in departments}
        primary_department_name = department_name_map.get(target_department_id or 0)
        hospitals = (
            await db.execute(select(Hospital.id, Hospital.name).where(Hospital.id.in_(department_hospital_ids)))
        ).all()
        hospital_name_map = {int(h[0]): str(h[1]) for h in hospitals}
        primary_hospital_name = hospital_name_map.get(target_hospital_id or 0)

    await db.commit()
    await db.refresh(user)
    tenant_name = None
    if user.tenant_id:
        tenant = (await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))).scalars().first()
        tenant_name = tenant.name if tenant else None
    return ApiResponse(
        code=200,
        message="success",
        data=_to_user_item(
            user,
            primary_hospital_name,
            target_hospital_ids,
            primary_department_name,
            target_department_ids,
            tenant_name,
        ),
    )


@router.get("/{user_id}", response_model=ApiResponse)
async def get_user(
    user_id: int,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    is_platform_admin = is_platform_super_admin(current_user)
    user_filters = [User.id == user_id]
    if not is_platform_admin:
        user_filters.append(User.tenant_id == current_user.tenant_id)
    user_row = (
        await db.execute(
            select(User, Hospital.name.label("hospital_name"), Department.name.label("department_name"), Tenant.name.label("tenant_name"))
            .outerjoin(Hospital, Hospital.id == User.hospital_id)
            .outerjoin(Department, Department.id == User.department_id)
            .outerjoin(Tenant, Tenant.id == User.tenant_id)
            .where(*user_filters)
            .limit(1)
        )
    ).first()
    user = user_row[0] if user_row else None
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="user:read",
        required_roles={"admin", "super_admin"},
        request=request,
        target_tenant_id=user.tenant_id,
        target_hospital_id=user.hospital_id,
        target_department_id=user.department_id,
        target_type="user",
        target_id=user.id,
    )
    link_map = await _load_user_hospital_links(db, [user.id])
    dep_link_map = await _load_user_department_links(db, [user.id])
    user_hospital_ids = sorted(set(link_map.get(user.id, []) + ([user.hospital_id] if user.hospital_id else [])))
    user_department_ids = sorted(
        set(dep_link_map.get(user.id, []) + ([user.department_id] if user.department_id else []))
    )
    if current_user.role != "super_admin" and not current_user.is_all_hospitals:
        accessible_hospital_ids = await get_accessible_hospital_ids(current_user, db)
        accessible_department_ids = await get_accessible_department_ids(current_user, db)
        if not (
            any(hid in accessible_hospital_ids for hid in user_hospital_ids)
            or any(did in accessible_department_ids for did in user_department_ids)
        ):
            raise HTTPException(status_code=403, detail="无权查看其他医院用户")
    hospital_name = str(user_row[1]) if user_row and user_row[1] else None
    department_name = str(user_row[2]) if user_row and user_row[2] else None
    tenant_name = str(user_row[3]) if user_row and user_row[3] else None
    return ApiResponse(
        code=200,
        message="success",
        data=_to_user_item(
            user,
            hospital_name,
            user_hospital_ids,
            department_name,
            user_department_ids,
            tenant_name,
        ),
    )


@router.put("/{user_id}", response_model=ApiResponse)
async def update_user(
    user_id: int,
    payload: UserUpdateRequest,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    is_platform_admin = is_platform_super_admin(current_user)
    update_user_filters = [User.id == user_id]
    if not is_platform_admin:
        update_user_filters.append(User.tenant_id == current_user.tenant_id)
    user = (await db.execute(select(User).where(*update_user_filters))).scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="user:update",
        required_roles={"admin", "super_admin"},
        request=request,
        target_tenant_id=user.tenant_id,
        target_hospital_id=user.hospital_id,
        target_department_id=user.department_id,
        target_type="user",
        target_id=user.id,
    )
    before_menu_permissions = _parse_menu_permissions(user.menu_permissions)

    link_map = await _load_user_hospital_links(db, [user.id])
    dep_link_map = await _load_user_department_links(db, [user.id])
    user_hospital_ids = sorted(set(link_map.get(user.id, []) + ([user.hospital_id] if user.hospital_id else [])))
    user_department_ids = sorted(
        set(dep_link_map.get(user.id, []) + ([user.department_id] if user.department_id else []))
    )
    before_scope_ids = list(user_hospital_ids)
    before_department_scope_ids = list(user_department_ids)
    before_snapshot = build_user_snapshot(
        role=user.role,
        real_name=user.real_name,
        hospital_id=user.hospital_id,
        department_id=user.department_id,
    )
    before_is_all_hospitals = bool(user.is_all_hospitals)
    accessible_hospital_ids = await get_accessible_hospital_ids(current_user, db)
    accessible_department_ids = await get_accessible_department_ids(current_user, db)
    if current_user.role != "super_admin" and not current_user.is_all_hospitals:
        if user.role == "super_admin":
            raise HTTPException(status_code=403, detail="无权编辑超级管理员")
        if not (
            any(hid in accessible_hospital_ids for hid in user_hospital_ids)
            or any(did in accessible_department_ids for did in user_department_ids)
        ):
            raise HTTPException(status_code=403, detail="无权编辑其他医院用户")

    target_role = payload.role or user.role
    if target_role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="无效角色")
    if not is_platform_admin and target_role == "super_admin":
        raise HTTPException(status_code=403, detail="仅平台超级管理员可设置超级管理员角色")
    user.role = target_role
    if user.role == "super_admin":
        user.is_all_hospitals = True
        user.menu_permissions = None

    password_changed = False
    if payload.real_name is not None:
        user.real_name = payload.real_name
    if payload.tenant_id is not None:
        if not is_platform_admin:
            raise HTTPException(status_code=403, detail="仅平台超级管理员可调整租户")
        tenant_exists = (await db.execute(select(Tenant.id).where(Tenant.id == payload.tenant_id))).scalar_one_or_none()
        if not tenant_exists:
            raise HTTPException(status_code=404, detail="租户不存在")
        user.tenant_id = payload.tenant_id
    if payload.password:
        user.password_hash = hash_password(payload.password)
        password_changed = True

    menu_permissions_changed = False
    menu_permissions_provided = "menu_permissions" in payload.model_fields_set
    if menu_permissions_provided:
        if current_user.role != "super_admin":
            raise HTTPException(status_code=403, detail="仅超级管理员可配置菜单权限")
        if current_user.id == user.id:
            raise HTTPException(status_code=400, detail="不允许修改自己的菜单权限")
        if user.role != "admin" or payload.menu_permissions is None:
            user.menu_permissions = None
        else:
            user.menu_permissions = _serialize_menu_permissions(payload.menu_permissions)
        menu_permissions_changed = before_menu_permissions != _parse_menu_permissions(user.menu_permissions)
    elif user.role != "admin":
        user.menu_permissions = None
        menu_permissions_changed = before_menu_permissions != _parse_menu_permissions(user.menu_permissions)

    update_hospital_scope = (
        payload.hospital_id is not None
        or payload.hospital_ids is not None
        or payload.department_id is not None
        or payload.department_ids is not None
        or payload.is_all_hospitals is not None
    )
    if update_hospital_scope:
        if current_user.role != "super_admin" and not current_user.is_all_hospitals:
            raise HTTPException(status_code=403, detail="当前账号无权调整医院权限范围")
        is_all = bool(payload.is_all_hospitals) if payload.is_all_hospitals is not None else bool(user.is_all_hospitals)
        if user.role == "super_admin":
            is_all = True
        candidate_department_ids = set(user_department_ids)
        if payload.department_ids is not None:
            candidate_department_ids = {int(did) for did in payload.department_ids if did}
        if payload.department_id is not None:
            candidate_department_ids.add(int(payload.department_id))
        if payload.hospital_ids is not None:
            rows = (
                await db.execute(select(Department.id).where(Department.hospital_id.in_(payload.hospital_ids)))
            ).all()
            candidate_department_ids.update(int(r[0]) for r in rows)
        if payload.hospital_id is not None:
            rows = (
                await db.execute(select(Department.id).where(Department.hospital_id == payload.hospital_id))
            ).all()
            candidate_department_ids.update(int(r[0]) for r in rows)

        if user.role == "student":
            if is_all:
                is_all = False
            if not candidate_department_ids:
                raise HTTPException(status_code=400, detail="咨询员必须绑定一个所属科室")
            candidate_department_ids = {sorted(candidate_department_ids)[0]}
        elif user.role == "admin":
            if not is_all and not candidate_department_ids:
                raise HTTPException(status_code=400, detail="管理员至少需要分配一个负责科室")
        else:
            candidate_department_ids = set()

        if candidate_department_ids:
            rows = (
                await db.execute(
                    select(Department.id, Department.hospital_id).where(
                        Department.id.in_(sorted(candidate_department_ids))
                    )
                )
            ).all()
            found = {int(r[0]) for r in rows}
            missing = [did for did in sorted(candidate_department_ids) if did not in found]
            if missing:
                raise HTTPException(status_code=404, detail=f"科室不存在: {missing}")
            if current_user.role != "super_admin" and not current_user.is_all_hospitals:
                if any(did not in accessible_department_ids for did in candidate_department_ids):
                    raise HTTPException(status_code=403, detail="无权分配超出当前管理员范围的科室")
            candidate_hospital_ids = sorted({int(r[1]) for r in rows})
        else:
            candidate_hospital_ids = []

        user.is_all_hospitals = is_all
        if user.role in {"admin", "student"}:
            user.department_id = sorted(candidate_department_ids)[0] if candidate_department_ids else None
            user.hospital_id = candidate_hospital_ids[0] if candidate_hospital_ids else None
        else:
            user.department_id = None
            user.hospital_id = None

        old_hospital_links = (
            await db.execute(select(UserHospital).where(UserHospital.user_id == user.id))
        ).scalars().all()
        for link in old_hospital_links:
            await db.delete(link)
        old_department_links = (
            await db.execute(select(UserDepartment).where(UserDepartment.user_id == user.id))
        ).scalars().all()
        for link in old_department_links:
            await db.delete(link)
        for did in sorted(candidate_department_ids):
            db.add(UserDepartment(user_id=user.id, department_id=did))
        for hid in sorted(candidate_hospital_ids):
            db.add(UserHospital(user_id=user.id, hospital_id=hid))

    if user.role in {"admin", "student"} and user.department_id is None and not user.is_all_hospitals:
        raise HTTPException(status_code=400, detail="管理员和咨询员必须绑定科室")
    hospital_name = None
    department_name = None
    tenant_name = None
    if user.hospital_id:
        hospital = (await db.execute(select(Hospital).where(Hospital.id == user.hospital_id))).scalars().first()
        hospital_name = hospital.name if hospital else None
    if user.department_id:
        department = (
            await db.execute(select(Department).where(Department.id == user.department_id))
        ).scalars().first()
        department_name = department.name if department else None
    if user.tenant_id:
        tenant = (await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))).scalars().first()
        tenant_name = tenant.name if tenant else None
    link_map = await _load_user_hospital_links(db, [user.id])
    dep_link_map = await _load_user_department_links(db, [user.id])
    user_hospital_ids = sorted(set(link_map.get(user.id, []) + ([user.hospital_id] if user.hospital_id else [])))
    user_department_ids = sorted(
        set(dep_link_map.get(user.id, []) + ([user.department_id] if user.department_id else []))
    )
    after_snapshot = build_user_snapshot(
        role=user.role,
        real_name=user.real_name,
        hospital_id=user.hospital_id,
        department_id=user.department_id,
    )
    permission_changed = (
        before_snapshot["role"] != after_snapshot["role"]
        or before_snapshot["hospital_id"] != after_snapshot["hospital_id"]
        or before_snapshot["department_id"] != after_snapshot["department_id"]
        or before_is_all_hospitals != bool(user.is_all_hospitals)
        or before_scope_ids != user_hospital_ids
        or before_department_scope_ids != user_department_ids
        or password_changed
        or menu_permissions_changed
    )
    if permission_changed:
        await append_audit_log(
            db,
            action="user_permission_change",
            user_id=current_user.id,
            target_type="user",
            target_id=user.id,
            hospital_id=user.hospital_id,
            department_id=user.department_id,
            detail={
                "before": {
                    "role": before_snapshot["role"],
                    "hospital_id": before_snapshot["hospital_id"],
                    "hospital_ids": before_scope_ids,
                    "department_id": before_snapshot["department_id"],
                    "department_ids": before_department_scope_ids,
                    "is_all_hospitals": before_is_all_hospitals,
                    "menu_permissions": before_menu_permissions,
                },
                "after": {
                    "role": after_snapshot["role"],
                    "hospital_id": after_snapshot["hospital_id"],
                    "hospital_ids": user_hospital_ids,
                    "department_id": after_snapshot["department_id"],
                    "department_ids": user_department_ids,
                    "is_all_hospitals": bool(user.is_all_hospitals),
                    "menu_permissions": _parse_menu_permissions(user.menu_permissions),
                },
                "password_changed": password_changed,
            },
            ip=get_request_ip(request),
        )
    if menu_permissions_changed:
        await append_audit_log(
            db,
            action="update_menu_permissions",
            user_id=current_user.id,
            target_type="user",
            target_id=user.id,
            hospital_id=user.hospital_id,
            department_id=user.department_id,
            detail={
                "before": before_menu_permissions,
                "after": _parse_menu_permissions(user.menu_permissions),
            },
            ip=get_request_ip(request),
        )
    await db.commit()
    return ApiResponse(
        code=200,
        message="success",
        data=_to_user_item(
            user,
            hospital_name,
            user_hospital_ids,
            department_name,
            user_department_ids,
            tenant_name,
        ),
    )


@router.delete("/{user_id}", response_model=ApiResponse)
async def toggle_user(
    user_id: int,
    request: Request,
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    is_platform_admin = is_platform_super_admin(current_user)
    toggle_filters = [User.id == user_id]
    if not is_platform_admin:
        toggle_filters.append(User.tenant_id == current_user.tenant_id)
    user = (await db.execute(select(User).where(*toggle_filters))).scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.role == "super_admin":
        raise HTTPException(status_code=400, detail="不能禁用超级管理员")
    old_active = bool(user.is_active)
    user.is_active = not user.is_active
    await append_audit_log(
        db,
        action="user_permission_change",
        user_id=current_user.id,
        target_type="user",
        target_id=user.id,
        hospital_id=user.hospital_id,
        department_id=user.department_id,
        detail={"before_active": old_active, "after_active": bool(user.is_active), "reason": "toggle_user"},
        ip=get_request_ip(request),
    )
    await db.commit()
    hospital_name = None
    department_name = None
    tenant_name = None
    if user.hospital_id:
        hospital = (await db.execute(select(Hospital).where(Hospital.id == user.hospital_id))).scalars().first()
        hospital_name = hospital.name if hospital else None
    if user.department_id:
        department = (
            await db.execute(select(Department).where(Department.id == user.department_id))
        ).scalars().first()
        department_name = department.name if department else None
    if user.tenant_id:
        tenant = (await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))).scalars().first()
        tenant_name = tenant.name if tenant else None
    link_map = await _load_user_hospital_links(db, [user.id])
    dep_link_map = await _load_user_department_links(db, [user.id])
    user_hospital_ids = sorted(set(link_map.get(user.id, []) + ([user.hospital_id] if user.hospital_id else [])))
    user_department_ids = sorted(
        set(dep_link_map.get(user.id, []) + ([user.department_id] if user.department_id else []))
    )
    return ApiResponse(
        code=200,
        message="success",
        data=_to_user_item(
            user,
            hospital_name,
            user_hospital_ids,
            department_name,
            user_department_ids,
            tenant_name,
        ),
    )


@router.post("/bulk-import-students", response_model=ApiResponse)
async def bulk_import_users(
    payload: BulkUserImportRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    if payload.role not in {"student", "admin"}:
        raise HTTPException(status_code=400, detail="批量导入仅支持咨询员或管理员角色")
    if payload.role == "admin" and current_user.role != "super_admin":
        raise HTTPException(status_code=403, detail="仅超级管理员可批量导入管理员")
    if not payload.items:
        raise HTTPException(status_code=400, detail="导入列表不能为空")

    accessible_hospital_ids = await get_accessible_hospital_ids(current_user, db)
    accessible_department_ids = await get_accessible_department_ids(current_user, db)
    current_hospital_id = current_user.hospital_id or (accessible_hospital_ids[0] if accessible_hospital_ids else None)
    current_department_id = current_user.department_id or (
        accessible_department_ids[0] if accessible_department_ids else None
    )

    created = 0
    skipped = 0
    errors: list[str] = []
    failed_items: list[dict[str, str | int]] = []

    import_tenant_id = current_user.tenant_id
    usernames = [i.username.strip() for i in payload.items if i.username.strip()]
    existed_rows = (
        await db.execute(
            select(User.username).where(User.username.in_(usernames), User.tenant_id == import_tenant_id)
        )
    ).all()
    existed = {row[0] for row in existed_rows}

    for idx, item in enumerate(payload.items, start=1):
        username = item.username.strip()
        real_name = item.real_name.strip()
        if not username or not real_name:
            skipped += 1
            reason = "用户名或姓名为空"
            errors.append(f"第{idx}行：{reason}")
            failed_items.append(
                {
                    "line_no": idx,
                    "username": username or "-",
                    "real_name": real_name or "-",
                    "reason": reason,
                }
            )
            continue
        if username in existed:
            skipped += 1
            reason = f"用户名 {username} 已存在"
            errors.append(f"第{idx}行：{reason}")
            failed_items.append(
                {
                    "line_no": idx,
                    "username": username,
                    "real_name": real_name,
                    "reason": reason,
                }
            )
            continue

        target_department_id = item.department_id or payload.department_id or current_department_id
        if not target_department_id:
            target_hospital_id = item.hospital_id or payload.hospital_id or current_hospital_id
            if target_hospital_id:
                mapped = (
                    await db.execute(
                        select(Department.id)
                        .where(Department.hospital_id == target_hospital_id)
                        .order_by(Department.id.asc())
                        .limit(1)
                    )
                ).scalars().first()
                target_department_id = int(mapped) if mapped else None
        if not target_department_id:
            skipped += 1
            reason = "未设置所属科室"
            errors.append(f"第{idx}行：{reason}")
            failed_items.append(
                {
                    "line_no": idx,
                    "username": username,
                    "real_name": real_name,
                    "reason": reason,
                }
            )
            continue
        if current_user.role != "super_admin" and not current_user.is_all_hospitals:
            if target_department_id not in accessible_department_ids:
                skipped += 1
                reason = f"无权分配到科室ID {target_department_id}"
                errors.append(f"第{idx}行：{reason}")
                failed_items.append(
                    {
                        "line_no": idx,
                        "username": username,
                        "real_name": real_name,
                        "reason": reason,
                    }
                )
                continue
        dept_import_filters = [Department.id == target_department_id]
        if current_user.tenant_id:
            dept_import_filters.append(Department.tenant_id == current_user.tenant_id)
        department = (
            await db.execute(select(Department).where(*dept_import_filters))
        ).scalars().first()
        if not department:
            skipped += 1
            reason = f"科室ID {target_department_id} 不存在"
            errors.append(f"第{idx}行：{reason}")
            failed_items.append(
                {
                    "line_no": idx,
                    "username": username,
                    "real_name": real_name,
                    "reason": reason,
                }
            )
            continue
        target_hospital_id = department.hospital_id

        password = (item.password or payload.default_password).strip()
        if len(password) < 6:
            skipped += 1
            reason = "密码长度不足6位"
            errors.append(f"第{idx}行：{reason}")
            failed_items.append(
                {
                    "line_no": idx,
                    "username": username,
                    "real_name": real_name,
                    "reason": reason,
                }
            )
            continue

        row = User(
            username=username,
            password_hash=hash_password(password),
            real_name=real_name,
            role=payload.role,
            tenant_id=current_user.tenant_id,
            hospital_id=target_hospital_id,
            department_id=target_department_id,
            is_all_hospitals=False,
            is_active=True,
        )
        db.add(row)
        await db.flush()
        db.add(UserDepartment(user_id=row.id, department_id=target_department_id))
        if target_hospital_id:
            db.add(UserHospital(user_id=row.id, hospital_id=target_hospital_id))
        existed.add(username)
        created += 1

    await db.commit()
    return ApiResponse(
        code=200,
        message="success",
        data=BulkUserImportData(
            total=len(payload.items),
            created=created,
            skipped=skipped,
            errors=errors[:50],
            failed_items=failed_items[:200],
        ),
    )


@router.post("/bulk-status", response_model=ApiResponse)
async def bulk_set_user_status(
    payload: BulkUserStatusRequest,
    request: Request,
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    is_platform_admin = is_platform_super_admin(current_user)
    user_ids = sorted({int(uid) for uid in payload.user_ids if uid})
    if not user_ids:
        raise HTTPException(status_code=400, detail="请选择至少一个用户")

    bulk_status_filters = [User.id.in_(user_ids)]
    if not is_platform_admin:
        bulk_status_filters.append(User.tenant_id == current_user.tenant_id)
    users = (await db.execute(select(User).where(*bulk_status_filters))).scalars().all()
    updated = 0
    skipped_ids: list[int] = []
    for user in users:
        if user.role == "super_admin":
            skipped_ids.append(user.id)
            continue
        if bool(user.is_active) == bool(payload.is_active):
            continue
        old_active = bool(user.is_active)
        user.is_active = bool(payload.is_active)
        updated += 1
        await append_audit_log(
            db,
            action="user_permission_change",
            user_id=current_user.id,
            target_type="user",
            target_id=user.id,
            hospital_id=user.hospital_id,
            department_id=user.department_id,
            detail={
                "before_active": old_active,
                "after_active": bool(user.is_active),
                "reason": "bulk_status_change",
            },
            ip=get_request_ip(request),
        )

    await db.commit()
    return ApiResponse(
        code=200,
        message="success",
        data=BulkUserStatusData(
            total=len(user_ids),
            updated=updated,
            skipped=max(0, len(user_ids) - updated),
            skipped_user_ids=sorted(set(skipped_ids)),
        ),
    )


@router.post("/bulk-menu-permissions", response_model=ApiResponse)
async def bulk_set_user_menu_permissions(
    payload: BulkUserMenuPermissionsRequest,
    request: Request,
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    is_platform_admin = is_platform_super_admin(current_user)
    user_ids = sorted({int(uid) for uid in payload.user_ids if uid})
    if not user_ids:
        raise HTTPException(status_code=400, detail="请选择至少一个用户")

    target_menu_permissions_raw = _serialize_menu_permissions(payload.menu_permissions)
    target_menu_permissions = _parse_menu_permissions(target_menu_permissions_raw)

    bulk_menu_filters = [User.id.in_(user_ids)]
    if not is_platform_admin:
        bulk_menu_filters.append(User.tenant_id == current_user.tenant_id)
    users = (await db.execute(select(User).where(*bulk_menu_filters))).scalars().all()
    user_map = {int(user.id): user for user in users}
    skipped_reason_ids: dict[str, list[int]] = {
        "用户不存在": [],
        "不能修改当前登录账号": [],
        "超级管理员不支持批量设置": [],
        "非管理员角色": [],
        "菜单权限未变化": [],
    }
    updated = 0

    for uid in user_ids:
        if uid not in user_map:
            skipped_reason_ids["用户不存在"].append(uid)

    for user in users:
        if user.id == current_user.id:
            skipped_reason_ids["不能修改当前登录账号"].append(int(user.id))
            continue
        if user.role == "super_admin":
            skipped_reason_ids["超级管理员不支持批量设置"].append(int(user.id))
            continue
        if user.role != "admin":
            skipped_reason_ids["非管理员角色"].append(int(user.id))
            continue
        before_menu_permissions = _parse_menu_permissions(user.menu_permissions)
        if before_menu_permissions == target_menu_permissions:
            skipped_reason_ids["菜单权限未变化"].append(int(user.id))
            continue
        user.menu_permissions = target_menu_permissions_raw
        updated += 1
        await append_audit_log(
            db,
            action="update_menu_permissions",
            user_id=current_user.id,
            target_type="user",
            target_id=user.id,
            hospital_id=user.hospital_id,
            department_id=user.department_id,
            detail={
                "before": before_menu_permissions,
                "after": target_menu_permissions,
                "reason": "bulk_menu_permissions",
            },
            ip=get_request_ip(request),
        )

    await db.commit()
    skipped_ids = sorted({uid for ids in skipped_reason_ids.values() for uid in ids})
    compact_skipped_reason_ids = {k: sorted(v) for k, v in skipped_reason_ids.items() if v}
    return ApiResponse(
        code=200,
        message="success",
        data=BulkUserMenuPermissionsData(
            total=len(user_ids),
            updated=updated,
            skipped=max(0, len(user_ids) - updated),
            skipped_user_ids=skipped_ids,
            skipped_reason_ids=compact_skipped_reason_ids,
        ),
    )
