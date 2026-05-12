from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models import User
from app.utils.security import hash_password


async def create_super_admin() -> None:
    async with SessionLocal() as db:
        stmt = select(User).where(User.username == settings.super_admin_username)
        existing = (await db.execute(stmt)).scalars().first()
        if existing:
            print(f"Super admin already exists: {existing.username}")
            return

        user = User(
            username=settings.super_admin_username,
            password_hash=hash_password(settings.super_admin_password),
            real_name="系统管理员",
            role="super_admin",
            is_active=True,
        )
        db.add(user)
        await db.commit()
        print(f"Super admin created: {user.username}")


if __name__ == "__main__":
    asyncio.run(create_super_admin())
