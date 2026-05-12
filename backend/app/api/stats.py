from __future__ import annotations

from datetime import datetime, timedelta
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import ensure_tenant_bound, get_accessible_department_ids, get_accessible_hospital_ids, require_admin
from app.models import AuditLog, Department, Hospital, ImportTask, Message, Practice, PracticeComment, PracticeReply, Quiz, User
from app.services.audit import append_audit_log, get_request_ip
from app.services.rbac import enforce_rbac
from app.schemas.stats import (
    ApiResponse,
    CommentData,
    CommentRequest,
    HospitalCompareItem,
    HospitalComparePageData,
    OverviewData,
    QuizStatsPageData,
    QuizStatsItem,
    SystemHealthData,
    StudentPracticeItem,
    StudentPracticePageData,
    StudentStatsPageData,
    StudentStatsItem,
    TrendsData,
)

router = APIRouter()


async def _table_exists(db: AsyncSession, table_name: str) -> bool:
    stmt = text(
        """
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_schema = DATABASE() AND table_name = :table_name
        """
    )
    count = (await db.execute(stmt, {"table_name": table_name})).scalar_one()
    return bool(count)


@router.get("/overview", response_model=ApiResponse)
async def overview(
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="stats:overview",
        required_roles={"admin", "super_admin"},
        request=request,
        target_tenant_id=(int(current_user.tenant_id) if current_user.tenant_id else None),
        target_type="stats",
    )
    tenant_id = ensure_tenant_bound(current_user)
    quiz_filters = [Quiz.is_deleted.is_(False), Quiz.tenant_id == tenant_id]
    student_filters = [User.role == "student", User.tenant_id == tenant_id]
    current_hospital_id: int | None = None
    accessible_hospital_ids: list[int] = []
    accessible_department_ids: list[int] = []
    practice_where_sql = ""
    practice_sql_params: dict[str, int] = {"tenant_id": tenant_id}
    if current_user.role != "super_admin" and not current_user.is_all_hospitals:
        accessible_department_ids = await get_accessible_department_ids(current_user, db)
        accessible_hospital_ids = await get_accessible_hospital_ids(current_user, db)
        current_hospital_id = accessible_hospital_ids[0] if len(accessible_hospital_ids) == 1 else None
        quiz_filters.append(
            (Quiz.scope == "common")
            | (Quiz.department_id.in_(accessible_department_ids))
            | (Quiz.hospital_id.in_(accessible_hospital_ids))
        )
        student_filters.append(
            (User.department_id.in_(accessible_department_ids)) | (User.hospital_id.in_(accessible_hospital_ids))
        )
        if len(accessible_hospital_ids) == 1:
            practice_where_sql = " WHERE tenant_id = :tenant_id AND hospital_id = :hospital_id"
            practice_sql_params["hospital_id"] = accessible_hospital_ids[0]
        else:
            ids_sql = ",".join(str(int(i)) for i in accessible_hospital_ids) or "-1"
            practice_where_sql = f" WHERE tenant_id = :tenant_id AND hospital_id IN ({ids_sql})"
    else:
        practice_where_sql = " WHERE tenant_id = :tenant_id"

    total_quizzes_stmt = select(func.count(Quiz.id)).where(*quiz_filters)
    total_students_stmt = select(func.count(User.id)).where(*student_filters)
    hospital_filters = [Hospital.is_active.is_(True), Hospital.tenant_id == tenant_id]
    if current_hospital_id:
        hospital_filters.append(Hospital.id == current_hospital_id)
    elif accessible_hospital_ids:
        hospital_filters.append(Hospital.id.in_(accessible_hospital_ids))
    total_hospitals_stmt = select(func.count(Hospital.id)).where(*hospital_filters)

    total_quizzes = (await db.execute(total_quizzes_stmt)).scalar_one()
    total_students = (await db.execute(total_students_stmt)).scalar_one()
    total_hospitals = (await db.execute(total_hospitals_stmt)).scalar_one()
    dept_filters = [Department.is_active.is_(True), Department.tenant_id == tenant_id]
    if current_hospital_id:
        dept_filters.append(Department.hospital_id == current_hospital_id)
    elif accessible_hospital_ids:
        dept_filters.append(Department.hospital_id.in_(accessible_hospital_ids))
    elif accessible_department_ids:
        dept_filters.append(Department.id.in_(accessible_department_ids))
    total_departments = (await db.execute(select(func.count(Department.id)).where(*dept_filters))).scalar_one()

    total_practices = 0
    today_practices = 0
    if await _table_exists(db, "practices"):
        where_body = practice_where_sql.replace(" WHERE ", "", 1) if practice_where_sql else "tenant_id = :tenant_id"
        practice_summary_sql = text(
            f"""
            SELECT
                COUNT(*) AS total_practices,
                SUM(
                    CASE
                        WHEN created_at >= CURDATE()
                          AND created_at < DATE_ADD(CURDATE(), INTERVAL 1 DAY)
                        THEN 1 ELSE 0
                    END
                ) AS today_practices
            FROM practices
            WHERE {where_body}
            """
        )
        practice_summary = (await db.execute(practice_summary_sql, practice_sql_params)).mappings().one()
        total_practices = int(practice_summary["total_practices"] or 0)
        today_practices = int(practice_summary["today_practices"] or 0)

    return ApiResponse(
        code=200,
        message="success",
        data=OverviewData(
            total_quizzes=total_quizzes,
            total_students=total_students,
            total_practices=total_practices,
            today_practices=today_practices,
            total_hospitals=total_hospitals,
            total_departments=total_departments,
        ),
    )


@router.get("/system-health", response_model=ApiResponse)
async def system_health(
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="stats:system_health",
        required_roles={"admin", "super_admin"},
        request=request,
        target_tenant_id=(int(current_user.tenant_id) if current_user.tenant_id else None),
        target_type="stats",
    )
    tenant_id = ensure_tenant_bound(current_user)

    ping_start = time.perf_counter()
    await db.execute(text("SELECT 1"))
    db_ping_ms = round((time.perf_counter() - ping_start) * 1000, 1)

    active_practice_sessions = int(
        (
            await db.execute(
                select(func.count(Practice.id)).where(
                    Practice.tenant_id == tenant_id,
                    Practice.status == "in_progress",
                )
            )
        ).scalar_one()
        or 0
    )
    pending_import_tasks = int(
        (
            await db.execute(
                select(func.count(ImportTask.id)).where(
                    ImportTask.tenant_id == tenant_id,
                    ImportTask.status == "running",
                )
            )
        ).scalar_one()
        or 0
    )
    audit_logs_24h = int(
        (
            await db.execute(
                select(func.count(AuditLog.id)).where(
                    AuditLog.tenant_id == tenant_id,
                    AuditLog.created_at >= (datetime.now() - timedelta(hours=24)),
                )
            )
        ).scalar_one()
        or 0
    )
    return ApiResponse(
        code=200,
        message="success",
        data=SystemHealthData(
            db_status="ok",
            db_ping_ms=db_ping_ms,
            active_practice_sessions=active_practice_sessions,
            pending_import_tasks=pending_import_tasks,
            audit_logs_24h=audit_logs_24h,
            slow_request_threshold_ms=500,
            server_time=datetime.now(),
        ),
    )


@router.get("/trends", response_model=ApiResponse)
async def trends(
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    days: int = Query(default=30, ge=7, le=90),
    hospital_id: int | None = None,
    department_id: int | None = None,
) -> ApiResponse:
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="stats:trends",
        required_roles={"admin", "super_admin"},
        request=request,
        target_tenant_id=(int(current_user.tenant_id) if current_user.tenant_id else None),
        target_hospital_id=hospital_id,
        target_department_id=department_id,
        target_type="stats",
    )
    tenant_id = ensure_tenant_bound(current_user)
    if current_user.role == "super_admin" or current_user.is_all_hospitals:
        scoped_hospital_ids: list[int] = []
        scoped_department_ids: list[int] = []
    else:
        scoped_hospital_ids = await get_accessible_hospital_ids(current_user, db)
        scoped_department_ids = await get_accessible_department_ids(current_user, db)
        if hospital_id and hospital_id not in scoped_hospital_ids:
            raise HTTPException(status_code=403, detail="无权查看该医院数据")
        if department_id and department_id not in scoped_department_ids:
            raise HTTPException(status_code=403, detail="无权查看该科室数据")

    from_date_expr = f"DATE_SUB(CURDATE(), INTERVAL {days - 1} DAY)"
    params: dict[str, int] = {"tenant_id": tenant_id}

    practice_filters = [f"DATE(created_at) >= {from_date_expr}", "tenant_id = :tenant_id"]
    student_filters = [f"DATE(created_at) >= {from_date_expr}", "role='student'", "tenant_id = :tenant_id"]
    completed_filters = [f"DATE(completed_at) >= {from_date_expr}", "completed_at IS NOT NULL", "tenant_id = :tenant_id"]

    if hospital_id:
        practice_filters.append("hospital_id = :hospital_id")
        completed_filters.append("hospital_id = :hospital_id")
        student_filters.append("hospital_id = :hospital_id")
        params["hospital_id"] = hospital_id
    elif current_user.role != "super_admin" and not current_user.is_all_hospitals:
        ids_sql = ",".join(str(int(i)) for i in scoped_hospital_ids) or "-1"
        practice_filters.append(f"hospital_id IN ({ids_sql})")
        completed_filters.append(f"hospital_id IN ({ids_sql})")
        student_filters.append(f"hospital_id IN ({ids_sql})")

    if department_id:
        practice_filters.append("department_id = :department_id")
        completed_filters.append("department_id = :department_id")
        student_filters.append("department_id = :department_id")
        params["department_id"] = department_id
    elif current_user.role != "super_admin" and not current_user.is_all_hospitals and scoped_department_ids:
        dept_sql = ",".join(str(int(i)) for i in scoped_department_ids) or "-1"
        practice_filters.append(f"department_id IN ({dept_sql})")
        completed_filters.append(f"department_id IN ({dept_sql})")
        student_filters.append(f"department_id IN ({dept_sql})")

    practice_sql = text(
        f"""
        SELECT DATE(created_at) AS d, COUNT(*) AS c
        FROM practices
        WHERE {' AND '.join(practice_filters)}
        GROUP BY DATE(created_at)
        """
    )
    completed_sql = text(
        f"""
        SELECT DATE(completed_at) AS d, COUNT(*) AS c
        FROM practices
        WHERE {' AND '.join(completed_filters)}
        GROUP BY DATE(completed_at)
        """
    )
    students_sql = text(
        f"""
        SELECT DATE(created_at) AS d, COUNT(*) AS c
        FROM users
        WHERE {' AND '.join(student_filters)}
        GROUP BY DATE(created_at)
        """
    )

    practice_rows = (await db.execute(practice_sql, params)).mappings().all()
    completed_rows = (await db.execute(completed_sql, params)).mappings().all()
    student_rows = (await db.execute(students_sql, params)).mappings().all()

    practice_map = {str(r["d"]): int(r["c"] or 0) for r in practice_rows}
    completed_map = {str(r["d"]): int(r["c"] or 0) for r in completed_rows}
    student_map = {str(r["d"]): int(r["c"] or 0) for r in student_rows}

    dates_stmt = text(
        f"""
        SELECT DATE_FORMAT(DATE_ADD({from_date_expr}, INTERVAL seq DAY), '%Y-%m-%d') AS d
        FROM (
          SELECT ones.n + tens.n * 10 AS seq
          FROM (SELECT 0 n UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4 UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9) ones
          CROSS JOIN (SELECT 0 n UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4 UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9) tens
        ) nums
        WHERE seq < :days
        ORDER BY d
        """
    )
    date_rows = (await db.execute(dates_stmt, {"days": days})).mappings().all()
    dates = [str(r["d"]) for r in date_rows]

    return ApiResponse(
        code=200,
        message="success",
        data=TrendsData(
            dates=dates,
            new_practices=[practice_map.get(d, 0) for d in dates],
            completed=[completed_map.get(d, 0) for d in dates],
            new_students=[student_map.get(d, 0) for d in dates],
        ),
    )


@router.get("/students", response_model=ApiResponse)
async def student_stats(
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    hospital_id: int | None = None,
    department_id: int | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
) -> ApiResponse:
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="stats:students",
        required_roles={"admin", "super_admin"},
        request=request,
        target_tenant_id=(int(current_user.tenant_id) if current_user.tenant_id else None),
        target_hospital_id=hospital_id,
        target_department_id=department_id,
        target_type="stats",
    )
    tenant_id = ensure_tenant_bound(current_user)
    filters = "WHERE u.role='student' AND u.tenant_id=:tenant_id"
    params: dict[str, int] = {"tenant_id": tenant_id}
    if current_user.role == "super_admin" or current_user.is_all_hospitals:
        if hospital_id:
            filters += " AND u.hospital_id=:hospital_id"
            params["hospital_id"] = hospital_id
        if department_id:
            filters += " AND u.department_id=:department_id"
            params["department_id"] = department_id
    else:
        accessible_dept_ids = await get_accessible_department_ids(current_user, db)
        accessible_ids = await get_accessible_hospital_ids(current_user, db)
        if hospital_id:
            if hospital_id not in accessible_ids:
                raise HTTPException(status_code=403, detail="无权查看该医院数据")
            filters += " AND u.hospital_id=:hospital_id"
            params["hospital_id"] = hospital_id
        if department_id:
            if department_id not in accessible_dept_ids:
                raise HTTPException(status_code=403, detail="无权查看该科室数据")
            filters += " AND u.department_id=:department_id"
            params["department_id"] = department_id
        else:
            dept_sql = ",".join(str(int(i)) for i in accessible_dept_ids) or "-1"
            filters += f" AND u.department_id IN ({dept_sql})"

    base_sql = (
        """
        SELECT
          u.id AS user_id,
          u.username,
          u.real_name,
          u.hospital_id,
          h.name AS hospital_name,
          u.department_id,
          d.name AS department_name,
          SUM(CASE WHEN p.status='completed' THEN 1 ELSE 0 END) AS completed_count,
          SUM(CASE WHEN p.status='in_progress' THEN 1 ELSE 0 END) AS in_progress_count,
          MAX(p.updated_at) AS last_practice_time
        FROM users u
        LEFT JOIN hospitals h ON h.id = u.hospital_id
        LEFT JOIN departments d ON d.id = u.department_id
        LEFT JOIN practices p ON p.user_id = u.id AND p.tenant_id = u.tenant_id
        __FILTERS__
        GROUP BY u.id, u.username, u.real_name, u.hospital_id, h.name, u.department_id, d.name
        """
    ).replace("__FILTERS__", filters)
    count_stmt = text(f"SELECT COUNT(*) FROM ({base_sql}) AS s")
    total = int((await db.execute(count_stmt, params)).scalar_one())
    page_params = {**params, "limit": page_size, "offset": (page - 1) * page_size}
    stmt = text(
        """
        SELECT *
        FROM (__BASE_SQL__) AS s
        ORDER BY completed_count DESC, last_practice_time DESC
        LIMIT :limit OFFSET :offset
        """
        .replace("__BASE_SQL__", base_sql)
    )
    rows = (await db.execute(stmt, page_params)).mappings().all()
    items = [
        StudentStatsItem(
            user_id=int(r["user_id"]),
            username=str(r["username"]),
            real_name=str(r["real_name"]),
            hospital_id=int(r["hospital_id"]) if r["hospital_id"] else None,
            hospital_name=str(r["hospital_name"]) if r["hospital_name"] else None,
            department_id=int(r["department_id"]) if r["department_id"] else None,
            department_name=str(r["department_name"]) if r["department_name"] else None,
            completed_count=int(r["completed_count"] or 0),
            in_progress_count=int(r["in_progress_count"] or 0),
            last_practice_time=r["last_practice_time"],
        )
        for r in rows
    ]
    return ApiResponse(
        code=200,
        message="success",
        data=StudentStatsPageData(items=items, total=total, page=page, page_size=page_size),
    )


@router.get("/quizzes", response_model=ApiResponse)
async def quiz_stats(
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    hospital_id: int | None = None,
    department_id: int | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=500),
) -> ApiResponse:
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="stats:quizzes",
        required_roles={"admin", "super_admin"},
        request=request,
        target_tenant_id=(int(current_user.tenant_id) if current_user.tenant_id else None),
        target_hospital_id=hospital_id,
        target_department_id=department_id,
        target_type="stats",
    )
    tenant_id = ensure_tenant_bound(current_user)
    filters = "WHERE q.is_deleted = 0 AND q.tenant_id = :tenant_id"
    params: dict[str, int] = {"tenant_id": tenant_id}
    if current_user.role == "super_admin" or current_user.is_all_hospitals:
        if hospital_id:
            filters += " AND (q.scope='common' OR q.hospital_id=:hospital_id)"
            params["hospital_id"] = hospital_id
        if department_id:
            filters += " AND (q.scope='common' OR q.department_id=:department_id)"
            params["department_id"] = department_id
    else:
        accessible_dept_ids = await get_accessible_department_ids(current_user, db)
        accessible_ids = await get_accessible_hospital_ids(current_user, db)
        if hospital_id:
            if hospital_id not in accessible_ids:
                raise HTTPException(status_code=403, detail="无权查看该医院数据")
            filters += " AND (q.scope='common' OR q.hospital_id=:hospital_id)"
            params["hospital_id"] = hospital_id
        if department_id:
            if department_id not in accessible_dept_ids:
                raise HTTPException(status_code=403, detail="无权查看该科室数据")
            filters += " AND (q.scope='common' OR q.department_id=:department_id)"
            params["department_id"] = department_id
        else:
            dept_sql = ",".join(str(int(i)) for i in accessible_dept_ids) or "-1"
            filters += f" AND (q.scope='common' OR q.department_id IN ({dept_sql}) OR q.hospital_id IN ({','.join(str(int(i)) for i in accessible_ids) or '-1'}))"

    base_sql = (
        """
        SELECT q.id AS quiz_id, q.title, q.category, q.scope, q.hospital_id, h.name AS hospital_name, q.department_id, d.name AS department_name, COUNT(p.id) AS practice_count
        FROM quizzes q
        LEFT JOIN hospitals h ON h.id = q.hospital_id
        LEFT JOIN departments d ON d.id = q.department_id
        LEFT JOIN practices p ON p.quiz_id = q.id
        __FILTERS__
        GROUP BY q.id, q.title, q.category, q.scope, q.hospital_id, h.name, q.department_id, d.name
        """
    ).replace("__FILTERS__", filters)
    count_stmt = text(f"SELECT COUNT(*) FROM ({base_sql}) AS q")
    total = int((await db.execute(count_stmt, params)).scalar_one())
    page_params = {**params, "limit": page_size, "offset": (page - 1) * page_size}
    stmt = text(
        """
        SELECT *
        FROM (__BASE_SQL__) AS q
        ORDER BY practice_count DESC, quiz_id DESC
        LIMIT :limit OFFSET :offset
        """
        .replace("__BASE_SQL__", base_sql)
    )
    rows = (await db.execute(stmt, page_params)).mappings().all()
    items = [
        QuizStatsItem(
            quiz_id=int(r["quiz_id"]),
            title=str(r["title"]),
            category=str(r["category"]) if r["category"] else None,
            scope=str(r["scope"]),
            hospital_id=int(r["hospital_id"]) if r["hospital_id"] else None,
            hospital_name=str(r["hospital_name"]) if r["hospital_name"] else None,
            department_id=int(r["department_id"]) if r["department_id"] else None,
            department_name=str(r["department_name"]) if r["department_name"] else None,
            practice_count=int(r["practice_count"] or 0),
        )
        for r in rows
    ]
    return ApiResponse(
        code=200,
        message="success",
        data=QuizStatsPageData(items=items, total=total, page=page, page_size=page_size),
    )


@router.get("/hospitals/compare", response_model=ApiResponse)
async def hospital_compare(
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
) -> ApiResponse:
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="stats:hospital_compare",
        required_roles={"admin", "super_admin"},
        request=request,
        target_tenant_id=(int(current_user.tenant_id) if current_user.tenant_id else None),
        target_type="stats",
    )
    tenant_id = ensure_tenant_bound(current_user)
    filters = "WHERE h.is_active = 1 AND h.tenant_id = :tenant_id"
    params: dict[str, int] = {"tenant_id": tenant_id}
    if current_user.role != "super_admin" and not current_user.is_all_hospitals:
        accessible_ids = await get_accessible_hospital_ids(current_user, db)
        ids_sql = ",".join(str(int(i)) for i in accessible_ids) or "-1"
        filters += f" AND h.id IN ({ids_sql})"
    count_sql = "SELECT COUNT(*) FROM hospitals h __FILTERS__".replace("__FILTERS__", filters)
    total = int((await db.execute(text(count_sql), params)).scalar_one())
    page_params = {**params, "limit": page_size, "offset": (page - 1) * page_size}
    stmt = text(
        """
        SELECT
          h.id AS hospital_id,
          h.code AS hospital_code,
          h.name AS hospital_name,
          COALESCE(us.student_count, 0) AS student_count,
          COALESCE(qs.hospital_quiz_count, 0) AS hospital_quiz_count,
          COALESCE(ps.practice_count, 0) AS practice_count,
          COALESCE(ps.completed_count, 0) AS completed_count
        FROM hospitals h
        LEFT JOIN (
          SELECT hospital_id, COUNT(*) AS student_count
          FROM users
          WHERE role='student' AND tenant_id = :tenant_id
          GROUP BY hospital_id
        ) us ON us.hospital_id = h.id
        LEFT JOIN (
          SELECT hospital_id, COUNT(*) AS hospital_quiz_count
          FROM quizzes
          WHERE is_deleted=0 AND scope='hospital' AND tenant_id = :tenant_id
          GROUP BY hospital_id
        ) qs ON qs.hospital_id = h.id
        LEFT JOIN (
          SELECT
            hospital_id,
            COUNT(*) AS practice_count,
            SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed_count
          FROM practices
          WHERE tenant_id = :tenant_id
          GROUP BY hospital_id
        ) ps ON ps.hospital_id = h.id
        __FILTERS__
        ORDER BY practice_count DESC, h.id ASC
        LIMIT :limit OFFSET :offset
        """
        .replace("__FILTERS__", filters)
    )
    rows = (await db.execute(stmt, page_params)).mappings().all()
    items: list[HospitalCompareItem] = []
    for r in rows:
        practice_count = int(r["practice_count"] or 0)
        completed_count = int(r["completed_count"] or 0)
        completion_rate = round((completed_count / practice_count * 100), 2) if practice_count else 0.0
        items.append(
            HospitalCompareItem(
                hospital_id=int(r["hospital_id"]),
                hospital_code=str(r["hospital_code"]),
                hospital_name=str(r["hospital_name"]),
                student_count=int(r["student_count"] or 0),
                hospital_quiz_count=int(r["hospital_quiz_count"] or 0),
                practice_count=practice_count,
                completed_count=completed_count,
                completion_rate=completion_rate,
            )
        )
    return ApiResponse(
        code=200,
        message="success",
        data=HospitalComparePageData(items=items, total=total, page=page, page_size=page_size),
    )


@router.post("/practices/{practice_id}/comment", response_model=ApiResponse)
async def add_practice_comment(
    practice_id: int,
    payload: CommentRequest,
    request: Request,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    tenant_id = ensure_tenant_bound(current_admin)
    practice = (
        await db.execute(select(Practice).where(Practice.id == practice_id, Practice.tenant_id == tenant_id))
    ).scalars().first()
    if not practice:
        raise HTTPException(status_code=404, detail="训练记录不存在")
    if current_admin.role != "super_admin" and not current_admin.is_all_hospitals:
        accessible_ids = await get_accessible_hospital_ids(current_admin, db)
        if practice.hospital_id is not None and practice.hospital_id not in accessible_ids:
            raise HTTPException(status_code=403, detail="无权给其他医院训练记录添加点评")
    comment = PracticeComment(
        tenant_id=tenant_id,
        practice_id=practice_id,
        admin_id=current_admin.id,
        content=payload.content.strip(),
        created_at=datetime.now(),
    )
    db.add(comment)
    await db.flush()
    await append_audit_log(
        db,
        action="comment_change",
        user_id=current_admin.id,
        target_type="practice_comment",
        target_id=comment.id,
        hospital_id=practice.hospital_id,
        department_id=practice.department_id,
        detail={"type": "create", "practice_id": practice_id, "content": comment.content},
        ip=get_request_ip(request),
    )
    await db.commit()
    await db.refresh(comment)
    return ApiResponse(
        code=200,
        message="success",
        data=CommentData(
            comment_id=comment.id,
            practice_id=comment.practice_id,
            admin_id=comment.admin_id,
            content=comment.content,
            created_at=comment.created_at,
        ),
    )


@router.put("/comments/{comment_id}", response_model=ApiResponse)
async def update_practice_comment(
    comment_id: int,
    payload: CommentRequest,
    request: Request,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    tenant_id = ensure_tenant_bound(current_admin)
    comment = (
        await db.execute(
            select(PracticeComment).where(PracticeComment.id == comment_id, PracticeComment.tenant_id == tenant_id)
        )
    ).scalars().first()
    if not comment:
        raise HTTPException(status_code=404, detail="点评不存在")
    if current_admin.role != "super_admin" and not current_admin.is_all_hospitals:
        practice = (
            await db.execute(select(Practice).where(Practice.id == comment.practice_id, Practice.tenant_id == tenant_id))
        ).scalars().first()
        accessible_ids = await get_accessible_hospital_ids(current_admin, db)
        if not practice or (practice.hospital_id is not None and practice.hospital_id not in accessible_ids):
            raise HTTPException(status_code=403, detail="无权编辑其他医院点评")
    if current_admin.role != "super_admin" and comment.admin_id != current_admin.id:
        raise HTTPException(status_code=403, detail="仅可编辑自己创建的点评")
    old_content = comment.content
    comment.content = payload.content.strip()
    practice = (
        await db.execute(select(Practice).where(Practice.id == comment.practice_id, Practice.tenant_id == tenant_id))
    ).scalars().first()
    await append_audit_log(
        db,
        action="comment_change",
        user_id=current_admin.id,
        target_type="practice_comment",
        target_id=comment.id,
        hospital_id=practice.hospital_id if practice else None,
        department_id=practice.department_id if practice else None,
        detail={"type": "update", "practice_id": comment.practice_id, "before": old_content, "after": comment.content},
        ip=get_request_ip(request),
    )
    await db.commit()
    await db.refresh(comment)
    return ApiResponse(
        code=200,
        message="success",
        data=CommentData(
            comment_id=comment.id,
            practice_id=comment.practice_id,
            admin_id=comment.admin_id,
            content=comment.content,
            created_at=comment.created_at,
        ),
    )


@router.delete("/comments/{comment_id}", response_model=ApiResponse)
async def delete_practice_comment(
    comment_id: int,
    request: Request,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    tenant_id = ensure_tenant_bound(current_admin)
    comment = (
        await db.execute(
            select(PracticeComment).where(PracticeComment.id == comment_id, PracticeComment.tenant_id == tenant_id)
        )
    ).scalars().first()
    if not comment:
        raise HTTPException(status_code=404, detail="点评不存在")
    if current_admin.role != "super_admin" and not current_admin.is_all_hospitals:
        practice = (
            await db.execute(select(Practice).where(Practice.id == comment.practice_id, Practice.tenant_id == tenant_id))
        ).scalars().first()
        accessible_ids = await get_accessible_hospital_ids(current_admin, db)
        if not practice or (practice.hospital_id is not None and practice.hospital_id not in accessible_ids):
            raise HTTPException(status_code=403, detail="无权删除其他医院点评")
    if current_admin.role != "super_admin" and comment.admin_id != current_admin.id:
        raise HTTPException(status_code=403, detail="仅可删除自己创建的点评")
    practice = (
        await db.execute(select(Practice).where(Practice.id == comment.practice_id, Practice.tenant_id == tenant_id))
    ).scalars().first()
    await append_audit_log(
        db,
        action="comment_change",
        user_id=current_admin.id,
        target_type="practice_comment",
        target_id=comment.id,
        hospital_id=practice.hospital_id if practice else None,
        department_id=practice.department_id if practice else None,
        detail={"type": "delete", "practice_id": comment.practice_id, "content": comment.content},
        ip=get_request_ip(request),
    )
    await db.delete(comment)
    await db.commit()
    return ApiResponse(code=200, message="success", data=None)


@router.get("/students/{user_id}/practices", response_model=ApiResponse)
async def student_practices(
    user_id: int,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
) -> ApiResponse:
    tenant_id = ensure_tenant_bound(current_user)
    target_user = (
        await db.execute(select(User).where(User.id == user_id, User.tenant_id == tenant_id))
    ).scalars().first()
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="stats:student_practices",
        required_roles={"admin", "super_admin"},
        request=request,
        target_tenant_id=tenant_id,
        target_hospital_id=(target_user.hospital_id if target_user else None),
        target_department_id=(target_user.department_id if target_user else None),
        target_type="user",
        target_id=user_id,
    )
    if current_user.role != "super_admin" and not current_user.is_all_hospitals:
        accessible_ids = await get_accessible_hospital_ids(current_user, db)
        if not target_user or (target_user.hospital_id is not None and target_user.hospital_id not in accessible_ids):
            raise HTTPException(status_code=403, detail="无权查看其他医院咨询员")
    count_stmt = select(func.count(Practice.id)).where(Practice.user_id == user_id, Practice.tenant_id == tenant_id)
    total = int((await db.execute(count_stmt)).scalar_one())
    stmt = (
        select(Practice, Quiz)
        .join(Quiz, Quiz.id == Practice.quiz_id)
        .where(Practice.user_id == user_id, Practice.tenant_id == tenant_id, Quiz.tenant_id == tenant_id)
        .order_by(Practice.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.execute(stmt)).all()
    items = [
        StudentPracticeItem(
            practice_id=p.id,
            quiz_id=q.id,
            quiz_title=q.title,
            status=p.status,
            started_at=p.started_at.strftime("%Y-%m-%d %H:%M:%S"),
            completed_at=p.completed_at.strftime("%Y-%m-%d %H:%M:%S") if p.completed_at else None,
        )
        for p, q in rows
    ]
    return ApiResponse(
        code=200,
        message="success",
        data=StudentPracticePageData(items=items, total=total, page=page, page_size=page_size),
    )


@router.get("/students/{user_id}/practices/{practice_id}", response_model=ApiResponse)
async def student_practice_detail(
    user_id: int,
    practice_id: int,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    tenant_id = ensure_tenant_bound(current_user)
    target_user = (
        await db.execute(select(User).where(User.id == user_id, User.tenant_id == tenant_id))
    ).scalars().first()
    await enforce_rbac(
        db=db,
        actor=current_user,
        action="stats:student_practice_detail",
        required_roles={"admin", "super_admin"},
        request=request,
        target_tenant_id=tenant_id,
        target_hospital_id=(target_user.hospital_id if target_user else None),
        target_department_id=(target_user.department_id if target_user else None),
        target_type="practice",
        target_id=practice_id,
    )
    if current_user.role != "super_admin" and not current_user.is_all_hospitals:
        accessible_ids = await get_accessible_hospital_ids(current_user, db)
        if not target_user or (target_user.hospital_id is not None and target_user.hospital_id not in accessible_ids):
            raise HTTPException(status_code=403, detail="无权查看其他医院咨询员")
    practice_quiz_row = (
        await db.execute(
            select(Practice, Quiz.title.label("quiz_title"))
            .join(Quiz, Quiz.id == Practice.quiz_id)
            .where(
                Practice.id == practice_id,
                Practice.user_id == user_id,
                Practice.tenant_id == tenant_id,
                Quiz.tenant_id == tenant_id,
            )
            .limit(1)
        )
    ).first()
    if not practice_quiz_row:
        raise HTTPException(status_code=404, detail="训练记录不存在")
    practice = practice_quiz_row[0]
    quiz_title = str(practice_quiz_row[1] or "")
    message_reply_rows = (
        await db.execute(
            select(Message, PracticeReply)
            .outerjoin(
                PracticeReply,
                (
                    (PracticeReply.message_id == Message.id)
                    & (PracticeReply.practice_id == practice.id)
                    & (PracticeReply.tenant_id == tenant_id)
                ),
            )
            .where(Message.quiz_id == practice.quiz_id, Message.tenant_id == tenant_id)
            .order_by(Message.sequence.asc(), Message.id.asc())
            .limit(500)
        )
    ).all()
    comments = (
        await db.execute(
            select(PracticeComment, User.real_name)
            .join(User, User.id == PracticeComment.admin_id)
            .where(PracticeComment.practice_id == practice.id, PracticeComment.tenant_id == tenant_id)
            .order_by(PracticeComment.id.asc())
            .limit(200)
        )
    ).all()
    reply_map = {reply.message_id: reply for _, reply in message_reply_rows if reply is not None}
    dialogues: list[dict] = []
    patients: list[dict] = []
    for m, _ in message_reply_rows:
        msg = {
            "id": m.id,
            "content": m.content,
            "content_type": m.content_type,
            "sender_name": m.sender_name,
        }
        if m.role == "counselor":
            rp = reply_map.get(m.id)
            dialogues.append(
                {
                    "patient_messages": patients,
                    "standard_answer": msg,
                    "student_reply": {
                        "content": rp.reply_content,
                        "reply_time": rp.reply_time.strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    if rp
                    else None,
                }
            )
            patients = []
        else:
            patients.append(msg)
    return ApiResponse(
        code=200,
        message="success",
        data={
            "practice_id": practice.id,
            "quiz_title": quiz_title,
            "status": practice.status,
            "dialogues": dialogues,
            "comments": [
                {
                    "comment_id": c.id,
                    "admin_id": c.admin_id,
                    "admin_name": admin_name,
                    "content": c.content,
                    "created_at": c.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                }
                for c, admin_name in comments
            ],
        },
    )
