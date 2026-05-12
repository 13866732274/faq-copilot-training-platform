from __future__ import annotations

from datetime import datetime
import hashlib
import json
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import ensure_tenant_bound, get_accessible_department_ids, get_accessible_hospital_ids, require_admin
from app.models import Department, Hospital, Message, Practice, Quiz, QuizVersion, User
from app.schemas.quiz import (
    ApiResponse,
    BatchQuizMetaUpdateData,
    BatchQuizMetaUpdateRequest,
    CategoryDeleteRequest,
    CategoryMergeRequest,
    CategoryRenameRequest,
    BatchReparseData,
    BatchReparseEstimateData,
    BatchReparseRequest,
    ConfirmImportData,
    ConfirmImportRequest,
    ImportQualityReport,
    MessageItem,
    PageData,
    QuizDetailData,
    QuizListItem,
    QuizMetaOptionItem,
    QuizMetaOptionsData,
    QuizMetaOperateData,
    TagDeleteRequest,
    TagMergeRequest,
    TagRenameRequest,
    QuizUpdateData,
    QuizUpdateRequest,
    QuizVersionItem,
    UploadPreviewData,
)
from app.services.csv_parser import parse_csv_text, parse_excel_bytes
from app.services.html_parser import parse_html_auto, parse_vel_html
from app.services.audit import append_audit_log, get_request_ip
from app.services.rbac import enforce_rbac
from app.services.preview_store import delete_preview, load_preview, save_preview

router = APIRouter()

UPLOAD_DIR = Path("/www/wwwroot/chattrainer/backend/uploads/html")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_SIZE_MB = 20
LEGACY_MEDIA_MARKERS = (
    "图片消息",
    "语音消息",
    "[图片]",
    "【图片】",
    "[语音]",
    "【语音】",
)


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
        unique.append(item[:50])
    return unique


def _join_tags(tags: list[str]) -> str | None:
    cleaned = [item.strip() for item in tags if (item or "").strip()]
    return ",".join(cleaned) if cleaned else None


async def _create_version_snapshot(
    db: AsyncSession,
    quiz: Quiz,
    *,
    source_file: str | None,
    message_count: int,
    created_by: int | None,
) -> None:
    max_no = (
        await db.execute(
            select(func.coalesce(func.max(QuizVersion.version_no), 0)).where(
                QuizVersion.quiz_id == quiz.id,
                QuizVersion.tenant_id == quiz.tenant_id,
            )
        )
    ).scalar_one()
    db.add(
        QuizVersion(
            quiz_id=quiz.id,
            tenant_id=quiz.tenant_id,
            version_no=int(max_no) + 1,
            source_file=source_file,
            message_count=message_count,
            created_by=created_by,
        )
    )


def _parse_original_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _normalize_hash_content(value: str | None) -> str:
    return " ".join((value or "").replace("\xa0", " ").split()).strip()


def _build_content_hash_from_preview(messages: list[dict]) -> str:
    payload: list[list[str | int]] = []
    for item in messages:
        payload.append(
            [
                int(item.get("sequence") or 0),
                str(item.get("role") or ""),
                str(item.get("content_type") or ""),
                _normalize_hash_content(str(item.get("content") or "")),
            ]
        )
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _build_content_hash_from_messages(messages: list[Message]) -> str:
    payload: list[list[str | int]] = []
    for item in messages:
        payload.append(
            [
                int(item.sequence or 0),
                str(item.role or ""),
                str(item.content_type or ""),
                _normalize_hash_content(str(item.content or "")),
            ]
        )
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _build_duplicate_scope_filters(
    *,
    scope: str,
    hospital_id: int | None,
    department_id: int | None,
    chat_type: str,
    message_count: int,
    content_hash: str | None = None,
    content_hash_is_null: bool = False,
):
    filters = [
        Quiz.is_deleted.is_(False),
        Quiz.scope == scope,
        Quiz.chat_type == chat_type,
        Quiz.message_count == int(message_count),
    ]
    if scope == "department":
        filters.append(Quiz.department_id == department_id)
    elif scope == "hospital":
        filters.append(Quiz.hospital_id == hospital_id)
    if content_hash is not None:
        filters.append(Quiz.content_hash == content_hash)
    if content_hash_is_null:
        filters.append(Quiz.content_hash.is_(None))
    return filters


def _build_preview_messages_from_parsed(parsed) -> list[dict]:
    return [
        {
            "sequence": m.sequence,
            "role": m.role,
            "content_type": m.content_type,
            "content": m.content,
            "sender_name": m.sender_name,
            "original_time": m.original_time,
        }
        for m in parsed.messages
    ]


async def _quiz_has_legacy_media_markers(db: AsyncSession, quiz_id: int) -> bool:
    marker_filters = [Message.content.like(f"%{marker}%") for marker in LEGACY_MEDIA_MARKERS]
    stmt = (
        select(Message.id)
        .where(
            Message.quiz_id == quiz_id,
            or_(Message.content_type.is_(None), Message.content_type.notin_(["image", "audio"])),
            or_(*marker_filters),
        )
        .limit(1)
    )
    hit = (await db.execute(stmt)).scalars().first()
    return bool(hit)


async def _load_reparse_quizzes(
    payload: BatchReparseRequest,
    current_user: User,
    db: AsyncSession,
) -> list[Quiz]:
    tenant_id = ensure_tenant_bound(current_user)
    filters = [Quiz.is_deleted.is_(False), Quiz.scope == payload.scope, Quiz.tenant_id == tenant_id]
    if payload.chat_type:
        filters.append(Quiz.chat_type == payload.chat_type)
    if payload.scope == "department":
        if not payload.department_id:
            raise HTTPException(status_code=400, detail="科室专属重解析必须指定所属科室")
        filters.append(Quiz.department_id == payload.department_id)
    elif payload.scope == "hospital":
        if not payload.hospital_id:
            raise HTTPException(status_code=400, detail="医院专属重解析必须指定所属医院")
        filters.append(Quiz.hospital_id == payload.hospital_id)

    if payload.scope == "common":
        if current_user.role != "super_admin":
            raise HTTPException(status_code=403, detail="仅超级管理员可批量重解析通用案例库")
    elif current_user.role != "super_admin" and not current_user.is_all_hospitals:
        accessible_dept_ids = await get_accessible_department_ids(current_user, db)
        accessible_hospital_ids = await get_accessible_hospital_ids(current_user, db)
        if payload.scope == "department":
            if payload.department_id not in accessible_dept_ids:
                raise HTTPException(status_code=403, detail="无权重解析该科室案例库")
        elif payload.scope == "hospital":
            if payload.hospital_id not in accessible_hospital_ids:
                raise HTTPException(status_code=403, detail="无权重解析该医院案例库")

    stmt = select(Quiz).where(*filters).order_by(Quiz.id.desc()).limit(payload.limit)
    quizzes = (await db.execute(stmt)).scalars().all()
    if payload.only_legacy_or_empty_hash:
        legacy_or_empty_quizzes: list[Quiz] = []
        for quiz in quizzes:
            if not (quiz.content_hash or "").strip():
                legacy_or_empty_quizzes.append(quiz)
                continue
            if await _quiz_has_legacy_media_markers(db, quiz.id):
                legacy_or_empty_quizzes.append(quiz)
        quizzes = legacy_or_empty_quizzes
    return quizzes


async def _find_duplicate_quiz(
    db: AsyncSession,
    *,
    tenant_id: int,
    scope: str,
    hospital_id: int | None,
    department_id: int | None,
    chat_type: str,
    message_count: int,
    content_hash: str,
) -> Quiz | None:
    exact_stmt = select(Quiz).where(
        Quiz.tenant_id == tenant_id,
        *_build_duplicate_scope_filters(
            scope=scope,
            hospital_id=hospital_id,
            department_id=department_id,
            chat_type=chat_type,
            message_count=message_count,
            content_hash=content_hash,
        )
    )
    exact = (await db.execute(exact_stmt)).scalars().first()
    if exact:
        return exact

    # 兼容旧数据：对未计算 content_hash 的案例库做一次惰性匹配并回填 hash
    fallback_stmt = (
        select(Quiz)
        .where(
            Quiz.tenant_id == tenant_id,
            *_build_duplicate_scope_filters(
                scope=scope,
                hospital_id=hospital_id,
                department_id=department_id,
                chat_type=chat_type,
                message_count=message_count,
                content_hash_is_null=True,
            )
        )
        .limit(50)
    )
    candidates = (await db.execute(fallback_stmt)).scalars().all()
    for quiz in candidates:
        msgs = (
            await db.execute(
                select(Message)
                .where(Message.quiz_id == quiz.id)
                .order_by(Message.sequence.asc(), Message.id.asc())
            )
        ).scalars().all()
        candidate_hash = _build_content_hash_from_messages(msgs)
        if not quiz.content_hash:
            quiz.content_hash = candidate_hash
        if candidate_hash == content_hash:
            return quiz
    return None


def _build_quiz_access_filter(current_user: User, accessible_dept_ids: list[int], accessible_ids: list[int]):
    if current_user.role == "super_admin" or current_user.is_all_hospitals:
        return (Quiz.scope == "common") | (Quiz.hospital_id.is_not(None))
    return (
        (Quiz.scope == "common")
        | (Quiz.department_id.in_(accessible_dept_ids))
        | (Quiz.hospital_id.in_(accessible_ids))
    )


async def _load_quizzes_for_meta_operation(
    *,
    db: AsyncSession,
    current_user: User,
    tenant_id: int,
    scope: str | None = None,
    hospital_id: int | None = None,
    department_id: int | None = None,
    chat_type: str | None = None,
) -> list[Quiz]:
    accessible_dept_ids = await get_accessible_department_ids(current_user, db)
    accessible_ids = await get_accessible_hospital_ids(current_user, db)
    filters = [Quiz.tenant_id == tenant_id, Quiz.is_deleted.is_(False)]
    if scope:
        filters.append(Quiz.scope == scope)
    if hospital_id:
        filters.append(Quiz.hospital_id == hospital_id)
    if department_id:
        filters.append(Quiz.department_id == department_id)
    if chat_type:
        filters.append(Quiz.chat_type == chat_type)
    filters.append(_build_quiz_access_filter(current_user, accessible_dept_ids, accessible_ids))
    return (await db.execute(select(Quiz).where(*filters))).scalars().all()


def _normalize_names(names: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in names:
        value = (item or "").strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(value[:50])
    return result


@router.post("/upload", response_model=ApiResponse)
async def upload_html_preview(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="quiz:upload_preview",
        required_roles={"admin", "super_admin"},
        request=request,
        target_tenant_id=(int(current_user.tenant_id) if current_user.tenant_id else None),
        target_type="quiz",
    )
    filename = file.filename or "unknown"
    suffix = Path(filename).suffix.lower()
    ALLOWED_SUFFIXES = {".html", ".csv", ".xlsx"}
    if suffix not in ALLOWED_SUFFIXES:
        if suffix == ".xls":
            raise HTTPException(
                status_code=400,
                detail="不支持旧版 .xls 格式，请转换为 .xlsx 或 .csv 后重新上传。",
            )
        raise HTTPException(
            status_code=400,
            detail=f"支持的文件格式：{', '.join(ALLOWED_SUFFIXES)}",
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="上传文件为空")

    size_mb = len(content) / (1024 * 1024)
    if size_mb > MAX_UPLOAD_SIZE_MB:
        raise HTTPException(
            status_code=400,
            detail=f"文件大小 {size_mb:.1f}MB 超出限制 ({MAX_UPLOAD_SIZE_MB}MB)，请拆分后再上传",
        )

    preview_id = f"temp_{uuid.uuid4().hex[:12]}"

    if suffix == ".html":
        try:
            text_content = content.decode("utf-8")
        except UnicodeDecodeError:
            text_content = content.decode("gbk", errors="ignore")
        parsed = parse_html_auto(text_content)
        target = UPLOAD_DIR / f"{preview_id}_{filename}"
        target.write_text(text_content, encoding="utf-8")

    elif suffix == ".csv":
        try:
            text_content = content.decode("utf-8")
        except UnicodeDecodeError:
            text_content = content.decode("gbk", errors="ignore")
        conversations = parse_csv_text(text_content)
        if not conversations:
            raise HTTPException(
                status_code=400,
                detail="CSV 解析失败：请确保包含 role 和 content 列。支持的角色值：patient/患者/访客、counselor/咨询师/客服/医生",
            )
        parsed = conversations[0]
        target = UPLOAD_DIR / f"{preview_id}_{filename}"
        target.write_text(text_content, encoding="utf-8")

    elif suffix == ".xlsx":
        conversations = parse_excel_bytes(content)
        if not conversations:
            raise HTTPException(
                status_code=400,
                detail="Excel 解析失败：请确保第一行包含 role 和 content 列标题",
            )
        parsed = conversations[0]
        target = UPLOAD_DIR / f"{preview_id}_{filename}"
        target.write_bytes(content)

    else:
        raise HTTPException(status_code=400, detail="不支持的文件格式")

    messages = [
        MessageItem(
            sequence=m.sequence,
            role=m.role,
            content_type=m.content_type,
            content=m.content,
            sender_name=m.sender_name,
            original_time=m.original_time,
        )
        for m in parsed.messages
    ]

    qr = parsed.quality_report
    quality_report = None
    if qr:
        quality_report = ImportQualityReport(
            total_messages=qr.total_messages,
            patient_count=qr.patient_count,
            counselor_count=qr.counselor_count,
            text_count=qr.text_count,
            image_count=qr.image_count,
            audio_count=qr.audio_count,
            skipped_empty=qr.skipped_empty,
            role_alternation_rate=qr.role_alternation_rate,
            unique_patient_names=qr.unique_patient_names,
            unique_counselor_names=qr.unique_counselor_names,
            name_collision=qr.name_collision,
            quality_score=qr.quality_score,
            warnings=qr.warnings,
        )

    await save_preview(
        db,
        preview_id,
        {
            "preview_id": preview_id,
            "source_file": str(target.name),
            "patient_name": parsed.patient_name,
            "counselor_name": parsed.counselor_name,
            "message_count": len(messages),
            "messages": [m.model_dump() for m in messages],
        },
    )

    return ApiResponse(
        code=200,
        message="success",
        data=UploadPreviewData(
            preview_id=preview_id,
            source_file=str(target.name),
            patient_name=parsed.patient_name,
            counselor_name=parsed.counselor_name,
            message_count=len(messages),
            messages=messages,
            quality_report=quality_report,
        ),
    )


@router.post("/confirm", response_model=ApiResponse)
async def confirm_import(
    payload: ConfirmImportRequest,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="quiz:confirm_import",
        required_roles={"admin", "super_admin"},
        request=request,
        target_tenant_id=(int(current_user.tenant_id) if current_user.tenant_id else None),
        target_hospital_id=payload.hospital_id,
        target_department_id=payload.department_id,
        target_type="quiz",
        extra_detail={"scope": payload.scope},
    )
    tenant_id = ensure_tenant_bound(current_user)
    preview = await load_preview(db, payload.preview_id)
    if not preview:
        raise HTTPException(status_code=404, detail="preview_id 不存在或已过期")

    if payload.scope == "common":
        if current_user.role != "super_admin":
            raise HTTPException(status_code=403, detail="仅超级管理员可导入通用案例库")
        target_hospital_id = None
        target_department_id = None
    elif payload.scope == "department":
        accessible_dept_ids = await get_accessible_department_ids(current_user, db)
        if current_user.role in {"super_admin"} or current_user.is_all_hospitals:
            target_department_id = payload.department_id
            if not target_department_id:
                raise HTTPException(status_code=400, detail="科室专属案例库必须选择所属科室")
        else:
            target_department_id = payload.department_id or (accessible_dept_ids[0] if accessible_dept_ids else None)
            if not target_department_id or target_department_id not in accessible_dept_ids:
                raise HTTPException(status_code=403, detail="无权导入到该科室")
        department = (
            await db.execute(
                select(Department).where(Department.id == target_department_id, Department.tenant_id == tenant_id)
            )
        ).scalars().first()
        if not department:
            raise HTTPException(status_code=404, detail="所属科室不存在")
        target_hospital_id = department.hospital_id
    else:
        if current_user.role == "super_admin":
            if not payload.hospital_id:
                raise HTTPException(status_code=400, detail="医院专属案例库必须选择所属医院")
            target_hospital_id = payload.hospital_id
        else:
            accessible_ids = await get_accessible_hospital_ids(current_user, db)
            target_hospital_id = payload.hospital_id or (accessible_ids[0] if accessible_ids else None)
            if not target_hospital_id or target_hospital_id not in accessible_ids:
                raise HTTPException(status_code=403, detail="无权导入到该医院")
        hospital = (
            await db.execute(select(Hospital).where(Hospital.id == target_hospital_id, Hospital.tenant_id == tenant_id))
        ).scalars().first()
        if not hospital:
            raise HTTPException(status_code=404, detail="所属医院不存在")
        target_department_id = None

    preview_messages = preview.get("messages", [])
    content_hash = _build_content_hash_from_preview(preview_messages)
    duplicate = await _find_duplicate_quiz(
        db,
        tenant_id=tenant_id,
        scope=payload.scope,
        hospital_id=target_hospital_id,
        department_id=target_department_id,
        chat_type=payload.chat_type,
        message_count=int(preview.get("message_count", 0)),
        content_hash=content_hash,
    )
    if duplicate:
        raise HTTPException(
            status_code=409,
            detail=f"检测到重复案例：编号{duplicate.id}《{duplicate.title}》。建议改用“更新已有案例版本”或跳过。",
        )

    quiz = Quiz(
        tenant_id=tenant_id,
        title=payload.title,
        scope=payload.scope,
        hospital_id=target_hospital_id,
        department_id=target_department_id,
        chat_type=payload.chat_type,
        description=payload.description,
        category=payload.category,
        difficulty=payload.difficulty,
        tags=payload.tags,
        patient_name=preview.get("patient_name"),
        counselor_name=preview.get("counselor_name"),
        message_count=preview.get("message_count", 0),
        source_file=preview.get("source_file"),
        content_hash=content_hash,
        is_active=True,
        is_deleted=False,
        created_by=current_user.id,
    )
    db.add(quiz)
    await db.flush()

    for item in preview_messages:
        db.add(
            Message(
                tenant_id=tenant_id,
                quiz_id=quiz.id,
                sequence=item["sequence"],
                role=item["role"],
                content_type=item["content_type"],
                content=item["content"],
                sender_name=item.get("sender_name"),
                original_time=_parse_original_time(item.get("original_time")),
            )
        )

    await _create_version_snapshot(
        db,
        quiz,
        source_file=quiz.source_file,
        message_count=quiz.message_count,
        created_by=current_user.id,
    )
    await append_audit_log(
        db,
        action="quiz_import",
        user_id=current_user.id,
        target_type="quiz",
        target_id=quiz.id,
        hospital_id=target_hospital_id,
        department_id=target_department_id,
        detail={
            "title": quiz.title,
            "scope": quiz.scope,
            "chat_type": quiz.chat_type,
            "message_count": quiz.message_count,
            "source_file": quiz.source_file,
        },
        ip=get_request_ip(request),
    )
    await delete_preview(db, payload.preview_id)

    await db.commit()

    return ApiResponse(
        code=200,
        message="success",
        data=ConfirmImportData(
            quiz_id=quiz.id,
            title=quiz.title,
            message_count=quiz.message_count,
        ),
    )


@router.post("/reparse/batch", response_model=ApiResponse)
async def batch_reparse_quizzes(
    payload: BatchReparseRequest,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="quiz:batch_reparse",
        required_roles={"admin", "super_admin"},
        request=request,
        target_tenant_id=(int(current_user.tenant_id) if current_user.tenant_id else None),
        target_hospital_id=payload.hospital_id,
        target_department_id=payload.department_id,
        target_type="quiz",
        extra_detail={"scope": payload.scope, "limit": payload.limit},
    )
    quizzes = await _load_reparse_quizzes(payload, current_user, db)

    updated = 0
    skipped = 0
    failed = 0
    details: list[dict] = []

    for quiz in quizzes:
        source_file = (quiz.source_file or "").strip()
        if not source_file:
            skipped += 1
            details.append({"quiz_id": quiz.id, "title": quiz.title, "status": "skipped", "reason": "缺少 source_file"})
            continue
        source_path = UPLOAD_DIR / source_file
        if not source_path.exists():
            skipped += 1
            details.append({"quiz_id": quiz.id, "title": quiz.title, "status": "skipped", "reason": "源 HTML 不存在"})
            continue
        try:
            html_text = source_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            html_text = source_path.read_text(encoding="gbk", errors="ignore")
        except Exception as exc:
            failed += 1
            details.append({"quiz_id": quiz.id, "title": quiz.title, "status": "failed", "reason": str(exc)})
            continue

        try:
            parsed = parse_vel_html(html_text)
            preview_messages = _build_preview_messages_from_parsed(parsed)
            new_hash = _build_content_hash_from_preview(preview_messages)
            old_hash = quiz.content_hash or ""
            if old_hash and old_hash == new_hash:
                skipped += 1
                details.append({"quiz_id": quiz.id, "title": quiz.title, "status": "skipped", "reason": "内容无变化"})
                continue

            old_messages = (
                await db.execute(select(Message).where(Message.quiz_id == quiz.id, Message.tenant_id == quiz.tenant_id))
            ).scalars().all()
            for m in old_messages:
                await db.delete(m)
            for item in preview_messages:
                db.add(
                    Message(
                        tenant_id=quiz.tenant_id,
                        quiz_id=quiz.id,
                        sequence=item["sequence"],
                        role=item["role"],
                        content_type=item["content_type"],
                        content=item["content"],
                        sender_name=item.get("sender_name"),
                        original_time=_parse_original_time(item.get("original_time")),
                    )
                )
            quiz.patient_name = parsed.patient_name
            quiz.counselor_name = parsed.counselor_name
            quiz.message_count = len(preview_messages)
            quiz.content_hash = new_hash
            quiz.source_file = source_file
            await _create_version_snapshot(
                db,
                quiz,
                source_file=quiz.source_file,
                message_count=quiz.message_count,
                created_by=current_user.id,
            )
            updated += 1
            details.append({"quiz_id": quiz.id, "title": quiz.title, "status": "updated", "message_count": quiz.message_count})
        except Exception as exc:
            failed += 1
            details.append({"quiz_id": quiz.id, "title": quiz.title, "status": "failed", "reason": str(exc)})

    await append_audit_log(
        db,
        action="quiz_batch_reparse",
        user_id=current_user.id,
        target_type="quiz",
        target_id=None,
        hospital_id=payload.hospital_id,
        department_id=payload.department_id,
        detail={
            "scope": payload.scope,
            "chat_type": payload.chat_type,
            "only_legacy_or_empty_hash": payload.only_legacy_or_empty_hash,
            "matched": len(quizzes),
            "updated": updated,
            "skipped": skipped,
            "failed": failed,
        },
        ip=get_request_ip(request),
    )
    await db.commit()

    return ApiResponse(
        code=200,
        message="success",
        data=BatchReparseData(
            matched=len(quizzes),
            processed=updated + skipped + failed,
            updated=updated,
            skipped=skipped,
            failed=failed,
            detail=details[:200],
        ),
    )


@router.post("/reparse/batch/estimate", response_model=ApiResponse)
async def estimate_batch_reparse_quizzes(
    request: Request,
    payload: BatchReparseRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="quiz:batch_reparse_estimate",
        required_roles={"admin", "super_admin"},
        request=request,
        target_tenant_id=(int(current_user.tenant_id) if current_user.tenant_id else None),
        target_hospital_id=payload.hospital_id,
        target_department_id=payload.department_id,
        target_type="quiz",
        extra_detail={"scope": payload.scope, "limit": payload.limit},
    )
    quizzes = await _load_reparse_quizzes(payload, current_user, db)
    return ApiResponse(
        code=200,
        message="success",
        data=BatchReparseEstimateData(
            matched=len(quizzes),
            limit=payload.limit,
            only_legacy_or_empty_hash=payload.only_legacy_or_empty_hash,
        ),
    )


@router.get("", response_model=ApiResponse)
async def get_quiz_list(
    request: Request,
    current_user: User = Depends(require_admin),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=500),
    keyword: str | None = None,
    chat_type: str | None = Query(default=None, pattern="^(active|passive)$"),
    scope: str | None = Query(default=None, pattern="^(common|hospital|department)$"),
    hospital_id: int | None = None,
    department_id: int | None = None,
    category: str | None = None,
    deleted_only: bool = False,
    include_deleted: bool = False,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="quiz:list",
        required_roles={"admin", "super_admin"},
        request=request,
        target_tenant_id=(int(current_user.tenant_id) if current_user.tenant_id else None),
        target_hospital_id=hospital_id,
        target_department_id=department_id,
        target_type="quiz",
        extra_detail={"scope": scope, "chat_type": chat_type},
    )
    tenant_id = ensure_tenant_bound(current_user)
    filters = [Quiz.tenant_id == tenant_id]
    if deleted_only:
        filters.append(Quiz.is_deleted.is_(True))
    elif not include_deleted:
        filters.append(Quiz.is_deleted.is_(False))
    if keyword:
        filters.append(Quiz.title.like(f"%{keyword}%"))
    if category:
        filters.append(Quiz.category == category)
    if chat_type:
        filters.append(Quiz.chat_type == chat_type)
    if scope:
        filters.append(Quiz.scope == scope)
    if department_id:
        filters.append(Quiz.department_id == department_id)
    if current_user.role == "super_admin" or current_user.is_all_hospitals:
        if hospital_id:
            filters.append(Quiz.hospital_id == hospital_id)
    else:
        accessible_dept_ids = await get_accessible_department_ids(current_user, db)
        accessible_ids = await get_accessible_hospital_ids(current_user, db)
        filters.append(
            (Quiz.scope == "common")
            | (Quiz.department_id.in_(accessible_dept_ids))
            | (Quiz.hospital_id.in_(accessible_ids))
        )

    count_stmt = select(func.count(Quiz.id)).where(*filters)
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = (
        select(Quiz)
        .where(*filters)
        .order_by(Quiz.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.execute(stmt)).scalars().all()
    hospital_ids = sorted({q.hospital_id for q in rows if q.hospital_id})
    department_ids = sorted({q.department_id for q in rows if q.department_id})
    hospital_map: dict[int, str] = {}
    department_map: dict[int, str] = {}
    if hospital_ids:
        hospitals = (
            await db.execute(select(Hospital).where(Hospital.id.in_(hospital_ids), Hospital.tenant_id == tenant_id))
        ).scalars().all()
        hospital_map = {h.id: h.name for h in hospitals}
    if department_ids:
        departments = (
            await db.execute(select(Department).where(Department.id.in_(department_ids), Department.tenant_id == tenant_id))
        ).scalars().all()
        department_map = {d.id: d.name for d in departments}

    items = [
        QuizListItem(
            id=q.id,
            title=q.title,
            scope=q.scope,
            hospital_id=q.hospital_id,
            hospital_name=hospital_map.get(q.hospital_id or 0),
            department_id=q.department_id,
            department_name=department_map.get(q.department_id or 0),
            chat_type=q.chat_type,
            category=q.category,
            difficulty=q.difficulty,
            tags=q.tags,
            patient_name=q.patient_name,
            counselor_name=q.counselor_name,
            message_count=q.message_count,
            is_active=q.is_active,
            is_deleted=bool(q.is_deleted),
            created_at=q.created_at,
        )
        for q in rows
    ]
    return ApiResponse(
        code=200,
        message="success",
        data=PageData(items=items, total=total, page=page, page_size=page_size),
    )


@router.get("/meta/options", response_model=ApiResponse)
async def get_quiz_meta_options(
    request: Request,
    current_user: User = Depends(require_admin),
    scope: str | None = Query(default=None, pattern="^(common|hospital|department)$"),
    hospital_id: int | None = None,
    department_id: int | None = None,
    chat_type: str | None = Query(default=None, pattern="^(active|passive)$"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="quiz:meta_options",
        required_roles={"admin", "super_admin"},
        request=request,
        target_tenant_id=(int(current_user.tenant_id) if current_user.tenant_id else None),
        target_hospital_id=hospital_id,
        target_department_id=department_id,
        target_type="quiz",
        extra_detail={"scope": scope, "chat_type": chat_type},
    )
    tenant_id = ensure_tenant_bound(current_user)
    accessible_dept_ids = await get_accessible_department_ids(current_user, db)
    accessible_ids = await get_accessible_hospital_ids(current_user, db)
    filters = [Quiz.tenant_id == tenant_id, Quiz.is_deleted.is_(False)]
    if scope:
        filters.append(Quiz.scope == scope)
    if hospital_id:
        filters.append(Quiz.hospital_id == hospital_id)
    if department_id:
        filters.append(Quiz.department_id == department_id)
    if chat_type:
        filters.append(Quiz.chat_type == chat_type)
    filters.append(_build_quiz_access_filter(current_user, accessible_dept_ids, accessible_ids))

    rows = (
        await db.execute(select(Quiz.category, Quiz.tags).where(*filters))
    ).all()
    category_counter: dict[str, int] = {}
    tag_counter: dict[str, int] = {}
    for row in rows:
        category = (row[0] or "").strip()
        if category:
            category_counter[category] = category_counter.get(category, 0) + 1
        for tag in _split_tags(row[1]):
            tag_counter[tag] = tag_counter.get(tag, 0) + 1
    categories = [
        QuizMetaOptionItem(name=name, count=count)
        for name, count in sorted(category_counter.items(), key=lambda x: (-x[1], x[0]))
    ]
    tags = [
        QuizMetaOptionItem(name=name, count=count)
        for name, count in sorted(tag_counter.items(), key=lambda x: (-x[1], x[0]))
    ]
    return ApiResponse(
        code=200,
        message="success",
        data=QuizMetaOptionsData(categories=categories, tags=tags),
    )


@router.post("/meta/category/rename", response_model=ApiResponse)
async def rename_quiz_category(
    payload: CategoryRenameRequest,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="quiz:meta_category_rename",
        required_roles={"admin", "super_admin"},
        request=request,
        target_tenant_id=(int(current_user.tenant_id) if current_user.tenant_id else None),
        target_hospital_id=payload.hospital_id,
        target_department_id=payload.department_id,
        target_type="quiz",
        extra_detail={"scope": payload.scope},
    )
    tenant_id = ensure_tenant_bound(current_user)
    old_name = payload.old_name.strip()
    new_name = payload.new_name.strip()
    if not old_name or not new_name:
        raise HTTPException(status_code=400, detail="分类名称不能为空")
    quizzes = await _load_quizzes_for_meta_operation(
        db=db,
        current_user=current_user,
        tenant_id=tenant_id,
        scope=payload.scope,
        hospital_id=payload.hospital_id,
        department_id=payload.department_id,
        chat_type=payload.chat_type,
    )
    matched = 0
    updated = 0
    for quiz in quizzes:
        current = (quiz.category or "").strip()
        if current != old_name:
            continue
        matched += 1
        if current != new_name:
            quiz.category = new_name
            updated += 1
    await append_audit_log(
        db,
        action="quiz_meta_category_rename",
        user_id=current_user.id,
        target_type="quiz",
        detail={"old_name": old_name, "new_name": new_name, "matched": matched, "updated": updated},
        ip=get_request_ip(request),
    )
    await db.commit()
    return ApiResponse(code=200, message="success", data=QuizMetaOperateData(matched=matched, updated=updated))


@router.post("/meta/category/merge", response_model=ApiResponse)
async def merge_quiz_category(
    payload: CategoryMergeRequest,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="quiz:meta_category_merge",
        required_roles={"admin", "super_admin"},
        request=request,
        target_tenant_id=(int(current_user.tenant_id) if current_user.tenant_id else None),
        target_hospital_id=payload.hospital_id,
        target_department_id=payload.department_id,
        target_type="quiz",
        extra_detail={"scope": payload.scope},
    )
    tenant_id = ensure_tenant_bound(current_user)
    source_names = _normalize_names(payload.source_names)
    target_name = payload.target_name.strip()
    if not source_names:
        raise HTTPException(status_code=400, detail="请至少选择一个来源分类")
    if not target_name:
        raise HTTPException(status_code=400, detail="目标分类不能为空")
    source_set = {name.lower() for name in source_names}
    quizzes = await _load_quizzes_for_meta_operation(
        db=db,
        current_user=current_user,
        tenant_id=tenant_id,
        scope=payload.scope,
        hospital_id=payload.hospital_id,
        department_id=payload.department_id,
        chat_type=payload.chat_type,
    )
    matched = 0
    updated = 0
    for quiz in quizzes:
        current = (quiz.category or "").strip()
        if not current or current.lower() not in source_set:
            continue
        matched += 1
        if current != target_name:
            quiz.category = target_name
            updated += 1
    await append_audit_log(
        db,
        action="quiz_meta_category_merge",
        user_id=current_user.id,
        target_type="quiz",
        detail={"source_names": source_names, "target_name": target_name, "matched": matched, "updated": updated},
        ip=get_request_ip(request),
    )
    await db.commit()
    return ApiResponse(code=200, message="success", data=QuizMetaOperateData(matched=matched, updated=updated))


@router.post("/meta/category/delete", response_model=ApiResponse)
async def delete_quiz_category(
    payload: CategoryDeleteRequest,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="quiz:meta_category_delete",
        required_roles={"admin", "super_admin"},
        request=request,
        target_tenant_id=(int(current_user.tenant_id) if current_user.tenant_id else None),
        target_hospital_id=payload.hospital_id,
        target_department_id=payload.department_id,
        target_type="quiz",
        extra_detail={"scope": payload.scope},
    )
    tenant_id = ensure_tenant_bound(current_user)
    names = {item.lower() for item in _normalize_names(payload.names)}
    if not names:
        raise HTTPException(status_code=400, detail="请至少选择一个分类")
    quizzes = await _load_quizzes_for_meta_operation(
        db=db,
        current_user=current_user,
        tenant_id=tenant_id,
        scope=payload.scope,
        hospital_id=payload.hospital_id,
        department_id=payload.department_id,
        chat_type=payload.chat_type,
    )
    matched = 0
    updated = 0
    for quiz in quizzes:
        current = (quiz.category or "").strip()
        if not current or current.lower() not in names:
            continue
        matched += 1
        if quiz.category is not None:
            quiz.category = None
            updated += 1
    await append_audit_log(
        db,
        action="quiz_meta_category_delete",
        user_id=current_user.id,
        target_type="quiz",
        detail={"names": sorted(names), "matched": matched, "updated": updated},
        ip=get_request_ip(request),
    )
    await db.commit()
    return ApiResponse(code=200, message="success", data=QuizMetaOperateData(matched=matched, updated=updated))


@router.post("/meta/tag/rename", response_model=ApiResponse)
async def rename_quiz_tag(
    payload: TagRenameRequest,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="quiz:meta_tag_rename",
        required_roles={"admin", "super_admin"},
        request=request,
        target_tenant_id=(int(current_user.tenant_id) if current_user.tenant_id else None),
        target_hospital_id=payload.hospital_id,
        target_department_id=payload.department_id,
        target_type="quiz",
        extra_detail={"scope": payload.scope},
    )
    tenant_id = ensure_tenant_bound(current_user)
    old_name = payload.old_name.strip()
    new_name = payload.new_name.strip()
    if not old_name or not new_name:
        raise HTTPException(status_code=400, detail="标签名称不能为空")
    quizzes = await _load_quizzes_for_meta_operation(
        db=db,
        current_user=current_user,
        tenant_id=tenant_id,
        scope=payload.scope,
        hospital_id=payload.hospital_id,
        department_id=payload.department_id,
        chat_type=payload.chat_type,
    )
    matched = 0
    updated = 0
    old_key = old_name.lower()
    for quiz in quizzes:
        tags = _split_tags(quiz.tags)
        if old_key not in {item.lower() for item in tags}:
            continue
        matched += 1
        next_tags: list[str] = []
        seen: set[str] = set()
        for item in tags:
            current = new_name if item.lower() == old_key else item
            key = current.lower()
            if key in seen:
                continue
            seen.add(key)
            next_tags.append(current)
        next_text = _join_tags(next_tags)
        if (quiz.tags or None) != next_text:
            quiz.tags = next_text
            updated += 1
    await append_audit_log(
        db,
        action="quiz_meta_tag_rename",
        user_id=current_user.id,
        target_type="quiz",
        detail={"old_name": old_name, "new_name": new_name, "matched": matched, "updated": updated},
        ip=get_request_ip(request),
    )
    await db.commit()
    return ApiResponse(code=200, message="success", data=QuizMetaOperateData(matched=matched, updated=updated))


@router.post("/meta/tag/merge", response_model=ApiResponse)
async def merge_quiz_tag(
    payload: TagMergeRequest,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="quiz:meta_tag_merge",
        required_roles={"admin", "super_admin"},
        request=request,
        target_tenant_id=(int(current_user.tenant_id) if current_user.tenant_id else None),
        target_hospital_id=payload.hospital_id,
        target_department_id=payload.department_id,
        target_type="quiz",
        extra_detail={"scope": payload.scope},
    )
    tenant_id = ensure_tenant_bound(current_user)
    source_names = _normalize_names(payload.source_names)
    target_name = payload.target_name.strip()
    if not source_names:
        raise HTTPException(status_code=400, detail="请至少选择一个来源标签")
    if not target_name:
        raise HTTPException(status_code=400, detail="目标标签不能为空")
    source_set = {name.lower() for name in source_names}
    quizzes = await _load_quizzes_for_meta_operation(
        db=db,
        current_user=current_user,
        tenant_id=tenant_id,
        scope=payload.scope,
        hospital_id=payload.hospital_id,
        department_id=payload.department_id,
        chat_type=payload.chat_type,
    )
    matched = 0
    updated = 0
    for quiz in quizzes:
        tags = _split_tags(quiz.tags)
        if not tags:
            continue
        lowered = {item.lower() for item in tags}
        if not lowered.intersection(source_set):
            continue
        matched += 1
        next_tags = [item for item in tags if item.lower() not in source_set]
        if target_name.lower() not in {item.lower() for item in next_tags}:
            next_tags.append(target_name)
        next_text = _join_tags(next_tags)
        if (quiz.tags or None) != next_text:
            quiz.tags = next_text
            updated += 1
    await append_audit_log(
        db,
        action="quiz_meta_tag_merge",
        user_id=current_user.id,
        target_type="quiz",
        detail={"source_names": source_names, "target_name": target_name, "matched": matched, "updated": updated},
        ip=get_request_ip(request),
    )
    await db.commit()
    return ApiResponse(code=200, message="success", data=QuizMetaOperateData(matched=matched, updated=updated))


@router.post("/meta/tag/delete", response_model=ApiResponse)
async def delete_quiz_tag(
    payload: TagDeleteRequest,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="quiz:meta_tag_delete",
        required_roles={"admin", "super_admin"},
        request=request,
        target_tenant_id=(int(current_user.tenant_id) if current_user.tenant_id else None),
        target_hospital_id=payload.hospital_id,
        target_department_id=payload.department_id,
        target_type="quiz",
        extra_detail={"scope": payload.scope},
    )
    tenant_id = ensure_tenant_bound(current_user)
    names = {item.lower() for item in _normalize_names(payload.names)}
    if not names:
        raise HTTPException(status_code=400, detail="请至少选择一个标签")
    quizzes = await _load_quizzes_for_meta_operation(
        db=db,
        current_user=current_user,
        tenant_id=tenant_id,
        scope=payload.scope,
        hospital_id=payload.hospital_id,
        department_id=payload.department_id,
        chat_type=payload.chat_type,
    )
    matched = 0
    updated = 0
    for quiz in quizzes:
        tags = _split_tags(quiz.tags)
        if not tags:
            continue
        if not any(item.lower() in names for item in tags):
            continue
        matched += 1
        next_tags = [item for item in tags if item.lower() not in names]
        next_text = _join_tags(next_tags)
        if (quiz.tags or None) != next_text:
            quiz.tags = next_text
            updated += 1
    await append_audit_log(
        db,
        action="quiz_meta_tag_delete",
        user_id=current_user.id,
        target_type="quiz",
        detail={"names": sorted(names), "matched": matched, "updated": updated},
        ip=get_request_ip(request),
    )
    await db.commit()
    return ApiResponse(code=200, message="success", data=QuizMetaOperateData(matched=matched, updated=updated))


@router.get("/{quiz_id}", response_model=ApiResponse)
async def get_quiz_detail(
    quiz_id: int,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    tenant_id = ensure_tenant_bound(current_user)
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="quiz:read",
        required_roles={"admin", "super_admin"},
        request=request,
        target_tenant_id=tenant_id,
        target_type="quiz",
        target_id=quiz_id,
    )
    quiz_stmt = select(Quiz).where(Quiz.id == quiz_id, Quiz.is_deleted.is_(False), Quiz.tenant_id == tenant_id)
    quiz = (await db.execute(quiz_stmt)).scalars().first()
    if not quiz:
        raise HTTPException(status_code=404, detail="案例不存在")
    if current_user.role != "super_admin" and not current_user.is_all_hospitals:
        accessible_dept_ids = await get_accessible_department_ids(current_user, db)
        accessible_ids = await get_accessible_hospital_ids(current_user, db)
        if quiz.scope != "common" and not (
            (quiz.department_id and quiz.department_id in accessible_dept_ids)
            or (quiz.hospital_id and quiz.hospital_id in accessible_ids)
        ):
            raise HTTPException(status_code=403, detail="无权查看其他医院案例库")

    msg_stmt = (
        select(Message)
        .where(Message.quiz_id == quiz_id, Message.tenant_id == tenant_id)
        .order_by(Message.sequence.asc(), Message.id.asc())
    )
    messages = (await db.execute(msg_stmt)).scalars().all()

    msg_items = [
        MessageItem(
            sequence=m.sequence,
            role=m.role,
            content_type=m.content_type,
            content=m.content,
            sender_name=m.sender_name or "",
            original_time=m.original_time.strftime("%Y-%m-%d %H:%M:%S")
            if m.original_time
            else None,
        )
        for m in messages
    ]

    name_row = (
        await db.execute(
            select(Hospital.name.label("hospital_name"), Department.name.label("department_name"))
            .select_from(Quiz)
            .outerjoin(Hospital, Hospital.id == Quiz.hospital_id)
            .outerjoin(Department, Department.id == Quiz.department_id)
            .where(Quiz.id == quiz.id, Quiz.tenant_id == tenant_id)
            .limit(1)
        )
    ).first()
    hospital_name = str(name_row[0]) if name_row and name_row[0] else None
    department_name = str(name_row[1]) if name_row and name_row[1] else None
    versions = (
        await db.execute(
            select(QuizVersion)
            .where(QuizVersion.quiz_id == quiz.id, QuizVersion.tenant_id == tenant_id)
            .order_by(QuizVersion.version_no.desc())
        )
    ).scalars().all()

    return ApiResponse(
        code=200,
        message="success",
        data=QuizDetailData(
            id=quiz.id,
            title=quiz.title,
            scope=quiz.scope,
            hospital_id=quiz.hospital_id,
            hospital_name=hospital_name,
            department_id=quiz.department_id,
            department_name=department_name,
            chat_type=quiz.chat_type,
            description=quiz.description,
            category=quiz.category,
            difficulty=quiz.difficulty,
            tags=quiz.tags,
            patient_name=quiz.patient_name,
            counselor_name=quiz.counselor_name,
            message_count=quiz.message_count,
            source_file=quiz.source_file,
            is_active=quiz.is_active,
            is_deleted=bool(quiz.is_deleted),
            created_at=quiz.created_at,
            versions=[
                QuizVersionItem(
                    id=v.id,
                    version_no=v.version_no,
                    source_file=v.source_file,
                    message_count=v.message_count,
                    created_by=v.created_by,
                    created_at=v.created_at,
                )
                for v in versions
            ],
            messages=msg_items,
        ),
    )


@router.post("/{quiz_id}/versions/confirm", response_model=ApiResponse)
async def confirm_quiz_new_version(
    quiz_id: int,
    payload: ConfirmImportRequest,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="quiz:update_version",
        required_roles={"admin", "super_admin"},
        request=request,
        target_tenant_id=(int(current_user.tenant_id) if current_user.tenant_id else None),
        target_type="quiz",
        target_id=quiz_id,
    )
    tenant_id = ensure_tenant_bound(current_user)
    preview = await load_preview(db, payload.preview_id)
    if not preview:
        raise HTTPException(status_code=404, detail="preview_id 不存在或已过期")
    quiz = (
        await db.execute(
            select(Quiz).where(Quiz.id == quiz_id, Quiz.is_deleted.is_(False), Quiz.tenant_id == tenant_id)
        )
    ).scalars().first()
    if not quiz:
        raise HTTPException(status_code=404, detail="案例不存在")

    if current_user.role != "super_admin" and not current_user.is_all_hospitals:
        accessible_dept_ids = await get_accessible_department_ids(current_user, db)
        accessible_ids = await get_accessible_hospital_ids(current_user, db)
        if quiz.scope != "common" and not (
            (quiz.department_id and quiz.department_id in accessible_dept_ids)
            or (quiz.hospital_id and quiz.hospital_id in accessible_ids)
        ):
            raise HTTPException(status_code=403, detail="无权更新其他医院案例")

    if payload.scope != quiz.scope:
        raise HTTPException(status_code=400, detail="版本更新时案例库范围必须与原案例一致")
    if quiz.scope == "common":
        if current_user.role != "super_admin":
            raise HTTPException(status_code=403, detail="仅超级管理员可更新通用案例库")
        quiz.hospital_id = None
        quiz.department_id = None
    elif quiz.scope == "department":
        accessible_dept_ids = await get_accessible_department_ids(current_user, db)
        if current_user.role == "super_admin" or current_user.is_all_hospitals:
            target_department_id = payload.department_id or quiz.department_id
            if not target_department_id:
                raise HTTPException(status_code=400, detail="科室专属案例库必须指定所属科室")
        else:
            target_department_id = payload.department_id or quiz.department_id
            if not target_department_id or target_department_id not in accessible_dept_ids:
                raise HTTPException(status_code=403, detail="无权设置为该科室")
        department = (
            await db.execute(
                select(Department).where(Department.id == target_department_id, Department.tenant_id == tenant_id)
            )
        ).scalars().first()
        if not department:
            raise HTTPException(status_code=404, detail="所属科室不存在")
        quiz.department_id = target_department_id
        quiz.hospital_id = department.hospital_id
    else:
        if current_user.role == "super_admin" or current_user.is_all_hospitals:
            target_hospital_id = payload.hospital_id or quiz.hospital_id
            if not target_hospital_id:
                raise HTTPException(status_code=400, detail="医院专属案例库必须指定所属医院")
        else:
            accessible_ids = await get_accessible_hospital_ids(current_user, db)
            target_hospital_id = payload.hospital_id or quiz.hospital_id
            if not target_hospital_id or target_hospital_id not in accessible_ids:
                raise HTTPException(status_code=403, detail="无权设置为该医院")
        hospital = (
            await db.execute(select(Hospital).where(Hospital.id == target_hospital_id, Hospital.tenant_id == tenant_id))
        ).scalars().first()
        if not hospital:
            raise HTTPException(status_code=404, detail="所属医院不存在")
        quiz.hospital_id = target_hospital_id
        quiz.department_id = None

    quiz.title = payload.title
    quiz.chat_type = payload.chat_type
    quiz.description = payload.description
    quiz.category = payload.category
    quiz.difficulty = payload.difficulty
    quiz.tags = payload.tags
    quiz.patient_name = preview.get("patient_name")
    quiz.counselor_name = preview.get("counselor_name")
    quiz.message_count = preview.get("message_count", 0)
    quiz.source_file = preview.get("source_file")
    quiz.content_hash = _build_content_hash_from_preview(preview.get("messages", []))

    old_messages = (
        await db.execute(select(Message).where(Message.quiz_id == quiz.id, Message.tenant_id == tenant_id))
    ).scalars().all()
    for m in old_messages:
        await db.delete(m)

    for item in preview.get("messages", []):
        db.add(
            Message(
                tenant_id=tenant_id,
                quiz_id=quiz.id,
                sequence=item["sequence"],
                role=item["role"],
                content_type=item["content_type"],
                content=item["content"],
                sender_name=item.get("sender_name"),
                original_time=_parse_original_time(item.get("original_time")),
            )
        )

    await _create_version_snapshot(
        db,
        quiz,
        source_file=quiz.source_file,
        message_count=quiz.message_count,
        created_by=current_user.id,
    )
    await append_audit_log(
        db,
        action="quiz_version_update",
        user_id=current_user.id,
        target_type="quiz",
        target_id=quiz.id,
        hospital_id=quiz.hospital_id,
        department_id=quiz.department_id,
        detail={
            "title": quiz.title,
            "scope": quiz.scope,
            "chat_type": quiz.chat_type,
            "message_count": quiz.message_count,
            "source_file": quiz.source_file,
        },
        ip=get_request_ip(request),
    )
    await delete_preview(db, payload.preview_id)
    await db.commit()
    return ApiResponse(
        code=200,
        message="success",
        data=ConfirmImportData(
            quiz_id=quiz.id,
            title=quiz.title,
            message_count=quiz.message_count,
        ),
    )


@router.put("/{quiz_id}", response_model=ApiResponse)
async def update_quiz_meta(
    quiz_id: int,
    payload: QuizUpdateRequest,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="quiz:update_meta",
        required_roles={"admin", "super_admin"},
        request=request,
        target_tenant_id=(int(current_user.tenant_id) if current_user.tenant_id else None),
        target_hospital_id=payload.hospital_id,
        target_department_id=payload.department_id,
        target_type="quiz",
        target_id=quiz_id,
    )
    tenant_id = ensure_tenant_bound(current_user)
    quiz = (
        await db.execute(
            select(Quiz).where(Quiz.id == quiz_id, Quiz.is_deleted.is_(False), Quiz.tenant_id == tenant_id)
        )
    ).scalars().first()
    if not quiz:
        raise HTTPException(status_code=404, detail="案例不存在")

    if current_user.role != "super_admin" and not current_user.is_all_hospitals:
        accessible_dept_ids = await get_accessible_department_ids(current_user, db)
        accessible_ids = await get_accessible_hospital_ids(current_user, db)
        if quiz.scope != "common" and not (
            (quiz.department_id and quiz.department_id in accessible_dept_ids)
            or (quiz.hospital_id and quiz.hospital_id in accessible_ids)
        ):
            raise HTTPException(status_code=403, detail="无权编辑其他医院案例")
        if payload.scope == "common":
            raise HTTPException(status_code=403, detail="仅超级管理员可设置为通用案例库")

    target_hospital_id: int | None
    target_department_id: int | None
    if payload.scope == "common":
        if current_user.role != "super_admin":
            raise HTTPException(status_code=403, detail="仅超级管理员可编辑通用案例库")
        target_hospital_id = None
        target_department_id = None
    elif payload.scope == "department":
        if not payload.department_id:
            raise HTTPException(status_code=400, detail="科室专属案例库必须选择所属科室")
        if current_user.role != "super_admin" and not current_user.is_all_hospitals:
            accessible_dept_ids = await get_accessible_department_ids(current_user, db)
            if payload.department_id not in accessible_dept_ids:
                raise HTTPException(status_code=403, detail="无权设置为该科室")
        department = (
            await db.execute(select(Department).where(Department.id == payload.department_id, Department.tenant_id == tenant_id))
        ).scalars().first()
        if not department:
            raise HTTPException(status_code=404, detail="所属科室不存在")
        target_department_id = department.id
        target_hospital_id = department.hospital_id
    else:
        if not payload.hospital_id:
            raise HTTPException(status_code=400, detail="医院专属案例库必须选择所属医院")
        if current_user.role != "super_admin" and not current_user.is_all_hospitals:
            accessible_ids = await get_accessible_hospital_ids(current_user, db)
            if payload.hospital_id not in accessible_ids:
                raise HTTPException(status_code=403, detail="无权设置为该医院")
        hospital = (
            await db.execute(select(Hospital).where(Hospital.id == payload.hospital_id, Hospital.tenant_id == tenant_id))
        ).scalars().first()
        if not hospital:
            raise HTTPException(status_code=404, detail="所属医院不存在")
        target_hospital_id = hospital.id
        target_department_id = None

    quiz.title = payload.title.strip()
    quiz.scope = payload.scope
    quiz.hospital_id = target_hospital_id
    quiz.department_id = target_department_id
    quiz.chat_type = payload.chat_type
    quiz.category = (payload.category or "").strip() or None
    quiz.difficulty = payload.difficulty
    quiz.tags = (payload.tags or "").strip() or None
    quiz.description = (payload.description or "").strip() or None
    quiz.patient_name = (payload.patient_name or "").strip() or None
    quiz.counselor_name = (payload.counselor_name or "").strip() or None

    await append_audit_log(
        db,
        action="quiz_meta_update",
        user_id=current_user.id,
        target_type="quiz",
        target_id=quiz.id,
        hospital_id=quiz.hospital_id,
        department_id=quiz.department_id,
        detail={
            "title": quiz.title,
            "scope": quiz.scope,
            "chat_type": quiz.chat_type,
            "category": quiz.category,
            "difficulty": quiz.difficulty,
        },
        ip=get_request_ip(request),
    )
    await db.commit()
    return ApiResponse(
        code=200,
        message="success",
        data=QuizUpdateData(
            quiz_id=quiz.id,
            title=quiz.title,
            scope=quiz.scope,
            hospital_id=quiz.hospital_id,
            department_id=quiz.department_id,
            chat_type=quiz.chat_type,
            category=quiz.category,
            difficulty=quiz.difficulty,
            tags=quiz.tags,
            description=quiz.description,
            patient_name=quiz.patient_name,
            counselor_name=quiz.counselor_name,
        ),
    )


@router.post("/batch/meta/update", response_model=ApiResponse)
async def batch_update_quiz_meta(
    payload: BatchQuizMetaUpdateRequest,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="quiz:batch_update_meta",
        required_roles={"admin", "super_admin"},
        request=request,
        target_tenant_id=(int(current_user.tenant_id) if current_user.tenant_id else None),
        target_hospital_id=payload.hospital_id,
        target_department_id=payload.department_id,
        target_type="quiz",
        extra_detail={"scope": payload.scope},
    )
    tenant_id = ensure_tenant_bound(current_user)
    has_operation = bool(
        payload.clear_category
        or payload.clear_tags
        or payload.set_category is not None
        or payload.replace_tags is not None
        or payload.add_tags
        or payload.remove_tags
    )
    if not has_operation:
        raise HTTPException(status_code=400, detail="请至少指定一个批量修改动作")
    filters = [Quiz.tenant_id == tenant_id, Quiz.is_deleted.is_(False)]
    if payload.quiz_ids:
        filters.append(Quiz.id.in_(payload.quiz_ids))
    if payload.keyword:
        filters.append(Quiz.title.like(f"%{payload.keyword.strip()}%"))
    if payload.scope:
        filters.append(Quiz.scope == payload.scope)
    if payload.hospital_id:
        filters.append(Quiz.hospital_id == payload.hospital_id)
    if payload.department_id:
        filters.append(Quiz.department_id == payload.department_id)
    if payload.chat_type:
        filters.append(Quiz.chat_type == payload.chat_type)
    accessible_dept_ids = await get_accessible_department_ids(current_user, db)
    accessible_ids = await get_accessible_hospital_ids(current_user, db)
    filters.append(_build_quiz_access_filter(current_user, accessible_dept_ids, accessible_ids))
    rows = (await db.execute(select(Quiz).where(*filters))).scalars().all()
    updated = 0
    add_tags = _split_tags(",".join(payload.add_tags))
    remove_tags = {item.lower() for item in _split_tags(",".join(payload.remove_tags))}
    replace_tags = _split_tags(",".join(payload.replace_tags or [])) if payload.replace_tags is not None else None
    set_category = (payload.set_category or "").strip() or None
    for quiz in rows:
        changed = False
        if payload.clear_category:
            if quiz.category is not None:
                quiz.category = None
                changed = True
        elif payload.set_category is not None:
            if quiz.category != set_category:
                quiz.category = set_category
                changed = True

        if payload.clear_tags:
            if (quiz.tags or "").strip():
                quiz.tags = None
                changed = True
        else:
            current_tags = _split_tags(quiz.tags)
            if replace_tags is not None:
                next_tags = replace_tags
            else:
                next_tags = current_tags[:]
                for tag in add_tags:
                    if tag.lower() not in {item.lower() for item in next_tags}:
                        next_tags.append(tag)
                if remove_tags:
                    next_tags = [item for item in next_tags if item.lower() not in remove_tags]
            next_text = _join_tags(next_tags)
            if (quiz.tags or None) != next_text:
                quiz.tags = next_text
                changed = True
        if changed:
            updated += 1
    await append_audit_log(
        db,
        action="quiz_batch_meta_update",
        user_id=current_user.id,
        target_type="quiz",
        target_id=None,
        hospital_id=payload.hospital_id,
        department_id=payload.department_id,
        detail={
            "matched": len(rows),
            "updated": updated,
            "scope": payload.scope,
        },
        ip=get_request_ip(request),
    )
    await db.commit()
    return ApiResponse(
        code=200,
        message="success",
        data=BatchQuizMetaUpdateData(matched=len(rows), updated=updated),
    )


@router.delete("/{quiz_id}", response_model=ApiResponse)
async def soft_delete_quiz(
    quiz_id: int,
    request: Request,
    hard: bool = Query(default=False),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="quiz:delete",
        required_roles={"admin", "super_admin"},
        request=request,
        target_tenant_id=(int(current_user.tenant_id) if current_user.tenant_id else None),
        target_type="quiz",
        target_id=quiz_id,
        extra_detail={"hard": bool(hard)},
    )
    tenant_id = ensure_tenant_bound(current_user)
    quiz = (
        await db.execute(select(Quiz).where(Quiz.id == quiz_id, Quiz.tenant_id == tenant_id))
    ).scalars().first()
    if not quiz:
        raise HTTPException(status_code=404, detail="案例不存在")

    if current_user.role != "super_admin" and not current_user.is_all_hospitals:
        accessible_dept_ids = await get_accessible_department_ids(current_user, db)
        accessible_ids = await get_accessible_hospital_ids(current_user, db)
        if quiz.scope != "common" and not (
            (quiz.department_id and quiz.department_id in accessible_dept_ids)
            or (quiz.hospital_id and quiz.hospital_id in accessible_ids)
        ):
            raise HTTPException(status_code=403, detail="无权删除其他医院案例")
        if quiz.scope == "common":
            raise HTTPException(status_code=403, detail="无权删除通用案例库")

    if hard:
        if current_user.role != "super_admin":
            raise HTTPException(status_code=403, detail="仅超级管理员可彻底删除案例")
        if not quiz.is_deleted:
            raise HTTPException(status_code=400, detail="请先软删除后再彻底删除")
        practice_count = (
            await db.execute(select(func.count(Practice.id)).where(Practice.quiz_id == quiz.id, Practice.tenant_id == tenant_id))
        ).scalar_one()
        if practice_count > 0:
            raise HTTPException(status_code=400, detail="该案例已有训练记录，不能彻底删除")
        await append_audit_log(
            db,
            action="quiz_hard_delete",
            user_id=current_user.id,
            target_type="quiz",
            target_id=quiz.id,
            hospital_id=quiz.hospital_id,
            department_id=quiz.department_id,
            detail={
                "title": quiz.title,
                "scope": quiz.scope,
                "chat_type": quiz.chat_type,
            },
            ip=get_request_ip(request),
        )
        await db.delete(quiz)
        await db.commit()
        return ApiResponse(code=200, message="success", data=None)

    if quiz.is_deleted:
        return ApiResponse(code=200, message="success", data=None)

    quiz.is_deleted = True
    await append_audit_log(
        db,
        action="quiz_soft_delete",
        user_id=current_user.id,
        target_type="quiz",
        target_id=quiz.id,
        hospital_id=quiz.hospital_id,
        department_id=quiz.department_id,
        detail={
            "title": quiz.title,
            "scope": quiz.scope,
            "chat_type": quiz.chat_type,
        },
        ip=get_request_ip(request),
    )
    await db.commit()
    return ApiResponse(code=200, message="success", data=None)


@router.post("/{quiz_id}/restore", response_model=ApiResponse)
async def restore_quiz(
    quiz_id: int,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="quiz:restore",
        required_roles={"admin", "super_admin"},
        request=request,
        target_tenant_id=(int(current_user.tenant_id) if current_user.tenant_id else None),
        target_type="quiz",
        target_id=quiz_id,
    )
    tenant_id = ensure_tenant_bound(current_user)
    quiz = (
        await db.execute(select(Quiz).where(Quiz.id == quiz_id, Quiz.tenant_id == tenant_id))
    ).scalars().first()
    if not quiz:
        raise HTTPException(status_code=404, detail="案例不存在")
    if not quiz.is_deleted:
        return ApiResponse(code=200, message="success", data=None)

    if current_user.role != "super_admin" and not current_user.is_all_hospitals:
        accessible_dept_ids = await get_accessible_department_ids(current_user, db)
        accessible_ids = await get_accessible_hospital_ids(current_user, db)
        if quiz.scope != "common" and not (
            (quiz.department_id and quiz.department_id in accessible_dept_ids)
            or (quiz.hospital_id and quiz.hospital_id in accessible_ids)
        ):
            raise HTTPException(status_code=403, detail="无权恢复其他医院案例")
        if quiz.scope == "common":
            raise HTTPException(status_code=403, detail="无权恢复通用案例库")

    quiz.is_deleted = False
    await append_audit_log(
        db,
        action="quiz_restore",
        user_id=current_user.id,
        target_type="quiz",
        target_id=quiz.id,
        hospital_id=quiz.hospital_id,
        department_id=quiz.department_id,
        detail={
            "title": quiz.title,
            "scope": quiz.scope,
            "chat_type": quiz.chat_type,
        },
        ip=get_request_ip(request),
    )
    await db.commit()
    return ApiResponse(code=200, message="success", data=None)
