from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_super_admin
from app.models import User
from app.services.permission_points import (
    ADMIN_CONFIGURABLE_MENU_KEYS,
    MENU_KEYS,
    _has_menu_access,
    _parse_menu_permissions,
    build_permission_context,
)

router = APIRouter()


def _classify_permission_mode(raw: str | None) -> str:
    if not raw:
        return "default_all"
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return "invalid_json"
    if not isinstance(parsed, list):
        return "invalid_json"
    return "custom"


def _build_user_audit_item(
    user: User,
    *,
    menu_permissions: list[str] | None,
    raw_menu_permissions: str | None,
) -> dict:
    mode = _classify_permission_mode(raw_menu_permissions)

    configurable_menu_audit: list[dict] = []
    for menu_key in sorted(ADMIN_CONFIGURABLE_MENU_KEYS):
        has_access = _has_menu_access(user, menu_key, menu_permissions)
        in_db = (menu_permissions is not None and menu_key in menu_permissions) if menu_permissions is not None else None
        compat = False
        if menu_key == "quiz-taxonomy" and menu_permissions is not None:
            if menu_key not in menu_permissions and "quiz-list" in menu_permissions:
                compat = True

        configurable_menu_audit.append({
            "menu_key": menu_key,
            "runtime_allowed": has_access,
            "in_db": in_db,
            "via_compat": compat,
        })

    issues: list[str] = []
    if mode == "invalid_json":
        issues.append("menu_permissions 字段 JSON 格式异常")

    if menu_permissions is not None:
        unknown_keys = [k for k in menu_permissions if k not in set(MENU_KEYS)]
        if unknown_keys:
            issues.append(f"包含未知菜单 key: {', '.join(unknown_keys)}")

    quiz_taxonomy_entry = next((e for e in configurable_menu_audit if e["menu_key"] == "quiz-taxonomy"), None)
    if quiz_taxonomy_entry and quiz_taxonomy_entry["via_compat"]:
        issues.append("quiz-taxonomy 通过兼容逻辑隐式获得（数据库中未显式写入）")

    return {
        "user_id": user.id,
        "username": user.username,
        "real_name": user.real_name,
        "role": user.role,
        "is_active": user.is_active,
        "permission_mode": mode,
        "raw_menu_permissions": raw_menu_permissions,
        "parsed_menu_permissions": menu_permissions,
        "configurable_menu_audit": configurable_menu_audit,
        "issues": issues,
        "issue_count": len(issues),
    }


@router.get("/permission-audit")
async def get_permission_audit(
    _admin: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(User).where(
        User.role.in_(["super_admin", "admin"]),
    ).order_by(User.role.asc(), User.id.asc())
    users = (await db.execute(stmt)).scalars().all()

    items: list[dict] = []
    summary = {
        "total": 0,
        "active": 0,
        "inactive": 0,
        "default_all": 0,
        "custom": 0,
        "invalid_json": 0,
        "has_issues": 0,
        "missing_quiz_taxonomy_explicit": 0,
    }

    for user in users:
        raw = user.menu_permissions
        parsed = _parse_menu_permissions(raw)
        item = _build_user_audit_item(
            user, menu_permissions=parsed, raw_menu_permissions=raw,
        )
        items.append(item)

        summary["total"] += 1
        if user.is_active:
            summary["active"] += 1
        else:
            summary["inactive"] += 1
        summary[item["permission_mode"]] = summary.get(item["permission_mode"], 0) + 1
        if item["issue_count"] > 0:
            summary["has_issues"] += 1

        qt_entry = next((e for e in item["configurable_menu_audit"] if e["menu_key"] == "quiz-taxonomy"), None)
        if qt_entry and qt_entry["via_compat"]:
            summary["missing_quiz_taxonomy_explicit"] += 1

    return {
        "code": 200,
        "message": "success",
        "data": {
            "summary": summary,
            "items": items,
            "all_configurable_menu_keys": sorted(ADMIN_CONFIGURABLE_MENU_KEYS),
            "all_menu_keys": list(MENU_KEYS),
        },
    }


@router.post("/permission-audit/fix")
async def fix_permission_audit(
    _admin: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(User).where(
        User.role.in_(["super_admin", "admin"]),
        User.is_active.is_(True),
    )
    users = (await db.execute(stmt)).scalars().all()

    fixed_users: list[dict] = []

    for user in users:
        raw = user.menu_permissions
        parsed = _parse_menu_permissions(raw)
        if parsed is None:
            continue
        if "quiz-list" not in parsed:
            continue
        if "quiz-taxonomy" in parsed:
            continue

        new_perms = [*parsed, "quiz-taxonomy"]
        user.menu_permissions = json.dumps(new_perms, ensure_ascii=False)
        fixed_users.append({
            "user_id": user.id,
            "username": user.username,
            "real_name": user.real_name,
            "added": "quiz-taxonomy",
        })

    if fixed_users:
        await db.commit()

    return {
        "code": 200,
        "message": f"已修复 {len(fixed_users)} 个账号" if fixed_users else "无需修复",
        "data": {
            "fixed_count": len(fixed_users),
            "fixed_users": fixed_users,
        },
    }
