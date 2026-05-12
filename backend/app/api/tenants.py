from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_platform_super_admin
from app.models import ModuleDefinition, Tenant, TenantModule, User
from app.schemas.tenant import (
    ApiResponse,
    ModuleDefinitionItem,
    ModuleDefinitionListData,
    TenantCreateRequest,
    TenantItem,
    TenantModuleItem,
    TenantModuleListData,
    TenantModuleUpdateRequest,
    TenantListData,
    TenantUpdateRequest,
)

router = APIRouter()

def _json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        key = item.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(key)
    return result


def _to_item(row: Tenant) -> TenantItem:
    return TenantItem(
        id=row.id,
        code=row.code,
        name=row.name,
        is_active=bool(row.is_active),
        session_version=int(row.session_version or 1),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_module_def_item(row: ModuleDefinition) -> ModuleDefinitionItem:
    return ModuleDefinitionItem(
        module_id=row.module_id,
        name=row.name,
        description=row.description,
        icon=row.icon,
        menu_keys=_json_list(row.menu_keys),
        permission_points=_json_list(row.permission_points),
        dependencies=_json_list(row.dependencies),
        is_default=bool(row.is_default),
        sort_order=int(row.sort_order or 0),
    )


async def _build_tenant_module_list(db: AsyncSession, tenant: Tenant) -> TenantModuleListData:
    defs = (await db.execute(select(ModuleDefinition).order_by(ModuleDefinition.sort_order.asc()))).scalars().all()
    overrides = (
        await db.execute(
            select(TenantModule).where(TenantModule.tenant_id == tenant.id)
        )
    ).scalars().all()
    override_map = {row.module_id: row for row in overrides}

    depends_index: dict[str, list[str]] = {}
    for row in defs:
        deps = _json_list(row.dependencies)
        for dep in deps:
            depends_index.setdefault(dep, []).append(row.module_id)

    items: list[TenantModuleItem] = []
    for row in defs:
        override = override_map.get(row.module_id)
        if override:
            is_enabled = bool(override.is_enabled)
            source = "tenant_override"
            enabled_at = override.enabled_at
            disabled_at = override.disabled_at
        else:
            is_enabled = bool(row.is_default)
            source = "default"
            enabled_at = None
            disabled_at = None
        items.append(
            TenantModuleItem(
                tenant_id=tenant.id,
                module_id=row.module_id,
                name=row.name,
                description=row.description,
                icon=row.icon,
                menu_keys=_json_list(row.menu_keys),
                dependencies=_json_list(row.dependencies),
                depended_by=sorted(depends_index.get(row.module_id, [])),
                is_default=bool(row.is_default),
                is_enabled=is_enabled,
                source=source,
                enabled_at=enabled_at,
                disabled_at=disabled_at,
                sort_order=int(row.sort_order or 0),
            )
        )

    return TenantModuleListData(
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        items=items,
        total=len(items),
    )


@router.get("", response_model=ApiResponse)
async def list_tenants(
    _: User = Depends(require_platform_super_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    rows = (await db.execute(select(Tenant).order_by(Tenant.id.asc()))).scalars().all()
    total = (await db.execute(select(func.count(Tenant.id)))).scalar_one()
    return ApiResponse(
        code=200,
        message="success",
        data=TenantListData(items=[_to_item(r) for r in rows], total=total),
    )


@router.post("", response_model=ApiResponse)
async def create_tenant(
    payload: TenantCreateRequest,
    _: User = Depends(require_platform_super_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    code = payload.code.strip().lower()
    name = payload.name.strip()
    if not code:
        raise HTTPException(status_code=400, detail="租户编码不能为空")
    if not name:
        raise HTTPException(status_code=400, detail="租户名称不能为空")
    exists = (await db.execute(select(Tenant.id).where(Tenant.code == code))).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=400, detail="租户编码已存在")
    row = Tenant(code=code, name=name, is_active=True)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return ApiResponse(code=200, message="success", data=_to_item(row))


@router.get("/modules", response_model=ApiResponse)
async def list_module_definitions(
    _: User = Depends(require_platform_super_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    rows = (await db.execute(select(ModuleDefinition).order_by(ModuleDefinition.sort_order.asc()))).scalars().all()
    items = [_to_module_def_item(row) for row in rows]
    return ApiResponse(
        code=200,
        message="success",
        data=ModuleDefinitionListData(items=items, total=len(items)),
    )


@router.get("/{tenant_id}/modules", response_model=ApiResponse)
async def list_tenant_modules(
    tenant_id: int,
    _: User = Depends(require_platform_super_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    tenant = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalars().first()
    if not tenant:
        raise HTTPException(status_code=404, detail="租户不存在")
    data = await _build_tenant_module_list(db, tenant)
    return ApiResponse(code=200, message="success", data=data)


@router.put("/{tenant_id}/modules", response_model=ApiResponse)
async def update_tenant_module(
    tenant_id: int,
    payload: TenantModuleUpdateRequest,
    _: User = Depends(require_platform_super_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    tenant = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalars().first()
    if not tenant:
        raise HTTPException(status_code=404, detail="租户不存在")

    module_def = (
        await db.execute(select(ModuleDefinition).where(ModuleDefinition.module_id == payload.module_id))
    ).scalars().first()
    if not module_def:
        raise HTTPException(status_code=404, detail="模块不存在")

    defs = (await db.execute(select(ModuleDefinition))).scalars().all()
    def_map = {row.module_id: row for row in defs}
    enabled_map: dict[str, bool] = {}
    overrides = (
        await db.execute(select(TenantModule).where(TenantModule.tenant_id == tenant_id))
    ).scalars().all()
    override_map = {row.module_id: row for row in overrides}
    for module_id, row in def_map.items():
        ov = override_map.get(module_id)
        enabled_map[module_id] = bool(ov.is_enabled) if ov else bool(row.is_default)

    if payload.is_enabled:
        dependencies = _json_list(module_def.dependencies)
        missing = [dep for dep in dependencies if not enabled_map.get(dep, False)]
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"启用失败，缺少依赖模块：{', '.join(missing)}",
            )
    else:
        depending_enabled: list[str] = []
        for module_id, row in def_map.items():
            if module_id == payload.module_id:
                continue
            deps = _json_list(row.dependencies)
            if payload.module_id in deps and enabled_map.get(module_id, False):
                depending_enabled.append(module_id)
        if depending_enabled:
            raise HTTPException(
                status_code=400,
                detail=f"停用失败，以下已启用模块依赖当前模块：{', '.join(sorted(depending_enabled))}",
            )

    row = override_map.get(payload.module_id)
    now = datetime.utcnow()
    if not row:
        row = TenantModule(
            tenant_id=tenant_id,
            module_id=payload.module_id,
            is_enabled=bool(payload.is_enabled),
            enabled_at=now if payload.is_enabled else None,
            disabled_at=None if payload.is_enabled else now,
            config_json=payload.config_json,
        )
        db.add(row)
    else:
        row.is_enabled = bool(payload.is_enabled)
        if payload.is_enabled:
            row.enabled_at = now
            row.disabled_at = None
        else:
            row.disabled_at = now
        row.config_json = payload.config_json
    await db.commit()

    data = await _build_tenant_module_list(db, tenant)
    return ApiResponse(code=200, message="success", data=data)


@router.put("/{tenant_id}", response_model=ApiResponse)
async def update_tenant(
    tenant_id: int,
    payload: TenantUpdateRequest,
    _: User = Depends(require_platform_super_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    row = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="租户不存在")
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="租户名称不能为空")
        row.name = name
    if payload.is_active is not None:
        new_active = bool(payload.is_active)
        if bool(row.is_active) != new_active:
            row.is_active = new_active
            # Bump tenant session version so all old tenant tokens are invalidated immediately.
            row.session_version = int(row.session_version or 1) + 1
    await db.commit()
    await db.refresh(row)
    return ApiResponse(code=200, message="success", data=_to_item(row))
