from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass

from sqlalchemy import select

from app.database import SessionLocal
from app.models import User


TARGET_MENU = "quiz-taxonomy"
SOURCE_MENU = "quiz-list"


@dataclass
class BackfillStats:
    scanned: int = 0
    updated: int = 0
    skipped_no_permissions: int = 0
    skipped_no_source_menu: int = 0
    skipped_already_has_target: int = 0
    invalid_json: int = 0


def _normalize_menu_permissions(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, list):
        return None
    normalized: list[str] = []
    seen: set[str] = set()
    for item in parsed:
        if not isinstance(item, str):
            continue
        key = item.strip()
        if not key:
            continue
        if key in seen:
            continue
        seen.add(key)
        normalized.append(key)
    return normalized


async def backfill(*, dry_run: bool, include_super_admin: bool) -> BackfillStats:
    stats = BackfillStats()
    async with SessionLocal() as db:
        roles = ["admin", "super_admin"] if include_super_admin else ["admin"]
        users = (await db.execute(select(User).where(User.role.in_(roles), User.is_active.is_(True)))).scalars().all()

        for user in users:
            stats.scanned += 1
            if not user.menu_permissions:
                stats.skipped_no_permissions += 1
                continue
            menu_list = _normalize_menu_permissions(user.menu_permissions)
            if menu_list is None:
                stats.invalid_json += 1
                continue
            if SOURCE_MENU not in menu_list:
                stats.skipped_no_source_menu += 1
                continue
            if TARGET_MENU in menu_list:
                stats.skipped_already_has_target += 1
                continue
            next_permissions = [*menu_list, TARGET_MENU]
            user.menu_permissions = json.dumps(next_permissions, ensure_ascii=False)
            stats.updated += 1

        if dry_run:
            await db.rollback()
        else:
            await db.commit()
    return stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="一次性补齐 quiz-taxonomy 菜单权限（继承 quiz-list 权限账号）"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅预览结果，不写入数据库",
    )
    parser.add_argument(
        "--exclude-super-admin",
        action="store_true",
        help="仅处理 admin，不处理 super_admin",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    stats = asyncio.run(
        backfill(
            dry_run=bool(args.dry_run),
            include_super_admin=not bool(args.exclude_super_admin),
        )
    )
    print("backfill_quiz_taxonomy_menu_done")
    print(f"mode={'dry-run' if args.dry_run else 'apply'}")
    print(f"scanned={stats.scanned}")
    print(f"updated={stats.updated}")
    print(f"skipped_no_permissions={stats.skipped_no_permissions}")
    print(f"skipped_no_source_menu={stats.skipped_no_source_menu}")
    print(f"skipped_already_has_target={stats.skipped_already_has_target}")
    print(f"invalid_json={stats.invalid_json}")


if __name__ == "__main__":
    main()

