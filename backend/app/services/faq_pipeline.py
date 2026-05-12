"""FAQ knowledge-base extraction pipeline.

Flow: conversations → extract Q&A → embed → cluster → LLM refine → store
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Message, Quiz
from app.models.faq_answer import FaqAnswer
from app.models.faq_cluster import FaqCluster
from app.models.faq_question import FaqQuestion
from app.models.faq_task import FaqTask
from app.services.faq_llm import (
    QAPair,
    extract_qa_pairs,
    get_embeddings,
    refine_cluster,
)

logger = logging.getLogger("chattrainer.faq_pipeline")

DEFAULT_SIMILARITY_THRESHOLD = 0.35
MIN_CLUSTER_SIZE = 1


async def _set_task_status(db: AsyncSession, task: FaqTask, status: str) -> None:
    """Set task status and update stage heartbeat time."""
    now = datetime.utcnow()
    if task.status != status:
        task.status = status
    task.stage_changed_at = now
    await db.commit()


async def _touch_task_heartbeat(db: AsyncSession, task: FaqTask) -> None:
    """Update task heartbeat while staying in the same stage."""
    task.stage_changed_at = datetime.utcnow()
    await db.commit()


@dataclass
class ExtractedPair:
    quiz_id: int
    tenant_id: int | None
    question: str
    raw_question: str
    answer: str
    question_msg_ids: list[int] = field(default_factory=list)
    answer_msg_ids: list[int] = field(default_factory=list)
    embedding: list[float] | None = None


def _resolve_msg_ids(
    seq_ids: list[int],
    seq_to_real: dict[int, int],
) -> list[int]:
    """Convert LLM-returned sequence numbers to real message IDs."""
    resolved = []
    for s in seq_ids:
        real_id = seq_to_real.get(s)
        if real_id is not None:
            resolved.append(real_id)
    return resolved


async def _load_conversations(
    db: AsyncSession,
    tenant_id: int | None,
    quiz_ids: list[int] | None = None,
) -> list[tuple[Quiz, list[dict], dict[int, int]]]:
    """Load quizzes and their messages.

    Returns (quiz, messages, seq_to_real_id) tuples.
    """
    filters = [Quiz.is_deleted.is_(False), Quiz.is_active.is_(True)]
    if tenant_id is not None:
        filters.append(Quiz.tenant_id == tenant_id)
    if quiz_ids:
        filters.append(Quiz.id.in_(quiz_ids))

    quizzes = (await db.execute(select(Quiz).where(*filters))).scalars().all()

    results: list[tuple[Quiz, list[dict], dict[int, int]]] = []
    for quiz in quizzes:
        msg_rows = (
            await db.execute(
                select(Message)
                .where(Message.quiz_id == quiz.id)
                .order_by(Message.sequence.asc())
            )
        ).scalars().all()

        seq_to_real: dict[int, int] = {}
        messages = []
        for m in msg_rows:
            seq_to_real[m.sequence] = m.id
            messages.append({
                "id": m.id,
                "sequence": m.sequence,
                "role": m.role,
                "content_type": m.content_type,
                "content": m.content,
                "sender_name": m.sender_name,
            })
        results.append((quiz, messages, seq_to_real))

    return results


async def step_extract(
    db: AsyncSession,
    task: FaqTask,
    tenant_id: int | None,
    quiz_ids: list[int] | None = None,
) -> list[ExtractedPair]:
    """Step 1: Extract Q&A pairs from conversations using LLM."""
    task.started_at = datetime.utcnow()
    await _set_task_status(db, task, "extracting")

    conversations = await _load_conversations(db, tenant_id, quiz_ids)
    task.total_quizzes = len(conversations)
    task.total_messages = sum(len(msgs) for _, msgs, _ in conversations)
    await db.commit()

    import asyncio

    EXTRACT_CONCURRENCY = 3
    all_pairs: list[ExtractedPair] = []
    last_touch_at = datetime.utcnow()

    non_empty = [(q, m, s) for q, m, s in conversations if m]

    for chunk_start in range(0, len(non_empty), EXTRACT_CONCURRENCY):
        chunk = non_empty[chunk_start : chunk_start + EXTRACT_CONCURRENCY]

        async def _extract_one(quiz: Quiz, messages: list[dict], seq_to_real: dict[int, int]) -> list[ExtractedPair]:
            try:
                qa_pairs: list[QAPair] = await extract_qa_pairs(messages)
                return [
                    ExtractedPair(
                        quiz_id=quiz.id,
                        tenant_id=quiz.tenant_id,
                        question=pair.question,
                        raw_question=pair.raw_question,
                        answer=pair.answer,
                        question_msg_ids=_resolve_msg_ids(pair.question_msg_ids, seq_to_real),
                        answer_msg_ids=_resolve_msg_ids(pair.answer_msg_ids, seq_to_real),
                    )
                    for pair in qa_pairs
                ]
            except Exception:
                logger.exception("Failed to extract from quiz %d", quiz.id)
                return []

        results = await asyncio.gather(*[_extract_one(q, m, s) for q, m, s in chunk])
        for pairs_list in results:
            all_pairs.extend(pairs_list)

        now = datetime.utcnow()
        if (now - last_touch_at).total_seconds() >= 30:
            await _touch_task_heartbeat(db, task)
            last_touch_at = now

    task.extracted_pairs = len(all_pairs)
    await db.commit()
    logger.info("Extracted %d Q&A pairs from %d conversations", len(all_pairs), len(conversations))
    return all_pairs


def _try_distributed_embed(texts: list[str], chunk_size: int = 30) -> list[list[float]] | None:
    """Try to embed via Celery workers. Returns None if Celery unavailable."""
    try:
        from celery import group
        from app.tasks.faq_tasks import celery_embed_batch

        chunks = [texts[i:i + chunk_size] for i in range(0, len(texts), chunk_size)]
        if len(chunks) <= 1:
            return None

        job = group(celery_embed_batch.s(c) for c in chunks)
        result = job.apply_async()
        all_results = result.get(timeout=300)
        merged: list[list[float]] = []
        for batch_result in all_results:
            merged.extend(batch_result)
        logger.info("Distributed embedding: %d texts in %d chunks", len(texts), len(chunks))
        return merged
    except Exception:
        logger.debug("Distributed embedding unavailable, falling back to local")
        return None


async def step_embed(
    db: AsyncSession,
    task: FaqTask,
    pairs: list[ExtractedPair],
) -> list[ExtractedPair]:
    """Step 2: Get embeddings for all extracted questions.

    Tries distributed Celery embedding for large batches, falls back to local.
    """
    await _set_task_status(db, task, "embedding")

    if not pairs:
        return pairs

    questions = [p.question for p in pairs]

    embeddings = None
    if len(questions) >= 50:
        import asyncio
        embeddings = await asyncio.get_event_loop().run_in_executor(
            None, _try_distributed_embed, questions,
        )

    if embeddings is None:
        embeddings = await get_embeddings(questions)

    for pair, emb in zip(pairs, embeddings):
        pair.embedding = emb

    logger.info("Embedded %d questions", len(pairs))
    return pairs


def step_cluster(
    pairs: list[ExtractedPair],
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> list[list[int]]:
    """Step 3: Cluster similar questions using agglomerative clustering.

    Returns list of clusters, each cluster is a list of pair indices.
    """
    if len(pairs) <= 1:
        return [[i] for i in range(len(pairs))]

    embeddings = []
    for p in pairs:
        if p.embedding:
            embeddings.append(p.embedding)
        else:
            embeddings.append([0.0] * 1024)

    X = np.array(embeddings, dtype=np.float32)
    norms = np.linalg.norm(X, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    X_norm = X / norms

    clustering = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=similarity_threshold,
        metric="cosine",
        linkage="average",
    )
    labels = clustering.fit_predict(X_norm)

    cluster_map: dict[int, list[int]] = {}
    for idx, label in enumerate(labels):
        cluster_map.setdefault(int(label), []).append(idx)

    return list(cluster_map.values())


async def _clean_previous_faq_data(
    db: AsyncSession,
    tenant_id: int | None,
) -> int:
    """Remove existing unlocked FAQ data for this tenant before a fresh run.

    Locked clusters (manually curated) are preserved.
    Returns the number of preserved (locked) clusters.
    """
    filters_cluster = [FaqCluster.is_locked.is_(False)]
    if tenant_id is not None:
        filters_cluster.append(FaqCluster.tenant_id == tenant_id)

    unlocked_ids_q = select(FaqCluster.id).where(*filters_cluster)
    await db.execute(delete(FaqAnswer).where(FaqAnswer.cluster_id.in_(unlocked_ids_q)))
    await db.execute(delete(FaqQuestion).where(FaqQuestion.cluster_id.in_(unlocked_ids_q)))
    await db.execute(delete(FaqCluster).where(*filters_cluster))

    locked_filters = [FaqCluster.is_locked.is_(True)]
    if tenant_id is not None:
        locked_filters.append(FaqCluster.tenant_id == tenant_id)
    preserved = (
        await db.execute(select(func.count(FaqCluster.id)).where(*locked_filters))
    ).scalar() or 0

    await db.commit()
    logger.info(
        "Cleaned previous FAQ data for tenant=%s (preserved %d locked clusters)",
        tenant_id,
        preserved,
    )
    return preserved


async def step_refine_and_store(
    db: AsyncSession,
    task: FaqTask,
    pairs: list[ExtractedPair],
    cluster_indices: list[list[int]],
    tenant_id: int | None,
) -> None:
    """Step 4: LLM refine each cluster, then store in DB (per-cluster commit)."""
    await _set_task_status(db, task, "refining")
    preserved = await _clean_previous_faq_data(db, tenant_id)
    if preserved:
        logger.info("Preserved %d locked clusters", preserved)

    created = 0
    skipped = 0
    last_touch_at = datetime.utcnow()
    total_clusters = len(cluster_indices)

    for ci, indices in enumerate(cluster_indices):
        try:
            questions = [pairs[i].question for i in indices]
            answers = [pairs[i].answer for i in indices]

            refinement = await refine_cluster(questions, answers)

            centroid_emb = None
            emb_list = [pairs[i].embedding for i in indices if pairs[i].embedding]
            if emb_list:
                centroid = np.mean(np.array(emb_list, dtype=np.float32), axis=0)
                centroid_emb = centroid.tolist()

            cluster = FaqCluster(
                tenant_id=tenant_id,
                title=refinement.title or questions[0][:100],
                summary=refinement.summary,
                category=refinement.category,
                representative_question=refinement.representative_question or questions[0],
                best_answer=refinement.best_answer or answers[0] if answers else "",
                embedding_json=json.dumps(centroid_emb) if centroid_emb else None,
                question_count=len(indices),
                answer_count=len(indices),
            )
            db.add(cluster)
            await db.flush()

            for rank, pair_idx in enumerate(indices):
                pair = pairs[pair_idx]

                q_msg_id = pair.question_msg_ids[0] if pair.question_msg_ids else None
                faq_q = FaqQuestion(
                    tenant_id=pair.tenant_id,
                    cluster_id=cluster.id,
                    quiz_id=pair.quiz_id,
                    message_id=q_msg_id,
                    content=pair.question,
                    embedding_json=json.dumps(pair.embedding) if pair.embedding else None,
                    similarity_score=1.0 if rank == 0 else 0.0,
                    is_representative=(pair.question == refinement.representative_question),
                    source_context=pair.raw_question,
                )
                db.add(faq_q)

                quality_score = 0.5
                if refinement.answer_quality_scores and rank < len(refinement.answer_quality_scores):
                    quality_score = refinement.answer_quality_scores[rank]

                a_msg_id = pair.answer_msg_ids[0] if pair.answer_msg_ids else None
                faq_a = FaqAnswer(
                    tenant_id=pair.tenant_id,
                    cluster_id=cluster.id,
                    quiz_id=pair.quiz_id,
                    message_id=a_msg_id,
                    content=pair.answer,
                    quality_score=quality_score,
                    is_best=(rank == 0 and quality_score >= 0.7),
                    source_context=pair.raw_question,
                )
                db.add(faq_a)

            await db.commit()
            created += 1
            logger.info("Cluster %d/%d saved (%d pairs)", ci + 1, total_clusters, len(indices))

        except Exception:
            logger.exception("Failed to save cluster %d/%d, rolling back", ci + 1, total_clusters)
            await db.rollback()
            skipped += 1

        now = datetime.utcnow()
        if (now - last_touch_at).total_seconds() >= 30:
            await _touch_task_heartbeat(db, task)
            last_touch_at = now

    task.clusters_created = created
    await db.commit()
    logger.info("Refine complete: created=%d skipped=%d total=%d", created, skipped, total_clusters)


async def _load_similarity_threshold(db: AsyncSession, tenant_id: int | None) -> float:
    """Load clustering threshold from system settings."""
    from app.models.system_setting import SystemSetting
    if tenant_id is None:
        return DEFAULT_SIMILARITY_THRESHOLD
    row = (
        await db.execute(
            select(SystemSetting.faq_similarity_threshold)
            .where(SystemSetting.tenant_id == tenant_id)
            .limit(1)
        )
    ).scalar()
    if row is not None and 0.1 <= float(row) <= 0.9:
        return float(row)
    return DEFAULT_SIMILARITY_THRESHOLD


async def run_pipeline(
    db: AsyncSession,
    task: FaqTask,
    tenant_id: int | None,
    quiz_ids: list[int] | None = None,
) -> None:
    """Execute the full FAQ extraction pipeline."""
    import time

    task_id = task.id
    durations: dict[str, float] = {}

    try:
        sim_threshold = await _load_similarity_threshold(db, tenant_id)
        logger.info("Using similarity_threshold=%.3f for task=%d", sim_threshold, task_id)

        t0 = time.monotonic()
        pairs = await step_extract(db, task, tenant_id, quiz_ids)
        durations["extracting"] = round(time.monotonic() - t0, 2)

        if not pairs:
            task.status = "completed"
            task.stage_changed_at = datetime.utcnow()
            task.finished_at = datetime.utcnow()
            task.stage_durations_json = json.dumps(durations)
            await db.commit()
            logger.info("FAQ pipeline completed (no pairs): task=%d", task_id)
            return

        t0 = time.monotonic()
        pairs = await step_embed(db, task, pairs)
        durations["embedding"] = round(time.monotonic() - t0, 2)

        t0 = time.monotonic()
        await _set_task_status(db, task, "clustering")
        cluster_indices = step_cluster(pairs, similarity_threshold=sim_threshold)
        durations["clustering"] = round(time.monotonic() - t0, 2)

        t0 = time.monotonic()
        await step_refine_and_store(db, task, pairs, cluster_indices, tenant_id)
        durations["refining"] = round(time.monotonic() - t0, 2)

        task.status = "completed"
        task.stage_changed_at = datetime.utcnow()
        task.finished_at = datetime.utcnow()
        task.stage_durations_json = json.dumps(durations)
        await db.commit()
        logger.info(
            "FAQ pipeline completed: task=%d clusters=%d durations=%s",
            task_id, task.clusters_created, durations,
        )

    except Exception as e:
        logger.exception("FAQ pipeline failed: task=%d", task_id)
        try:
            await db.rollback()
            task.status = "failed"
            task.stage_changed_at = datetime.utcnow()
            task.error_message = f"{type(e).__name__}: {str(e)[:500]}"
            task.finished_at = datetime.utcnow()
            task.stage_durations_json = json.dumps(durations) if durations else None
            await db.commit()
        except Exception:
            logger.exception("Failed to update task status after error: task=%d", task_id)


MERGE_SIMILARITY_THRESHOLD = 0.82


async def _load_existing_cluster_embeddings(
    db: AsyncSession,
    tenant_id: int | None,
) -> list[tuple[int, np.ndarray]]:
    """Load all existing cluster embeddings for merge matching."""
    filters = [FaqCluster.is_active.is_(True), FaqCluster.embedding_json.isnot(None)]
    if tenant_id is not None:
        filters.append(FaqCluster.tenant_id == tenant_id)

    rows = (await db.execute(
        select(FaqCluster.id, FaqCluster.embedding_json).where(*filters)
    )).all()

    result: list[tuple[int, np.ndarray]] = []
    for cid, emb_json in rows:
        try:
            vec = np.array(json.loads(emb_json), dtype=np.float32)
            norm = np.linalg.norm(vec)
            if norm > 0:
                result.append((cid, vec / norm))
        except (json.JSONDecodeError, TypeError):
            continue
    return result


def _find_best_merge_target(
    centroid: np.ndarray,
    existing: list[tuple[int, np.ndarray]],
    threshold: float = MERGE_SIMILARITY_THRESHOLD,
) -> int | None:
    """Find the most similar existing cluster above threshold."""
    if not existing:
        return None
    norm = np.linalg.norm(centroid)
    if norm == 0:
        return None
    centroid_normed = centroid / norm

    best_sim = -1.0
    best_id: int | None = None
    for cid, evec in existing:
        sim = float(np.dot(centroid_normed, evec))
        if sim > best_sim:
            best_sim = sim
            best_id = cid

    if best_sim >= threshold and best_id is not None:
        return best_id
    return None


async def _merge_into_existing_cluster(
    db: AsyncSession,
    cluster_id: int,
    pairs: list[ExtractedPair],
    indices: list[int],
    new_centroid: np.ndarray,
) -> None:
    """Merge new Q&A pairs into an existing cluster and update its centroid."""
    cluster = (await db.execute(
        select(FaqCluster).where(FaqCluster.id == cluster_id)
    )).scalars().first()
    if not cluster:
        return

    for rank, pair_idx in enumerate(indices):
        pair = pairs[pair_idx]
        q_msg_id = pair.question_msg_ids[0] if pair.question_msg_ids else None
        faq_q = FaqQuestion(
            tenant_id=pair.tenant_id,
            cluster_id=cluster_id,
            quiz_id=pair.quiz_id,
            message_id=q_msg_id,
            content=pair.question,
            embedding_json=json.dumps(pair.embedding) if pair.embedding else None,
            similarity_score=0.0,
            is_representative=False,
            source_context=pair.raw_question,
        )
        db.add(faq_q)

        quality_score = 0.5
        a_msg_id = pair.answer_msg_ids[0] if pair.answer_msg_ids else None
        faq_a = FaqAnswer(
            tenant_id=pair.tenant_id,
            cluster_id=cluster_id,
            quiz_id=pair.quiz_id,
            message_id=a_msg_id,
            content=pair.answer,
            quality_score=quality_score,
            is_best=False,
            source_context=pair.raw_question,
        )
        db.add(faq_a)

    cluster.question_count = cluster.question_count + len(indices)
    cluster.answer_count = cluster.answer_count + len(indices)

    if cluster.embedding_json:
        try:
            old_emb = np.array(json.loads(cluster.embedding_json), dtype=np.float32)
            merged_emb = (old_emb + new_centroid) / 2.0
            cluster.embedding_json = json.dumps(merged_emb.tolist())
        except (json.JSONDecodeError, TypeError):
            pass

    await db.commit()


async def _step_refine_and_store_incremental(
    db: AsyncSession,
    task: FaqTask,
    pairs: list[ExtractedPair],
    cluster_indices: list[list[int]],
    tenant_id: int | None,
) -> None:
    """Incremental: merge into existing clusters when similar, otherwise create new."""
    await _set_task_status(db, task, "refining")

    existing_embeddings = await _load_existing_cluster_embeddings(db, tenant_id)
    logger.info("Loaded %d existing cluster embeddings for merge matching", len(existing_embeddings))

    created = 0
    merged = 0
    skipped = 0
    last_touch_at = datetime.utcnow()
    total_clusters = len(cluster_indices)

    for ci, indices in enumerate(cluster_indices):
        try:
            centroid_emb = None
            emb_list = [pairs[i].embedding for i in indices if pairs[i].embedding]
            if emb_list:
                centroid = np.mean(np.array(emb_list, dtype=np.float32), axis=0)
                centroid_emb = centroid.tolist()

            merge_target = None
            if centroid_emb is not None:
                merge_target = _find_best_merge_target(
                    np.array(centroid_emb, dtype=np.float32),
                    existing_embeddings,
                )

            if merge_target is not None:
                await _merge_into_existing_cluster(
                    db, merge_target, pairs, indices,
                    np.array(centroid_emb, dtype=np.float32),
                )
                merged += 1
                logger.info(
                    "Incremental cluster %d/%d merged into existing #%d (%d pairs)",
                    ci + 1, total_clusters, merge_target, len(indices),
                )
            else:
                questions = [pairs[i].question for i in indices]
                answers = [pairs[i].answer for i in indices]

                refinement = await refine_cluster(questions, answers)

                cluster = FaqCluster(
                    tenant_id=tenant_id,
                    title=refinement.title or questions[0][:100],
                    summary=refinement.summary,
                    category=refinement.category,
                    representative_question=refinement.representative_question or questions[0],
                    best_answer=refinement.best_answer or answers[0] if answers else "",
                    embedding_json=json.dumps(centroid_emb) if centroid_emb else None,
                    question_count=len(indices),
                    answer_count=len(indices),
                )
                db.add(cluster)
                await db.flush()

                for rank, pair_idx in enumerate(indices):
                    pair = pairs[pair_idx]

                    q_msg_id = pair.question_msg_ids[0] if pair.question_msg_ids else None
                    faq_q = FaqQuestion(
                        tenant_id=pair.tenant_id,
                        cluster_id=cluster.id,
                        quiz_id=pair.quiz_id,
                        message_id=q_msg_id,
                        content=pair.question,
                        embedding_json=json.dumps(pair.embedding) if pair.embedding else None,
                        similarity_score=1.0 if rank == 0 else 0.0,
                        is_representative=(pair.question == refinement.representative_question),
                        source_context=pair.raw_question,
                    )
                    db.add(faq_q)

                    quality_score = 0.5
                    if refinement.answer_quality_scores and rank < len(refinement.answer_quality_scores):
                        quality_score = refinement.answer_quality_scores[rank]

                    a_msg_id = pair.answer_msg_ids[0] if pair.answer_msg_ids else None
                    faq_a = FaqAnswer(
                        tenant_id=pair.tenant_id,
                        cluster_id=cluster.id,
                        quiz_id=pair.quiz_id,
                        message_id=a_msg_id,
                        content=pair.answer,
                        quality_score=quality_score,
                        is_best=(rank == 0 and quality_score >= 0.7),
                        source_context=pair.raw_question,
                    )
                    db.add(faq_a)

                await db.commit()
                created += 1

                if centroid_emb is not None:
                    vec = np.array(centroid_emb, dtype=np.float32)
                    norm = np.linalg.norm(vec)
                    if norm > 0:
                        existing_embeddings.append((cluster.id, vec / norm))

                logger.info("Incremental cluster %d/%d created (%d pairs)", ci + 1, total_clusters, len(indices))

        except Exception:
            logger.exception("Failed to save incremental cluster %d/%d", ci + 1, total_clusters)
            await db.rollback()
            skipped += 1

        now = datetime.utcnow()
        if (now - last_touch_at).total_seconds() >= 30:
            await _touch_task_heartbeat(db, task)
            last_touch_at = now

    task.clusters_created = created
    await db.commit()
    logger.info(
        "Incremental refine complete: created=%d merged=%d skipped=%d total=%d",
        created, merged, skipped, total_clusters,
    )


async def run_pipeline_incremental(
    db: AsyncSession,
    task: FaqTask,
    tenant_id: int | None,
    quiz_ids: list[int],
) -> None:
    """Incremental pipeline: process only specified quizzes, append to existing FAQ."""
    import time

    task_id = task.id
    durations: dict[str, float] = {}

    try:
        sim_threshold = await _load_similarity_threshold(db, tenant_id)
        logger.info(
            "Incremental pipeline: task=%d quizzes=%d threshold=%.3f",
            task_id, len(quiz_ids), sim_threshold,
        )

        t0 = time.monotonic()
        pairs = await step_extract(db, task, tenant_id, quiz_ids)
        durations["extracting"] = round(time.monotonic() - t0, 2)

        if not pairs:
            task.status = "completed"
            task.stage_changed_at = datetime.utcnow()
            task.finished_at = datetime.utcnow()
            task.stage_durations_json = json.dumps(durations)
            await db.commit()
            logger.info("Incremental pipeline completed (no pairs): task=%d", task_id)
            return

        t0 = time.monotonic()
        pairs = await step_embed(db, task, pairs)
        durations["embedding"] = round(time.monotonic() - t0, 2)

        t0 = time.monotonic()
        await _set_task_status(db, task, "clustering")
        cluster_indices = step_cluster(pairs, similarity_threshold=sim_threshold)
        durations["clustering"] = round(time.monotonic() - t0, 2)

        t0 = time.monotonic()
        await _step_refine_and_store_incremental(db, task, pairs, cluster_indices, tenant_id)
        durations["refining"] = round(time.monotonic() - t0, 2)

        task.status = "completed"
        task.stage_changed_at = datetime.utcnow()
        task.finished_at = datetime.utcnow()
        task.stage_durations_json = json.dumps(durations)
        await db.commit()
        logger.info(
            "Incremental pipeline completed: task=%d clusters=%d durations=%s",
            task_id, task.clusters_created, durations,
        )

    except Exception as e:
        logger.exception("Incremental pipeline failed: task=%d", task_id)
        try:
            await db.rollback()
            task.status = "failed"
            task.stage_changed_at = datetime.utcnow()
            task.error_message = f"{type(e).__name__}: {str(e)[:500]}"
            task.finished_at = datetime.utcnow()
            task.stage_durations_json = json.dumps(durations) if durations else None
            await db.commit()
        except Exception:
            logger.exception("Failed to update task status: task=%d", task_id)


async def semantic_search(
    db: AsyncSession,
    query_embedding: list[float],
    tenant_id: int | None,
    top_k: int = 5,
) -> list[dict]:
    """Search FAQ clusters by cosine similarity to query embedding."""
    filters = [FaqCluster.is_active.is_(True)]
    if tenant_id is not None:
        filters.append(FaqCluster.tenant_id == tenant_id)

    clusters = (
        await db.execute(
            select(FaqCluster).where(*filters, FaqCluster.embedding_json.isnot(None))
        )
    ).scalars().all()

    if not clusters:
        return []

    query_vec = np.array(query_embedding, dtype=np.float32)
    query_norm = np.linalg.norm(query_vec)
    if query_norm == 0:
        return []
    query_vec = query_vec / query_norm

    scored: list[tuple[float, FaqCluster]] = []
    for cluster in clusters:
        try:
            emb = json.loads(cluster.embedding_json)
            cluster_vec = np.array(emb, dtype=np.float32)
            c_norm = np.linalg.norm(cluster_vec)
            if c_norm == 0:
                continue
            cluster_vec = cluster_vec / c_norm
            similarity = float(np.dot(query_vec, cluster_vec))
            scored.append((similarity, cluster))
        except (json.JSONDecodeError, TypeError):
            continue

    scored.sort(key=lambda x: x[0], reverse=True)

    results: list[dict] = []
    for sim, cluster in scored[:top_k]:
        results.append({
            "cluster_id": cluster.id,
            "title": cluster.title,
            "summary": cluster.summary,
            "category": cluster.category,
            "representative_question": cluster.representative_question,
            "best_answer": cluster.best_answer,
            "question_count": cluster.question_count,
            "answer_count": cluster.answer_count,
            "similarity": round(sim, 4),
        })

    return results
