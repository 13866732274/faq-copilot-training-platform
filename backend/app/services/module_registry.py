from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ModuleDefinition, Tenant, TenantModule


@dataclass(frozen=True)
class ModuleSeed:
    module_id: str
    name: str
    description: str
    icon: str
    menu_keys: list[str]
    permission_points: list[str]
    dependencies: list[str]
    is_default: bool
    sort_order: int


MODULE_SEEDS: tuple[ModuleSeed, ...] = (
    ModuleSeed(
        module_id="mod_training",
        name="对话训练",
        description="案例库导入、案例库管理、分类标签、训练流程、训练记录",
        icon="ChatLineSquare",
        menu_keys=["quiz-import", "quiz-list", "quiz-taxonomy", "practice", "records"],
        permission_points=["quiz.*", "practice.*", "record.*"],
        dependencies=[],
        is_default=True,
        sort_order=10,
    ),
    ModuleSeed(
        module_id="mod_faq",
        name="FAQ 智能知识库",
        description="FAQ 概览、知识条目、AI 问答助手、处理任务",
        icon="Collection",
        menu_keys=["faq-dashboard", "faq-clusters", "faq-copilot", "faq-tasks"],
        permission_points=["faq.*"],
        dependencies=[],
        is_default=False,
        sort_order=20,
    ),
    ModuleSeed(
        module_id="mod_ai_scoring",
        name="AI 智能评分",
        description="训练完成后的 AI 评分能力",
        icon="DataBoard",
        menu_keys=[],
        permission_points=["ai_scoring.*"],
        dependencies=[],
        is_default=False,
        sort_order=30,
    ),
    ModuleSeed(
        module_id="mod_stats",
        name="统计分析",
        description="统计总览、咨询员/案例维度统计、点评",
        icon="PieChart",
        menu_keys=["stats"],
        permission_points=["stats.*"],
        dependencies=[],
        is_default=True,
        sort_order=40,
    ),
    ModuleSeed(
        module_id="mod_export",
        name="数据导出",
        description="导出中心能力",
        icon="Download",
        menu_keys=["export-center"],
        permission_points=["system.export.*"],
        dependencies=[],
        is_default=False,
        sort_order=50,
    ),
    ModuleSeed(
        module_id="mod_audit",
        name="审计增强",
        description="操作审计日志能力",
        icon="List",
        menu_keys=["audit-logs"],
        permission_points=["audit.*"],
        dependencies=[],
        is_default=False,
        sort_order=60,
    ),
)

MODULE_MAP: dict[str, ModuleSeed] = {item.module_id: item for item in MODULE_SEEDS}
MENU_MODULE_MAP: dict[str, str] = {
    menu_key: item.module_id
    for item in MODULE_SEEDS
    for menu_key in item.menu_keys
}


def get_module_seed(module_id: str) -> ModuleSeed | None:
    return MODULE_MAP.get(module_id)


def get_default_module_ids() -> list[str]:
    return [item.module_id for item in MODULE_SEEDS if item.is_default]


def get_module_id_by_menu_key(menu_key: str) -> str | None:
    return MENU_MODULE_MAP.get(menu_key)


async def get_enabled_module_ids(db: AsyncSession, tenant_id: int) -> set[str]:
    """Resolve enabled module ids for a tenant.

    Rule:
    - Start from module_definitions.is_default
    - tenant_modules entries override default values
    """
    definitions = (await db.execute(select(ModuleDefinition.module_id, ModuleDefinition.is_default))).all()
    enabled: set[str] = {str(module_id) for module_id, is_default in definitions if bool(is_default)}
    overrides = (
        await db.execute(
            select(TenantModule.module_id, TenantModule.is_enabled).where(TenantModule.tenant_id == tenant_id)
        )
    ).all()
    for module_id, is_enabled in overrides:
        key = str(module_id)
        if bool(is_enabled):
            enabled.add(key)
        elif key in enabled:
            enabled.remove(key)
    return enabled


async def is_module_enabled(db: AsyncSession, tenant_id: int, module_id: str) -> bool:
    enabled = await get_enabled_module_ids(db, tenant_id)
    return module_id in enabled


async def sync_module_definitions(db: AsyncSession) -> tuple[int, int]:
    """Upsert module definition seed data."""
    existing_rows = (await db.execute(select(ModuleDefinition))).scalars().all()
    existing_map = {row.module_id: row for row in existing_rows}

    created = 0
    updated = 0

    for seed in MODULE_SEEDS:
        payload = {
            "name": seed.name,
            "description": seed.description,
            "icon": seed.icon,
            "menu_keys": json.dumps(seed.menu_keys, ensure_ascii=False),
            "permission_points": json.dumps(seed.permission_points, ensure_ascii=False),
            "dependencies": json.dumps(seed.dependencies, ensure_ascii=False),
            "is_default": bool(seed.is_default),
            "sort_order": int(seed.sort_order),
        }
        row = existing_map.get(seed.module_id)
        if not row:
            db.add(
                ModuleDefinition(
                    module_id=seed.module_id,
                    created_at=datetime.utcnow(),
                    **payload,
                )
            )
            created += 1
            continue

        changed = False
        for key, value in payload.items():
            if getattr(row, key) != value:
                setattr(row, key, value)
                changed = True
        if changed:
            updated += 1

    return created, updated


async def seed_default_tenant_modules(db: AsyncSession) -> tuple[int, int]:
    """Enable default modules for all existing tenants."""
    default_module_ids = get_default_module_ids()
    if not default_module_ids:
        return 0, 0

    tenants = (await db.execute(select(Tenant))).scalars().all()
    existing = (
        await db.execute(
            select(TenantModule.tenant_id, TenantModule.module_id)
            .where(TenantModule.module_id.in_(default_module_ids))
        )
    ).all()
    existing_pairs = {(int(row[0]), str(row[1])) for row in existing}

    created = 0
    already_exists = 0
    now = datetime.utcnow()
    for tenant in tenants:
        for module_id in default_module_ids:
            pair = (int(tenant.id), module_id)
            if pair in existing_pairs:
                already_exists += 1
                continue
            db.add(
                TenantModule(
                    tenant_id=int(tenant.id),
                    module_id=module_id,
                    is_enabled=True,
                    enabled_at=now,
                )
            )
            created += 1

    return created, already_exists

