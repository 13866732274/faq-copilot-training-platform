"""Celery tasks for FAQ pipeline processing."""

from __future__ import annotations

import asyncio
import logging

from app.celery_app import celery_app

logger = logging.getLogger("chattrainer.tasks.faq")


def _run_async(coro):
    """Run an async coroutine in a new event loop (for Celery sync workers)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(
    name="faq.run_pipeline", bind=True, max_retries=2,
)
def celery_run_pipeline(self, task_id: int, tenant_id: int | None, quiz_ids: list[int] | None):
    """Celery task: run the full FAQ pipeline (priority=3)."""
    from app.database import SessionLocal
    from app.services.faq_pipeline import run_pipeline
    from sqlalchemy import select
    from app.models.faq_task import FaqTask

    async def _work():
        async with SessionLocal() as db:
            task = (await db.execute(select(FaqTask).where(FaqTask.id == task_id))).scalars().first()
            if not task:
                logger.warning("Task %d not found", task_id)
                return
            await run_pipeline(db, task, tenant_id, quiz_ids)

    logger.info("Celery: starting full pipeline task_id=%d (attempt %d)", task_id, self.request.retries + 1)
    _run_async(_work())
    logger.info("Celery: completed full pipeline task_id=%d", task_id)


@celery_app.task(
    name="faq.run_incremental", bind=True, max_retries=2,
)
def celery_run_incremental(self, task_id: int, tenant_id: int | None, quiz_ids: list[int]):
    """Celery task: run the incremental FAQ pipeline (priority=7, high queue)."""
    from app.database import SessionLocal
    from app.services.faq_pipeline import run_pipeline_incremental
    from sqlalchemy import select
    from app.models.faq_task import FaqTask

    async def _work():
        async with SessionLocal() as db:
            task = (await db.execute(select(FaqTask).where(FaqTask.id == task_id))).scalars().first()
            if not task:
                logger.warning("Task %d not found", task_id)
                return
            await run_pipeline_incremental(db, task, tenant_id, quiz_ids)

    logger.info("Celery: starting incremental pipeline task_id=%d quizzes=%d (attempt %d)", task_id, len(quiz_ids), self.request.retries + 1)
    _run_async(_work())
    logger.info("Celery: completed incremental pipeline task_id=%d", task_id)


@celery_app.task(
    name="faq.embed_batch", bind=True, max_retries=3,
    default_retry_delay=5, retry_backoff=True,
)
def celery_embed_batch(self, texts: list[str]) -> list[list[float]]:
    """Celery task: embed a batch of texts (distributable across workers)."""
    from app.services.faq_llm import get_embeddings

    try:
        result = _run_async(get_embeddings(texts))
        logger.info("Celery: embedded batch of %d texts", len(texts))
        return result
    except Exception as exc:
        logger.exception("Celery embed_batch failed (attempt %d), retrying", self.request.retries + 1)
        raise self.retry(exc=exc)
