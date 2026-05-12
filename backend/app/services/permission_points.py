from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import ensure_tenant_bound, is_platform_super_admin
from app.models import SystemSetting, User
from app.services.module_registry import get_enabled_module_ids, get_module_id_by_menu_key

PERMISSION_POINTS: tuple[str, ...] = (
    "system.settings.update",
    "system.export.users",
    "system.export.practices",
    "system.export.quizzes",
    "quiz.batch.reparse",
    "quiz.update",
    "quiz.restore",
    "quiz.delete.soft",
    "quiz.delete.hard",
    "import.batch.submit",
    "import.task.export_failed",
)

MENU_KEYS: tuple[str, ...] = (
    "dashboard",
    "quiz-import",
    "quiz-list",
    "quiz-taxonomy",
    "faq-dashboard",
    "faq-clusters",
    "faq-copilot",
    "faq-copilot-logs",
    "faq-tasks",
    "user-manage",
    "hospital-manage",
    "department-manage",
    "stats",
    "system-settings",
    "permission-policy-diagnostics",
    "tenant-manage",
    "billing-center",
    "export-center",
    "audit-logs",
    "permission-audit",
    "practice",
    "records",
)

ADMIN_CONFIGURABLE_MENU_KEYS: set[str] = {
    "quiz-import",
    "quiz-list",
    "quiz-taxonomy",
    "faq-dashboard",
    "faq-clusters",
    "faq-copilot",
    "faq-copilot-logs",
    "faq-tasks",
    "user-manage",
    "hospital-manage",
    "department-manage",
    "stats",
    "export-center",
}


@dataclass
class PermissionPointDecision:
    point: str
    allowed: bool
    reason: str


@dataclass
class MenuAccessDecision:
    menu_key: str
    allowed: bool
    reason: str


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


def _has_menu_access(user: User, menu_key: str, menu_permissions: list[str] | None) -> bool:
    if user.role == "super_admin":
        return True
    if user.role != "admin":
        return False
    # 兼容旧账号：未配置菜单权限时默认放行
    if menu_permissions is None:
        return True
    # 兼容策略：已拥有“案例管理”权限的账号，自动继承“分类标签中心”。
    if menu_key == "quiz-taxonomy" and "quiz-list" in menu_permissions:
        return True
    return menu_key in menu_permissions


def _allow(point: str) -> PermissionPointDecision:
    return PermissionPointDecision(point=point, allowed=True, reason="")


def _deny(point: str, reason: str) -> PermissionPointDecision:
    return PermissionPointDecision(point=point, allowed=False, reason=reason)


async def _is_export_enabled(db: AsyncSession, tenant_id: int) -> bool:
    row = (
        await db.execute(
            select(SystemSetting).where(SystemSetting.tenant_id == tenant_id).order_by(SystemSetting.id.asc()).limit(1)
        )
    ).scalars().first()
    if not row:
        return True
    return bool(row.enable_export_center)


async def _is_audit_enabled(db: AsyncSession, tenant_id: int) -> bool:
    row = (
        await db.execute(
            select(SystemSetting).where(SystemSetting.tenant_id == tenant_id).order_by(SystemSetting.id.asc()).limit(1)
        )
    ).scalars().first()
    if not row:
        return True
    return bool(row.enable_audit_enhanced)


def _allow_menu(menu_key: str) -> MenuAccessDecision:
    return MenuAccessDecision(menu_key=menu_key, allowed=True, reason="")


def _deny_menu(menu_key: str, reason: str) -> MenuAccessDecision:
    return MenuAccessDecision(menu_key=menu_key, allowed=False, reason=reason)


def _build_menu_access(
    user: User,
    *,
    enabled_modules: set[str],
    menu_permissions: list[str] | None,
    export_enabled: bool,
    audit_enabled: bool,
) -> list[MenuAccessDecision]:
    decisions: list[MenuAccessDecision] = []
    for menu_key in MENU_KEYS:
        module_id = get_module_id_by_menu_key(menu_key)
        if module_id and (not is_platform_super_admin(user)) and module_id not in enabled_modules:
            decisions.append(_deny_menu(menu_key, f"模块未开通：{module_id}"))
            continue

        if menu_key in {"practice", "records"}:
            if user.role == "student":
                decisions.append(_allow_menu(menu_key))
            else:
                decisions.append(_deny_menu(menu_key, "仅咨询员可访问"))
            continue

        if user.role == "student":
            decisions.append(_deny_menu(menu_key, "当前账号无管理权限"))
            continue

        if menu_key == "tenant-manage":
            if is_platform_super_admin(user):
                decisions.append(_allow_menu(menu_key))
            else:
                decisions.append(_deny_menu(menu_key, "仅平台超级管理员可访问租户管理"))
            continue

        if menu_key == "billing-center":
            if not is_platform_super_admin(user):
                decisions.append(_deny_menu(menu_key, "仅平台超级管理员可访问计费中心"))
                continue
            decisions.append(_allow_menu(menu_key))
            continue

        if menu_key == "audit-logs":
            if user.role != "super_admin":
                decisions.append(_deny_menu(menu_key, "仅超级管理员可访问审计日志"))
                continue
            if not audit_enabled:
                decisions.append(_deny_menu(menu_key, "增强审计能力已被系统管理员关闭"))
                continue
            decisions.append(_allow_menu(menu_key))
            continue

        if menu_key == "permission-audit":
            if user.role != "super_admin":
                decisions.append(_deny_menu(menu_key, "仅超级管理员可访问权限体检"))
                continue
            decisions.append(_allow_menu(menu_key))
            continue

        if menu_key == "permission-policy-diagnostics":
            if user.role != "super_admin":
                decisions.append(_deny_menu(menu_key, "仅超级管理员可访问权限策略诊断"))
                continue
            decisions.append(_allow_menu(menu_key))
            continue

        if menu_key == "export-center" and not export_enabled:
            decisions.append(_deny_menu(menu_key, "导出中心已被系统管理员关闭"))
            continue

        if menu_key in ADMIN_CONFIGURABLE_MENU_KEYS:
            if _has_menu_access(user, menu_key, menu_permissions):
                decisions.append(_allow_menu(menu_key))
            else:
                decisions.append(_deny_menu(menu_key, "缺少菜单权限"))
            continue

        decisions.append(_allow_menu(menu_key))

    return decisions


async def build_permission_context(
    user: User,
    db: AsyncSession,
) -> tuple[list[PermissionPointDecision], list[MenuAccessDecision]]:
    menu_permissions = _parse_menu_permissions(user.menu_permissions)
    tenant_id = ensure_tenant_bound(user)
    enabled_modules = await get_enabled_module_ids(db, tenant_id)
    export_enabled = await _is_export_enabled(db, tenant_id)
    audit_enabled = await _is_audit_enabled(db, tenant_id)
    decisions: list[PermissionPointDecision] = []

    for point in PERMISSION_POINTS:
        if point == "system.settings.update":
            if user.role == "super_admin":
                decisions.append(_allow(point))
            else:
                decisions.append(_deny(point, "仅超级管理员可修改系统设置"))
            continue

        if point.startswith("system.export."):
            if user.role not in {"admin", "super_admin"}:
                decisions.append(_deny(point, "当前账号无管理权限"))
                continue
            if not export_enabled:
                decisions.append(_deny(point, "导出中心已被系统管理员关闭"))
                continue
            if not _has_menu_access(user, "export-center", menu_permissions):
                decisions.append(_deny(point, "缺少导出中心菜单权限"))
                continue
            decisions.append(_allow(point))
            continue

        if point in {"quiz.batch.reparse", "import.batch.submit", "import.task.export_failed"}:
            if user.role not in {"admin", "super_admin"}:
                decisions.append(_deny(point, "当前账号无管理权限"))
                continue
            if not _has_menu_access(user, "quiz-import", menu_permissions):
                decisions.append(_deny(point, "缺少导入案例菜单权限"))
                continue
            decisions.append(_allow(point))
            continue

        if point in {"quiz.update", "quiz.restore", "quiz.delete.soft"}:
            if user.role not in {"admin", "super_admin"}:
                decisions.append(_deny(point, "当前账号无管理权限"))
                continue
            if not _has_menu_access(user, "quiz-list", menu_permissions):
                decisions.append(_deny(point, "缺少案例管理菜单权限"))
                continue
            decisions.append(_allow(point))
            continue

        if point == "quiz.delete.hard":
            if user.role != "super_admin":
                decisions.append(_deny(point, "仅超级管理员可彻底删除案例"))
                continue
            if not _has_menu_access(user, "quiz-list", menu_permissions):
                decisions.append(_deny(point, "缺少案例管理菜单权限"))
                continue
            decisions.append(_allow(point))
            continue

        decisions.append(_deny(point, "未声明的权限点"))

    menu_decisions = _build_menu_access(
        user,
        enabled_modules=enabled_modules,
        menu_permissions=menu_permissions,
        export_enabled=export_enabled,
        audit_enabled=audit_enabled,
    )
    return decisions, menu_decisions
