from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PreviewCache

PREVIEW_TTL_HOURS = 24
LEGACY_PREVIEW_DIR = Path("/www/wwwroot/chattrainer/backend/uploads/previews")
LEGACY_PREVIEW_DIR.mkdir(parents=True, exist_ok=True)


async def save_preview(db: AsyncSession, preview_id: str, payload: dict[str, Any]) -> None:
    expires_at = datetime.now() + timedelta(hours=PREVIEW_TTL_HOURS)
    # Concurrent drag-upload may trigger transient InnoDB deadlocks.
    # Retry a few times to avoid surfacing random 500s to users.
    for attempt in range(3):
        try:
            db.add(PreviewCache(id=preview_id, data=payload, expires_at=expires_at))
            await db.commit()
            return
        except OperationalError as exc:
            await db.rollback()
            # MySQL deadlock error code 1213.
            if "1213" in str(exc) and attempt < 2:
                await asyncio.sleep(0.08 * (attempt + 1))
                continue
            raise


async def load_preview(db: AsyncSession, preview_id: str) -> dict[str, Any] | None:
    row = (await db.execute(select(PreviewCache).where(PreviewCache.id == preview_id))).scalars().first()
    if not row:
        return None
    if row.expires_at <= datetime.now():
        await db.delete(row)
        await db.commit()
        return None
    return row.data


async def delete_preview(db: AsyncSession, preview_id: str) -> None:
    await db.execute(delete(PreviewCache).where(PreviewCache.id == preview_id))


async def cleanup_expired_previews(db: AsyncSession) -> int:
    result = await db.execute(delete(PreviewCache).where(PreviewCache.expires_at <= datetime.now()))
    await db.commit()
    return int(result.rowcount or 0)
