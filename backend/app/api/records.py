from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import ensure_tenant_bound, get_current_user
from app.models import Message, Practice, PracticeComment, PracticeReply, Quiz, User
from app.schemas.record import ApiResponse, RecordDetailData, RecordDialogue, RecordListItem, RecordListPageData

router = APIRouter()


@router.get("/my", response_model=ApiResponse)
async def my_records(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
) -> ApiResponse:
    tenant_id = ensure_tenant_bound(current_user)
    total_stmt = select(func.count(Practice.id)).where(Practice.user_id == current_user.id, Practice.tenant_id == tenant_id)
    total = int((await db.execute(total_stmt)).scalar_one())
    stmt = (
        select(Practice, Quiz)
        .join(Quiz, Quiz.id == Practice.quiz_id)
        .where(Practice.user_id == current_user.id, Practice.tenant_id == tenant_id, Quiz.tenant_id == tenant_id)
        .order_by(Practice.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.execute(stmt)).all()
    items = [
        RecordListItem(
            practice_id=p.id,
            quiz_id=q.id,
            quiz_title=q.title,
            status=p.status,
            started_at=p.started_at,
            completed_at=p.completed_at,
        )
        for p, q in rows
    ]
    return ApiResponse(
        code=200,
        message="success",
        data=RecordListPageData(items=items, total=total, page=page, page_size=page_size),
    )


@router.get("/my/{practice_id}", response_model=ApiResponse)
async def my_record_detail(
    practice_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    tenant_id = ensure_tenant_bound(current_user)
    practice = (
        await db.execute(
            select(Practice).where(
                Practice.id == practice_id,
                Practice.user_id == current_user.id,
                Practice.tenant_id == tenant_id,
            )
        )
    ).scalars().first()
    if not practice:
        raise HTTPException(status_code=404, detail="记录不存在")
    if practice.status != "completed":
        raise HTTPException(status_code=400, detail="该练习尚未完成，请从“我的练习记录”点击继续练习")

    quiz = (
        await db.execute(select(Quiz).where(Quiz.id == practice.quiz_id, Quiz.tenant_id == tenant_id))
    ).scalars().first()
    if not quiz:
        raise HTTPException(status_code=404, detail="案例不存在")

    messages = (
        await db.execute(
            select(Message)
            .where(Message.quiz_id == practice.quiz_id, Message.tenant_id == tenant_id)
            .order_by(Message.sequence.asc(), Message.id.asc())
        )
    ).scalars().all()
    replies = (
        await db.execute(
            select(PracticeReply).where(PracticeReply.practice_id == practice.id, PracticeReply.tenant_id == tenant_id)
        )
    ).scalars().all()
    comments = (
        await db.execute(
            select(PracticeComment, User.real_name)
            .join(User, User.id == PracticeComment.admin_id)
            .where(PracticeComment.practice_id == practice.id, PracticeComment.tenant_id == tenant_id)
            .order_by(PracticeComment.id.asc())
        )
    ).all()
    reply_map = {r.message_id: r for r in replies}

    dialogues: list[RecordDialogue] = []
    idx = 0
    while idx < len(messages):
        patient_batch: list[dict] = []
        while idx < len(messages) and messages[idx].role == "patient":
            m = messages[idx]
            patient_batch.append(
                {
                    "id": m.id,
                    "role": m.role,
                    "content_type": m.content_type,
                    "content": m.content,
                    "sender_name": m.sender_name,
                    "original_time": m.original_time.strftime("%Y-%m-%d %H:%M:%S")
                    if m.original_time
                    else None,
                }
            )
            idx += 1

        counselor_batch: list[dict] = []
        while idx < len(messages) and messages[idx].role == "counselor":
            m = messages[idx]
            counselor_batch.append(
                {
                    "id": m.id,
                    "role": m.role,
                    "content_type": m.content_type,
                    "content": m.content,
                    "sender_name": m.sender_name,
                    "original_time": m.original_time.strftime("%Y-%m-%d %H:%M:%S")
                    if m.original_time
                    else None,
                }
            )
            idx += 1

        if not counselor_batch:
            continue

        first_answer = counselor_batch[0]
        rp = reply_map.get(first_answer["id"])
        dialogues.append(
            RecordDialogue(
                patient_messages=patient_batch,
                standard_answer=first_answer,
                standard_answers=counselor_batch,
                student_reply={
                    "content": rp.reply_content,
                    "reply_time": rp.reply_time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                if rp
                else None,
            )
        )

    detail = RecordDetailData(
        practice_id=practice.id,
        quiz_title=quiz.title,
        status=practice.status,
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
    )
    return ApiResponse(code=200, message="success", data=detail)
