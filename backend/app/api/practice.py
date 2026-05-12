from __future__ import annotations

from datetime import datetime, timedelta
import json
import random
import re
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.dependencies import (
    ensure_tenant_bound,
    get_accessible_department_ids,
    get_accessible_hospital_ids,
    get_current_user,
    require_module,
)
from app.models import Department, Hospital, Message, Practice, PracticeComment, PracticeReply, Quiz, SystemSetting, User
from app.models.faq_cluster import FaqCluster
from app.models.faq_copilot_log import FaqCopilotLog
from app.services.faq_llm import copilot_answer, get_single_embedding
from app.services.faq_pipeline import semantic_search
from app.services.llm_scoring import fuse_scores, run_llm_audit
from app.services.module_registry import is_module_enabled
from app.schemas.practice import (
    ApiResponse,
    CompleteData,
    NextData,
    PracticeAvailableFilterOptionsData,
    PracticeAvailableItem,
    PracticeAvailablePageData,
    PracticeDashboardData,
    PracticeDashboardContinueItem,
    PracticeDashboardHeatmapItem,
    PracticeDashboardRecentItem,
    PracticeFilterOptionItem,
    PracticeFaqClusterItem,
    PracticeFaqClusterListData,
    PracticeHistoryData,
    PracticeAiScoreData,
    PracticeFaqCopilotData,
    PracticeFaqSearchData,
    PracticeMessage,
    PracticeRandomStartRequest,
    PracticeStartData,
    PracticeStartRequest,
    ReplyData,
    ReplyRequest,
    ReviewData,
    ReviewDialogue,
)

router = APIRouter()

_PRACTICE_FAQ_RISK_KEYWORDS = ("费用", "价格", "医保", "报销", "疗程", "手术", "住院")


def _resolve_practice_quality_mode(query_text: str, requested_mode: str) -> tuple[str, str]:
    mode = (requested_mode or "auto").strip().lower()
    if mode in {"fast", "balanced", "quality"}:
        return mode, f"manual:{mode}"
    text = (query_text or "").strip()
    if len(text) <= 4:
        return "fast", "auto:short_query"
    if any(kw in text for kw in _PRACTICE_FAQ_RISK_KEYWORDS):
        return "quality", "auto:risk_keyword"
    return "balanced", "auto:default_balanced"


async def _ensure_faq_module_enabled(db: AsyncSession, tenant_id: int) -> None:
    if not await is_module_enabled(db, tenant_id, "mod_faq"):
        raise HTTPException(status_code=403, detail="FAQ 模块未启用")


def _split_tags(tags_text: str | None) -> list[str]:
    raw = (tags_text or "").replace("，", ",")
    items = [item.strip() for item in raw.split(",")]
    unique: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _fmt_message(m: Message) -> PracticeMessage:
    return PracticeMessage(
        id=m.id,
        role=m.role,
        content_type=m.content_type,
        content=m.content,
        sender_name=m.sender_name,
        original_time=m.original_time.strftime("%Y-%m-%d %H:%M:%S") if m.original_time else None,
    )


async def _get_ordered_messages(db: AsyncSession, quiz_id: int, tenant_id: int) -> list[Message]:
    stmt = (
        select(Message)
        .where(Message.quiz_id == quiz_id, Message.tenant_id == tenant_id)
        .order_by(Message.sequence.asc(), Message.id.asc())
    )
    return (await db.execute(stmt)).scalars().all()


async def _get_practice_or_404(db: AsyncSession, practice_id: int, user_id: int, tenant_id: int) -> Practice:
    stmt = select(Practice).where(
        Practice.id == practice_id,
        Practice.user_id == user_id,
        Practice.tenant_id == tenant_id,
    )
    practice = (await db.execute(stmt)).scalars().first()
    if not practice:
        raise HTTPException(status_code=404, detail="训练记录不存在")
    return practice


async def _query_available_quizzes(
    db: AsyncSession,
    current_user: User,
    *,
    chat_type: str | None = None,
    keyword: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
) -> list[Quiz]:
    tenant_id = ensure_tenant_bound(current_user)
    hospital_ids = await get_accessible_hospital_ids(current_user, db)
    department_ids = await get_accessible_department_ids(current_user, db)
    if current_user.role == "student":
        if current_user.department_id:
            department_ids = [current_user.department_id]
        elif current_user.hospital_id:
            hospital_ids = [current_user.hospital_id]
    filters = [Quiz.is_deleted.is_(False), Quiz.is_active.is_(True), Quiz.tenant_id == tenant_id]
    if chat_type:
        filters.append(Quiz.chat_type == chat_type)
    if keyword:
        filters.append(Quiz.title.like(f"%{keyword}%"))
    if category:
        filters.append(Quiz.category == category)
    if tag:
        filters.append(Quiz.tags.like(f"%{tag}%"))
    if current_user.role == "super_admin" or current_user.is_all_hospitals:
        filters.append((Quiz.scope == "common") | (Quiz.hospital_id.is_not(None)))
    else:
        filters.append(
            (Quiz.scope == "common")
            | (Quiz.department_id.in_(department_ids))
            | (Quiz.hospital_id.in_(hospital_ids))
        )
    stmt = select(Quiz).where(*filters).order_by(Quiz.id.desc())
    if page is not None and page_size is not None:
        stmt = stmt.offset((max(page, 1) - 1) * page_size).limit(page_size)
    return (await db.execute(stmt)).scalars().all()


async def _count_available_quizzes(
    db: AsyncSession,
    current_user: User,
    *,
    chat_type: str | None = None,
    keyword: str | None = None,
    category: str | None = None,
    tag: str | None = None,
) -> int:
    tenant_id = ensure_tenant_bound(current_user)
    hospital_ids = await get_accessible_hospital_ids(current_user, db)
    department_ids = await get_accessible_department_ids(current_user, db)
    if current_user.role == "student":
        if current_user.department_id:
            department_ids = [current_user.department_id]
        elif current_user.hospital_id:
            hospital_ids = [current_user.hospital_id]
    filters = [Quiz.is_deleted.is_(False), Quiz.is_active.is_(True), Quiz.tenant_id == tenant_id]
    if chat_type:
        filters.append(Quiz.chat_type == chat_type)
    if keyword:
        filters.append(Quiz.title.like(f"%{keyword}%"))
    if category:
        filters.append(Quiz.category == category)
    if tag:
        filters.append(Quiz.tags.like(f"%{tag}%"))
    if current_user.role == "super_admin" or current_user.is_all_hospitals:
        filters.append((Quiz.scope == "common") | (Quiz.hospital_id.is_not(None)))
    else:
        filters.append(
            (Quiz.scope == "common")
            | (Quiz.department_id.in_(department_ids))
            | (Quiz.hospital_id.in_(hospital_ids))
        )
    return int((await db.execute(select(func.count(Quiz.id)).where(*filters))).scalar_one() or 0)


async def _is_ai_scoring_enabled(db: AsyncSession, tenant_id: int) -> bool:
    enabled = (
        await db.execute(
            select(SystemSetting.enable_ai_scoring)
            .where(SystemSetting.tenant_id == tenant_id)
            .order_by(SystemSetting.id.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return bool(enabled) if enabled is not None else False


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").strip().lower())


def _char_ngrams(text: str, n: int = 2) -> set[str]:
    raw = _normalize_text(text)
    if not raw:
        return set()
    if len(raw) <= n:
        return {raw}
    return {raw[i : i + n] for i in range(0, len(raw) - n + 1)}


def _extract_keywords(text: str) -> set[str]:
    raw = _normalize_text(text)
    if not raw:
        return set()
    terms = set(re.findall(r"[\u4e00-\u9fff]{2,6}|[a-z0-9]{3,}", raw))
    stopwords = {
        "我们",
        "你们",
        "这个",
        "那个",
        "可以",
        "需要",
        "进行",
        "然后",
        "如果",
        "已经",
        "一下",
        "是否",
        "因为",
        "所以",
        "建议",
    }
    return {item for item in terms if item not in stopwords}


def _keyword_recall(reply_text: str, target_keywords: set[str]) -> float:
    if not target_keywords:
        return 0.0
    hit = sum(1 for kw in target_keywords if kw in reply_text)
    return hit / len(target_keywords)


def _text_similarity(reply: str, standard: str) -> float:
    reply_text = _normalize_text(reply)
    standard_text = _normalize_text(standard)
    if not reply_text or not standard_text:
        return 0.0
    grams_reply = _char_ngrams(reply_text, 2)
    grams_std = _char_ngrams(standard_text, 2)
    union = grams_reply | grams_std
    jaccard = (len(grams_reply & grams_std) / len(union)) if union else 0.0
    std_keywords = _extract_keywords(standard_text)
    keyword_recall = _keyword_recall(reply_text, std_keywords) if std_keywords else 0.0
    length_ratio = min(len(reply_text) / max(len(standard_text), 1), 1.0)
    return max(0.0, min(1.0, 0.55 * jaccard + 0.30 * keyword_recall + 0.15 * length_ratio))


def _build_counselor_rounds(messages: list[Message]) -> list[dict]:
    rounds: list[dict] = []
    idx = 0
    while idx < len(messages):
        while idx < len(messages) and messages[idx].role == "patient":
            idx += 1
        counselor_batch: list[Message] = []
        while idx < len(messages) and messages[idx].role == "counselor":
            counselor_batch.append(messages[idx])
            idx += 1
        if not counselor_batch:
            continue
        rounds.append(
            {
                "first_message_id": int(counselor_batch[0].id),
                "standards": [m.content for m in counselor_batch if (m.content or "").strip()],
            }
        )
    return rounds


def _score_communication_quality(reply_text: str) -> tuple[float, bool]:
    text = _normalize_text(reply_text)
    if not text:
        return 0.0, False
    empathy_markers = ("理解", "辛苦", "感谢", "我明白", "不容易", "先别着急", "一起")
    action_markers = ("建议", "可以", "请", "先", "然后", "安排", "观察", "复诊", "记录", "反馈")
    structure_markers = ("先", "再", "然后", "最后", "第一", "第二")
    empathy_hit = any(item in text for item in empathy_markers)
    action_hit = any(item in text for item in action_markers)
    structure_hit = any(item in text for item in structure_markers)
    clarity_hit = "。" in reply_text or "；" in reply_text or "，" in reply_text
    score = 0.0
    score += 42.0 if empathy_hit else 0.0
    score += 33.0 if action_hit else 0.0
    score += 15.0 if structure_hit else 0.0
    score += 10.0 if clarity_hit else 0.0
    return min(score, 100.0), empathy_hit


def _score_risk_control(reply_texts: list[str]) -> tuple[float, list[str]]:
    risky_rules = [
        ("保证", 12, "出现绝对承诺“保证”，建议改为条件化表达。"),
        ("一定会", 10, "出现绝对承诺“一定会”，存在误导风险。"),
        ("绝对", 10, "出现绝对化措辞“绝对”，建议使用概率表达。"),
        ("百分之百", 12, "出现“百分之百”表述，需避免医疗沟通中的绝对化承诺。"),
        ("必须", 6, "使用“必须”可能引发对抗情绪，建议柔化语气。"),
        ("不用管", 10, "出现“无需处理”类表达，可能存在风险。"),
        ("没事", 6, "对风险场景直接“没事”可能弱化风险提示。"),
    ]
    score = 100.0
    reasons: list[str] = []
    for text in reply_texts:
        normalized = _normalize_text(text)
        if len(normalized) < 6:
            score -= 5
            reasons.append("存在过短回复（<6字），建议补充评估依据和行动建议。")
        for keyword, penalty, reason in risky_rules:
            if keyword in normalized:
                score -= penalty
                reasons.append(reason)
    if not reply_texts:
        reasons.append("未检测到有效回复，风险控制维度无法评估。")
    unique_reasons = list(dict.fromkeys(reasons))
    return max(0.0, min(100.0, score)), unique_reasons


@router.get("/available", response_model=ApiResponse)
async def get_available_quizzes(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    chat_type: str | None = Query(default=None, pattern="^(active|passive)$"),
    keyword: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
) -> ApiResponse:
    total = await _count_available_quizzes(
        db,
        current_user,
        chat_type=chat_type,
        keyword=keyword,
        category=category,
        tag=tag,
    )
    quizzes = await _query_available_quizzes(
        db,
        current_user,
        chat_type=chat_type,
        keyword=keyword,
        category=category,
        tag=tag,
        page=page,
        page_size=page_size,
    )
    hospital_ids = sorted({q.hospital_id for q in quizzes if q.hospital_id})
    department_ids = sorted({q.department_id for q in quizzes if q.department_id})
    hospital_map: dict[int, str] = {}
    department_map: dict[int, str] = {}
    if hospital_ids:
        hospitals = (await db.execute(select(Hospital).where(Hospital.id.in_(hospital_ids)))).scalars().all()
        hospital_map = {h.id: h.name for h in hospitals}
    if department_ids:
        departments = (
            await db.execute(select(Department).where(Department.id.in_(department_ids)))
        ).scalars().all()
        department_map = {d.id: d.name for d in departments}
    items = [
        PracticeAvailableItem(
            id=q.id,
            title=q.title,
            scope=q.scope,
            hospital_id=q.hospital_id,
            hospital_name=hospital_map.get(q.hospital_id or 0),
            department_id=q.department_id,
            department_name=department_map.get(q.department_id or 0),
            chat_type=q.chat_type,
            category=q.category,
            tags=q.tags,
            difficulty=q.difficulty,
            message_count=q.message_count,
            patient_name=q.patient_name,
            counselor_name=q.counselor_name,
        )
        for q in quizzes
    ]
    return ApiResponse(
        code=200,
        message="success",
        data=PracticeAvailablePageData(items=items, total=total, page=page, page_size=page_size),
    )


@router.get("/my-dashboard", response_model=ApiResponse)
async def my_dashboard(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    tenant_id = ensure_tenant_bound(current_user)
    now = datetime.now()
    heatmap_days = 30
    quizzes_all = await _query_available_quizzes(db, current_user)
    total_quizzes = len(quizzes_all)
    accessible_quiz_ids = [q.id for q in quizzes_all]

    practice_filters = [Practice.user_id == current_user.id, Practice.tenant_id == tenant_id]
    if accessible_quiz_ids:
        practice_filters.append(Practice.quiz_id.in_(accessible_quiz_ids))
    else:
        practice_filters.append(Practice.quiz_id == -1)

    week_start = now - timedelta(days=6)
    summary_row = (
        await db.execute(
            select(
                func.count(Practice.id).label("total_practices"),
                func.sum(case((Practice.status == "in_progress", 1), else_=0)).label("in_progress_count"),
                func.count(
                    func.distinct(case((Practice.status == "completed", Practice.quiz_id), else_=None))
                ).label("completed_quizzes"),
                func.sum(case((Practice.started_at >= week_start, 1), else_=0)).label("this_week_practices"),
            ).where(*practice_filters)
        )
    ).one()
    total_practices = int(summary_row.total_practices or 0)
    in_progress_count = int(summary_row.in_progress_count or 0)
    completed_quizzes = int(summary_row.completed_quizzes or 0)
    this_week_practices = int(summary_row.this_week_practices or 0)

    heatmap_start = now - timedelta(days=heatmap_days - 1)
    heatmap_rows = (
        await db.execute(
            select(func.date(Practice.started_at).label("d"), func.count(Practice.id).label("c"))
            .where(*practice_filters, Practice.started_at >= heatmap_start)
            .group_by(func.date(Practice.started_at))
            .order_by(func.date(Practice.started_at).asc())
        )
    ).all()
    heatmap_map = {str(r.d): int(r.c or 0) for r in heatmap_rows}
    weekly_heatmap: list[PracticeDashboardHeatmapItem] = []
    for i in range(heatmap_days):
        d = (now - timedelta(days=heatmap_days - 1 - i)).strftime("%Y-%m-%d")
        weekly_heatmap.append(PracticeDashboardHeatmapItem(date=d, count=heatmap_map.get(d, 0)))

    # 连续训练天数（按 started_at 去重天）
    all_day_rows = (
        await db.execute(
            select(func.date(Practice.started_at).label("d"))
            .where(*practice_filters)
            .group_by(func.date(Practice.started_at))
            .order_by(func.date(Practice.started_at).desc())
        )
    ).all()
    trained_days = {str(r.d) for r in all_day_rows}
    streak_days = 0
    cursor = now.date()
    while cursor.strftime("%Y-%m-%d") in trained_days:
        streak_days += 1
        cursor -= timedelta(days=1)

    reply_count = int(
        (
            await db.execute(
                select(func.count(PracticeReply.id))
                .join(Practice, Practice.id == PracticeReply.practice_id)
                .where(*practice_filters)
            )
        ).scalar_one()
        or 0
    )
    avg_rounds = round((reply_count / total_practices), 2) if total_practices > 0 else 0.0

    recent_rows = (
        await db.execute(
            select(Practice, Quiz)
            .join(Quiz, Quiz.id == Practice.quiz_id)
            .where(*practice_filters)
            .order_by(Practice.started_at.desc())
            .limit(5)
        )
    ).all()
    recent_practices = [
        PracticeDashboardRecentItem(
            practice_id=p.id,
            quiz_id=q.id,
            quiz_title=q.title,
            status=p.status,
            started_at=p.started_at.strftime("%Y-%m-%d %H:%M:%S"),
            completed_at=p.completed_at.strftime("%Y-%m-%d %H:%M:%S") if p.completed_at else None,
        )
        for p, q in recent_rows
    ]

    last_in_progress_row = (
        await db.execute(
            select(Practice, Quiz)
            .join(Quiz, Quiz.id == Practice.quiz_id)
            .where(*practice_filters, Practice.status == "in_progress")
            .order_by(Practice.started_at.desc())
            .limit(1)
        )
    ).first()
    last_in_progress = (
        PracticeDashboardContinueItem(
            practice_id=last_in_progress_row[0].id,
            quiz_id=last_in_progress_row[1].id,
            quiz_title=last_in_progress_row[1].title,
            started_at=last_in_progress_row[0].started_at.strftime("%Y-%m-%d %H:%M:%S"),
        )
        if last_in_progress_row
        else None
    )

    return ApiResponse(
        code=200,
        message="success",
        data=PracticeDashboardData(
            total_quizzes=total_quizzes,
            completed_quizzes=completed_quizzes,
            total_practices=total_practices,
            this_week_practices=this_week_practices,
            streak_days=streak_days,
            avg_rounds=avg_rounds,
            weekly_heatmap=weekly_heatmap,
            recent_practices=recent_practices,
            in_progress_count=in_progress_count,
            last_in_progress=last_in_progress,
        ),
    )


@router.get("/available/options", response_model=ApiResponse)
async def get_available_quiz_options(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    chat_type: str | None = Query(default=None, pattern="^(active|passive)$"),
    keyword: str | None = None,
) -> ApiResponse:
    quizzes = await _query_available_quizzes(
        db,
        current_user,
        chat_type=chat_type,
        keyword=keyword,
    )
    category_counter: dict[str, int] = {}
    tag_counter: dict[str, int] = {}
    for quiz in quizzes:
        category = (quiz.category or "").strip()
        if category:
            category_counter[category] = category_counter.get(category, 0) + 1
        for tag in _split_tags(quiz.tags):
            tag_counter[tag] = tag_counter.get(tag, 0) + 1
    categories = [
        PracticeFilterOptionItem(name=name, count=count)
        for name, count in sorted(category_counter.items(), key=lambda x: (-x[1], x[0]))
    ]
    tags = [
        PracticeFilterOptionItem(name=name, count=count)
        for name, count in sorted(tag_counter.items(), key=lambda x: (-x[1], x[0]))
    ]
    return ApiResponse(
        code=200,
        message="success",
        data=PracticeAvailableFilterOptionsData(categories=categories, tags=tags),
    )


@router.post("/start-random", response_model=ApiResponse)
async def start_random_practice(
    payload: PracticeRandomStartRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    tenant_id = ensure_tenant_bound(current_user)
    chat_type = payload.chat_type if payload.chat_type in {"active", "passive"} else None
    keyword = (payload.keyword or "").strip() or None
    category = (payload.category or "").strip() or None
    tag = (payload.tag or "").strip() or None
    candidates = await _query_available_quizzes(
        db,
        current_user,
        chat_type=chat_type,
        keyword=keyword,
        category=category,
        tag=tag,
    )
    if not candidates:
        raise HTTPException(status_code=404, detail="当前筛选条件下没有可训练案例")

    candidate_ids = [q.id for q in candidates]
    recent_ids = (
        await db.execute(
            select(Practice.quiz_id)
            .where(
                Practice.user_id == current_user.id,
                Practice.quiz_id.in_(candidate_ids),
                Practice.tenant_id == tenant_id,
            )
            .order_by(Practice.started_at.desc())
            .limit(5)
        )
    ).scalars().all()
    recent_set = set(recent_ids)
    pool = [q for q in candidates if q.id not in recent_set] or candidates
    pool_ids = [q.id for q in pool]

    stats_rows = (
        await db.execute(
            select(
                Practice.quiz_id,
                func.count(Practice.id).label("cnt"),
                func.max(Practice.started_at).label("last_at"),
            )
            .where(Practice.user_id == current_user.id, Practice.quiz_id.in_(pool_ids))
            .where(Practice.tenant_id == tenant_id)
            .group_by(Practice.quiz_id)
        )
    ).all()
    stats_map = {row.quiz_id: {"count": int(row.cnt or 0), "last_at": row.last_at} for row in stats_rows}

    min_count = min(stats_map.get(q.id, {}).get("count", 0) for q in pool)
    least_used = [q for q in pool if stats_map.get(q.id, {}).get("count", 0) == min_count]
    never_practiced = [q for q in least_used if q.id not in stats_map]
    if never_practiced:
        chosen = random.choice(never_practiced)
    else:
        oldest_time = min(stats_map[q.id]["last_at"] for q in least_used)
        oldest_pool = [q for q in least_used if stats_map[q.id]["last_at"] == oldest_time]
        chosen = random.choice(oldest_pool)

    current_hospital_id = current_user.hospital_id
    current_department_id = current_user.department_id
    if not current_department_id:
        current_department_id = chosen.department_id
    if not current_hospital_id:
        current_hospital_id = chosen.hospital_id
    if not current_hospital_id:
        raise HTTPException(status_code=400, detail="当前账号未绑定医院，无法开始训练")

    practice = Practice(
        tenant_id=tenant_id,
        user_id=current_user.id,
        quiz_id=chosen.id,
        hospital_id=current_hospital_id,
        department_id=current_department_id,
        status="in_progress",
        current_step=1,
    )
    db.add(practice)
    await db.commit()
    await db.refresh(practice)
    return ApiResponse(
        code=200,
        message="success",
        data=PracticeStartData(practice_id=practice.id, quiz_id=chosen.id, status=practice.status),
    )


@router.get("/{practice_id}/history", response_model=ApiResponse)
async def get_practice_history(
    practice_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    tenant_id = ensure_tenant_bound(current_user)
    practice = await _get_practice_or_404(db, practice_id, current_user.id, tenant_id)
    messages = await _get_ordered_messages(db, practice.quiz_id, tenant_id)
    if not messages:
        return ApiResponse(code=200, message="success", data=PracticeHistoryData(messages=[]))

    id_to_index = {m.id: idx for idx, m in enumerate(messages)}
    rows = (
        await db.execute(
            select(PracticeReply, Message)
            .join(Message, Message.id == PracticeReply.message_id)
            .where(
                PracticeReply.practice_id == practice.id,
                PracticeReply.tenant_id == tenant_id,
                Message.tenant_id == tenant_id,
            )
            .order_by(Message.sequence.asc(), Message.id.asc())
        )
    ).all()

    pointer = 1
    history: list[PracticeMessage] = []
    for reply, target in rows:
        target_idx = id_to_index.get(target.id)
        if target_idx is None:
            continue

        # 回放本轮中咨询员之前已看到的患者消息
        idx = max(pointer - 1, 0)
        while idx < len(messages) and idx < target_idx:
            if messages[idx].role == "patient":
                history.append(_fmt_message(messages[idx]))
            idx += 1

        # 回放咨询员历史作答（不暴露标准答案）
        history.append(
            PracticeMessage(
                id=-reply.id,
                role="student",
                content_type="text",
                content=reply.reply_content,
                sender_name="我",
                original_time=reply.reply_time.strftime("%Y-%m-%d %H:%M:%S"),
            )
        )

        # 跳过连续咨询师消息，定位到下一批患者消息
        jump = target_idx + 1
        while jump < len(messages) and messages[jump].role == "counselor":
            jump += 1
        pointer = jump + 1

    return ApiResponse(code=200, message="success", data=PracticeHistoryData(messages=history))


@router.post("/start", response_model=ApiResponse)
async def start_practice(
    payload: PracticeStartRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    tenant_id = ensure_tenant_bound(current_user)
    hospital_ids = await get_accessible_hospital_ids(current_user, db)
    department_ids = await get_accessible_department_ids(current_user, db)
    current_hospital_id = current_user.hospital_id or (hospital_ids[0] if hospital_ids else None)
    current_department_id = current_user.department_id or (department_ids[0] if department_ids else None)
    quiz_stmt = select(Quiz).where(
        Quiz.id == payload.quiz_id, Quiz.is_deleted.is_(False), Quiz.is_active.is_(True), Quiz.tenant_id == tenant_id
    )
    quiz = (await db.execute(quiz_stmt)).scalars().first()
    if not quiz:
        raise HTTPException(status_code=404, detail="案例不存在或未启用")
    if quiz.scope != "common":
        if current_user.role == "super_admin" or current_user.is_all_hospitals:
            pass
        elif not (
            (quiz.department_id and quiz.department_id in department_ids)
            or (quiz.hospital_id and quiz.hospital_id in hospital_ids)
        ):
            raise HTTPException(status_code=403, detail="无权训练其他医院案例")
    if not current_department_id:
        current_department_id = quiz.department_id
    if not current_hospital_id:
        current_hospital_id = quiz.hospital_id
    if not current_hospital_id:
        raise HTTPException(status_code=400, detail="当前账号未绑定医院，无法开始训练")

    practice = Practice(
        tenant_id=tenant_id,
        user_id=current_user.id,
        quiz_id=quiz.id,
        hospital_id=current_hospital_id,
        department_id=current_department_id,
        status="in_progress",
        current_step=1,
    )
    db.add(practice)
    await db.commit()
    await db.refresh(practice)
    return ApiResponse(
        code=200,
        message="success",
        data=PracticeStartData(practice_id=practice.id, quiz_id=quiz.id, status=practice.status),
    )


@router.get("/{practice_id}/next", response_model=ApiResponse)
async def get_next_messages(
    practice_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    tenant_id = ensure_tenant_bound(current_user)
    practice = await _get_practice_or_404(db, practice_id, current_user.id, tenant_id)
    messages = await _get_ordered_messages(db, practice.quiz_id, tenant_id)
    if not messages:
        return ApiResponse(
            code=200,
            message="success",
            data=NextData(messages=[], need_reply=False, reply_to_message_id=None, is_last=True),
        )

    pointer = max(practice.current_step, 1)
    if pointer > len(messages):
        return ApiResponse(
            code=200,
            message="success",
            data=NextData(messages=[], need_reply=False, reply_to_message_id=None, is_last=True),
        )

    batch: list[PracticeMessage] = []
    idx = pointer - 1
    while idx < len(messages) and messages[idx].role != "counselor":
        m = messages[idx]
        batch.append(_fmt_message(m))
        idx += 1

    if idx >= len(messages):
        practice.current_step = len(messages) + 1
        await db.commit()
        return ApiResponse(
            code=200,
            message="success",
            data=NextData(messages=batch, need_reply=False, reply_to_message_id=None, is_last=True),
        )

    target = messages[idx]
    is_last = idx == len(messages) - 1
    return ApiResponse(
        code=200,
        message="success",
        data=NextData(
            messages=batch,
            need_reply=True,
            reply_to_message_id=target.id,
            is_last=is_last,
        ),
    )


@router.post("/{practice_id}/reply", response_model=ApiResponse)
async def submit_reply(
    practice_id: int,
    payload: ReplyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    tenant_id = ensure_tenant_bound(current_user)
    practice = await _get_practice_or_404(db, practice_id, current_user.id, tenant_id)
    if practice.status != "in_progress":
        raise HTTPException(status_code=400, detail="训练已完成，不能继续作答")

    msg_stmt = select(Message).where(
        Message.id == payload.message_id,
        Message.quiz_id == practice.quiz_id,
        Message.tenant_id == tenant_id,
    )
    target = (await db.execute(msg_stmt)).scalars().first()
    if not target or target.role != "counselor":
        raise HTTPException(status_code=400, detail="message_id 非有效咨询师消息")

    existing_stmt = select(PracticeReply).where(
        PracticeReply.practice_id == practice.id,
        PracticeReply.message_id == target.id,
        PracticeReply.tenant_id == practice.tenant_id,
    )
    existing = (await db.execute(existing_stmt)).scalars().first()
    if existing:
        existing.reply_content = payload.content.strip()
        existing.reply_time = datetime.now()
    else:
        db.add(
            PracticeReply(
                tenant_id=practice.tenant_id,
                practice_id=practice.id,
                message_id=target.id,
                reply_content=payload.content.strip(),
            )
        )

    # 一次作答后，直接跳过连续咨询师消息，推进到下一段患者消息。
    # 这样训练体验是“每轮仅回复一次 -> 看到下一批患者输出”。
    ordered = await _get_ordered_messages(db, practice.quiz_id, tenant_id)
    next_pointer = len(ordered) + 1
    for i, msg in enumerate(ordered):
        if msg.id != target.id:
            continue
        j = i + 1
        while j < len(ordered) and ordered[j].role == "counselor":
            j += 1
        next_pointer = j + 1
        break

    practice.current_step = next_pointer
    await db.commit()
    return ApiResponse(
        code=200,
        message="success",
        data=ReplyData(practice_id=practice.id, message_id=target.id, current_step=practice.current_step),
    )


@router.post("/{practice_id}/complete", response_model=ApiResponse)
async def complete_practice(
    practice_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    tenant_id = ensure_tenant_bound(current_user)
    practice = await _get_practice_or_404(db, practice_id, current_user.id, tenant_id)
    if practice.status == "completed" and practice.completed_at:
        return ApiResponse(
            code=200,
            message="success",
            data=CompleteData(
                practice_id=practice.id,
                status=practice.status,
                completed_at=practice.completed_at,
            ),
        )

    practice.status = "completed"
    practice.completed_at = practice.completed_at or datetime.now()
    await db.commit()
    return ApiResponse(
        code=200,
        message="success",
        data=CompleteData(
            practice_id=practice.id,
            status=practice.status,
            completed_at=practice.completed_at,
        ),
    )


@router.get("/{practice_id}/review", response_model=ApiResponse)
async def get_review_data(
    practice_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    tenant_id = ensure_tenant_bound(current_user)
    practice = await _get_practice_or_404(db, practice_id, current_user.id, tenant_id)
    if practice.status != "completed":
        raise HTTPException(status_code=400, detail="请先完成训练再查看对比")

    quiz_stmt = select(Quiz).where(Quiz.id == practice.quiz_id, Quiz.tenant_id == tenant_id)
    quiz = (await db.execute(quiz_stmt)).scalars().first()
    if not quiz:
        raise HTTPException(status_code=404, detail="案例不存在")

    messages = await _get_ordered_messages(db, practice.quiz_id, tenant_id)
    replies_stmt = select(PracticeReply).where(
        PracticeReply.practice_id == practice.id,
        PracticeReply.tenant_id == tenant_id,
    )
    replies = (await db.execute(replies_stmt)).scalars().all()
    reply_map = {r.message_id: r for r in replies}
    comments = (
        await db.execute(
            select(PracticeComment, User.real_name)
            .join(User, User.id == PracticeComment.admin_id)
            .where(PracticeComment.practice_id == practice.id, PracticeComment.tenant_id == tenant_id)
            .order_by(PracticeComment.id.asc())
        )
    ).all()

    dialogues: list[ReviewDialogue] = []
    idx = 0
    while idx < len(messages):
        patient_batch: list[PracticeMessage] = []
        while idx < len(messages) and messages[idx].role == "patient":
            m = messages[idx]
            patient_batch.append(_fmt_message(m))
            idx += 1

        counselor_batch: list[PracticeMessage] = []
        while idx < len(messages) and messages[idx].role == "counselor":
            m = messages[idx]
            counselor_batch.append(_fmt_message(m))
            idx += 1

        if not counselor_batch:
            continue

        first_answer = counselor_batch[0]
        reply = reply_map.get(first_answer.id)
        dialogues.append(
            ReviewDialogue(
                patient_messages=patient_batch,
                standard_answer=first_answer,
                standard_answers=counselor_batch,
                student_reply={
                    "content": reply.reply_content,
                    "reply_time": reply.reply_time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                if reply
                else None,
            )
        )

    return ApiResponse(
        code=200,
        message="success",
        data=ReviewData(
            quiz_title=quiz.title,
            dialogues=dialogues,
            comments=[
                {
                    "comment_id": c.id,
                    "admin_id": c.admin_id,
                    "admin_name": admin_name,
                    "content": c.content,
                    "created_at": c.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                }
                for c, admin_name in comments
            ],
        ),
    )


@router.post("/faq/copilot", response_model=ApiResponse)
async def practice_faq_copilot(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    tenant_id = ensure_tenant_bound(current_user)
    await _ensure_faq_module_enabled(db, tenant_id)

    query_text = str(payload.get("query") or "").strip()
    if not query_text:
        raise HTTPException(status_code=422, detail="query 不能为空")
    requested_quality_mode = str(payload.get("quality_mode") or "auto").strip().lower()

    started = time.monotonic()
    query_embedding = await get_single_embedding(query_text)
    quality_mode, route_reason = _resolve_practice_quality_mode(query_text, requested_quality_mode)
    matched = await semantic_search(db, query_embedding, tenant_id, top_k=6)
    copilot = await copilot_answer(query_text, matched, quality_mode=quality_mode)
    latency_ms = int((time.monotonic() - started) * 1000)

    db.add(
        FaqCopilotLog(
            tenant_id=tenant_id,
            user_id=current_user.id,
            mode=f"practice-copilot:{requested_quality_mode}->{quality_mode}",
            query=query_text,
            reply=copilot.recommended_reply,
            confidence=float(copilot.confidence or 0.0),
            sources_json=json.dumps(copilot.sources or [], ensure_ascii=False),
            matched_count=len(matched),
            latency_ms=latency_ms,
        )
    )
    await db.commit()

    return ApiResponse(
        code=200,
        message="success",
        data=PracticeFaqCopilotData(
            recommended_reply=copilot.recommended_reply,
            confidence=float(copilot.confidence or 0.0),
            matched_faqs=matched,
            latency_ms=latency_ms,
            quality_mode_requested=requested_quality_mode,
            quality_mode_effective=quality_mode,
            quality_route_reason=route_reason,
        ),
    )


@router.post("/faq/search", response_model=ApiResponse)
async def practice_faq_search(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    tenant_id = ensure_tenant_bound(current_user)
    await _ensure_faq_module_enabled(db, tenant_id)

    query_text = str(payload.get("query") or "").strip()
    if not query_text:
        raise HTTPException(status_code=422, detail="query 不能为空")
    top_k = int(payload.get("top_k") or 10)
    top_k = max(1, min(top_k, 20))

    started = time.monotonic()
    query_embedding = await get_single_embedding(query_text)
    matched = await semantic_search(db, query_embedding, tenant_id, top_k=top_k)
    latency_ms = int((time.monotonic() - started) * 1000)
    return ApiResponse(
        code=200,
        message="success",
        data=PracticeFaqSearchData(results=matched, latency_ms=latency_ms),
    )


@router.get("/faq/clusters", response_model=ApiResponse)
async def practice_faq_clusters(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    keyword: str | None = None,
    category: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=50),
) -> ApiResponse:
    tenant_id = ensure_tenant_bound(current_user)
    await _ensure_faq_module_enabled(db, tenant_id)

    filters = [FaqCluster.tenant_id == tenant_id]
    kw = (keyword or "").strip()
    if kw:
        like_kw = f"%{kw}%"
        filters.append(
            (FaqCluster.title.like(like_kw))
            | (FaqCluster.representative_question.like(like_kw))
            | (FaqCluster.summary.like(like_kw))
            | (FaqCluster.best_answer.like(like_kw))
            | (FaqCluster.category.like(like_kw))
        )
    if category:
        filters.append(FaqCluster.category == category.strip())

    total = int((await db.execute(select(func.count(FaqCluster.id)).where(*filters))).scalar_one() or 0)
    rows = (
        await db.execute(
            select(FaqCluster)
            .where(*filters)
            .order_by(FaqCluster.updated_at.desc(), FaqCluster.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    items = [
        PracticeFaqClusterItem(
            cluster_id=r.id,
            title=r.title,
            category=r.category,
            summary=r.summary,
            representative_question=r.representative_question,
            best_answer=r.best_answer,
            question_count=r.question_count,
            answer_count=r.answer_count,
        )
        for r in rows
    ]
    category_rows = (
        await db.execute(
            select(FaqCluster.category)
            .where(FaqCluster.tenant_id == tenant_id, FaqCluster.category.is_not(None))
            .group_by(FaqCluster.category)
            .order_by(func.count(FaqCluster.id).desc(), FaqCluster.category.asc())
            .limit(100)
        )
    ).all()
    categories = [str(r[0]).strip() for r in category_rows if str(r[0]).strip()]
    return ApiResponse(
        code=200,
        message="success",
        data=PracticeFaqClusterListData(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            categories=categories,
        ),
    )


@router.get("/{practice_id}/ai-score", response_model=ApiResponse)
async def get_ai_score(
    practice_id: int,
    _: User = Depends(require_module("mod_ai_scoring")),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    tenant_id = ensure_tenant_bound(current_user)
    if not await _is_ai_scoring_enabled(db, tenant_id):
        raise HTTPException(status_code=403, detail="AI评分能力已被系统管理员关闭")

    practice = await _get_practice_or_404(db, practice_id, current_user.id, tenant_id)
    if practice.status != "completed":
        raise HTTPException(status_code=400, detail="请先完成训练后再查看AI评分")

    ordered_messages = await _get_ordered_messages(db, practice.quiz_id, tenant_id)
    rounds = _build_counselor_rounds(ordered_messages)
    if not rounds:
        raise HTTPException(status_code=400, detail="当前案例缺少可评分回合")

    replies = (
        await db.execute(
            select(PracticeReply)
            .where(
                PracticeReply.practice_id == practice.id,
                PracticeReply.tenant_id == tenant_id,
            )
        )
    ).scalars().all()
    reply_map = {int(r.message_id): (r.reply_content or "").strip() for r in replies if (r.reply_content or "").strip()}
    total_rounds = len(rounds)
    answered_rounds = [r for r in rounds if int(r["first_message_id"]) in reply_map]
    answered = len(answered_rounds)
    completion_rate = round((answered / total_rounds) * 100, 2)
    completion_score = min(100.0, completion_rate)

    semantic_scores: list[float] = []
    keypoint_scores: list[float] = []
    quality_scores: list[float] = []
    empathy_hits = 0
    reply_texts: list[str] = []
    for item in rounds:
        message_id = int(item["first_message_id"])
        standards = [s for s in item["standards"] if (s or "").strip()]
        reply_text = reply_map.get(message_id, "")
        if not reply_text:
            semantic_scores.append(0.0)
            keypoint_scores.append(0.0)
            quality_scores.append(0.0)
            continue
        reply_texts.append(reply_text)
        candidate_similarities = [_text_similarity(reply_text, std) for std in standards] if standards else [0.0]
        semantic = max(candidate_similarities) if candidate_similarities else 0.0
        semantic_scores.append(semantic * 100.0)
        keyword_pool: set[str] = set()
        for std in standards:
            keyword_pool |= _extract_keywords(std)
        if keyword_pool:
            keypoint_scores.append(_keyword_recall(_normalize_text(reply_text), keyword_pool) * 100.0)
        else:
            keypoint_scores.append(semantic * 75.0)
        quality, empathy_hit = _score_communication_quality(reply_text)
        quality_scores.append(quality)
        if empathy_hit:
            empathy_hits += 1

    semantic_score = round(sum(semantic_scores) / total_rounds, 2) if total_rounds else 0.0
    keypoint_score = round(sum(keypoint_scores) / total_rounds, 2) if total_rounds else 0.0
    communication_score = round(sum(quality_scores) / total_rounds, 2) if total_rounds else 0.0
    risk_control_score, risk_reasons = _score_risk_control(reply_texts)
    avg_len = round((sum(len(t) for t in reply_texts) / len(reply_texts)), 2) if reply_texts else 0.0

    rule_dimension_scores = {
        "task_completion": round(completion_score, 2),
        "semantic_alignment": semantic_score,
        "keypoint_coverage": keypoint_score,
        "communication_quality": communication_score,
        "risk_control": round(risk_control_score, 2),
    }
    rule_overall = round(
        completion_score * 0.20
        + semantic_score * 0.30
        + keypoint_score * 0.20
        + communication_score * 0.20
        + risk_control_score * 0.10,
        2,
    )

    llm_result = await run_llm_audit(rounds, reply_map)

    if llm_result.status == "success" and llm_result.scores:
        fused_scores = fuse_scores(rule_dimension_scores, llm_result.scores)
        fused_overall = round(
            rule_overall * settings.ai_scoring_rule_weight
            + llm_result.overall * settings.ai_scoring_llm_weight,
            2,
        )
    else:
        fused_scores = rule_dimension_scores
        fused_overall = rule_overall
    overall = int(round(fused_overall))

    tc = fused_scores.get("task_completion", 0)
    sa = fused_scores.get("semantic_alignment", 0)
    kc = fused_scores.get("keypoint_coverage", 0)
    cq = fused_scores.get("communication_quality", 0)
    rc = fused_scores.get("risk_control", 0)
    deduction_reasons: list[str] = []
    if tc < 70:
        deduction_reasons.append("任务完成度偏低：未覆盖所有咨询师回合。")
    if sa < 65:
        deduction_reasons.append("语义贴合度偏低：回复与标准答案语义匹配不足。")
    if kc < 65:
        deduction_reasons.append("关键点命中偏低：建议覆盖标准答案中的核心要点。")
    if cq < 65:
        deduction_reasons.append("沟通质量偏低：建议加强共情表达、结构化建议和礼貌用语。")
    if rc < 85:
        deduction_reasons.extend(risk_reasons[:3])
    if llm_result.status == "success" and llm_result.deduction_reasons:
        for r in llm_result.deduction_reasons:
            if r not in deduction_reasons:
                deduction_reasons.append(r)

    suggestions: list[str] = []
    if completion_rate < 85:
        suggestions.append("优先提升回合覆盖率：每轮咨询师问题都尽量做出完整回应。")
    if sa < 70 or kc < 70:
        suggestions.append("建议围绕标准答案关键词组织回复，先判断问题意图再给建议。")
    if cq < 70:
        suggestions.append("建议采用“先共情-再建议-后确认”的三段式表达。")
    if rc < 90:
        suggestions.append("避免绝对化承诺，尽量使用条件化和风险提示表达。")
    if not suggestions:
        suggestions.append("整体表现良好，可进一步优化表达精炼度与复盘稳定性。")

    llm_audit_payload: dict = {
        "enabled": llm_result.enabled,
        "provider": llm_result.provider,
        "model": llm_result.model or settings.dashscope_model,
        "status": llm_result.status,
        "latency_ms": llm_result.latency_ms,
    }
    if llm_result.status == "success":
        llm_audit_payload["scores"] = llm_result.scores
        llm_audit_payload["overall"] = llm_result.overall
        llm_audit_payload["deduction_reasons"] = llm_result.deduction_reasons
        llm_audit_payload["highlights"] = llm_result.highlights
        llm_audit_payload["summary"] = llm_result.summary
        llm_audit_payload["fusion_weights"] = {
            "rule": settings.ai_scoring_rule_weight,
            "llm": settings.ai_scoring_llm_weight,
        }
    elif llm_result.error:
        llm_audit_payload["error"] = llm_result.error

    return ApiResponse(
        code=200,
        message="success",
        data=PracticeAiScoreData(
            practice_id=practice.id,
            overall_score=overall,
            completion_rate=completion_rate,
            avg_reply_length=avg_len,
            empathy_hits=empathy_hits,
            suggestions=suggestions,
            dimension_scores=fused_scores,
            deduction_reasons=list(dict.fromkeys(deduction_reasons)),
            llm_audit=llm_audit_payload,
        ),
    )
