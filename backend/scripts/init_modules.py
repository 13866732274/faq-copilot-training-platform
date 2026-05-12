from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass

from app.database import SessionLocal
from app.services.module_registry import seed_default_tenant_modules, sync_module_definitions


@dataclass
class InitStats:
    definitions_created: int = 0
    definitions_updated: int = 0
    tenant_modules_created: int = 0
    tenant_modules_existing: int = 0


async def init_modules(*, dry_run: bool) -> InitStats:
    stats = InitStats()
    async with SessionLocal() as db:
        created, updated = await sync_module_definitions(db)
        stats.definitions_created = created
        stats.definitions_updated = updated

        tm_created, tm_existing = await seed_default_tenant_modules(db)
        stats.tenant_modules_created = tm_created
        stats.tenant_modules_existing = tm_existing

        if dry_run:
            await db.rollback()
        else:
            await db.commit()

    return stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="初始化 SaaS 模块定义和租户默认模块开通记录")
    parser.add_argument("--dry-run", action="store_true", help="仅预览结果，不写入数据库")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    stats = asyncio.run(init_modules(dry_run=bool(args.dry_run)))
    print("init_modules_done")
    print(f"mode={'dry-run' if args.dry_run else 'apply'}")
    print(f"definitions_created={stats.definitions_created}")
    print(f"definitions_updated={stats.definitions_updated}")
    print(f"tenant_modules_created={stats.tenant_modules_created}")
    print(f"tenant_modules_existing={stats.tenant_modules_existing}")


if __name__ == "__main__":
    main()

