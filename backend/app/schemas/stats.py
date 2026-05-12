from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class OverviewData(BaseModel):
    total_quizzes: int
    total_students: int
    total_practices: int
    today_practices: int
    total_hospitals: int
    total_departments: int


class SystemHealthData(BaseModel):
    db_status: str
    db_ping_ms: float
    active_practice_sessions: int
    pending_import_tasks: int
    audit_logs_24h: int
    slow_request_threshold_ms: int
    server_time: datetime


class TrendsData(BaseModel):
    dates: list[str]
    new_practices: list[int]
    completed: list[int]
    new_students: list[int]


class StudentStatsItem(BaseModel):
    user_id: int
    username: str
    real_name: str
    hospital_id: int | None = None
    hospital_name: str | None = None
    department_id: int | None = None
    department_name: str | None = None
    completed_count: int
    in_progress_count: int
    last_practice_time: datetime | None = None


class QuizStatsItem(BaseModel):
    quiz_id: int
    title: str
    category: str | None = None
    scope: str
    hospital_id: int | None = None
    hospital_name: str | None = None
    department_id: int | None = None
    department_name: str | None = None
    practice_count: int


class HospitalCompareItem(BaseModel):
    hospital_id: int
    hospital_code: str
    hospital_name: str
    student_count: int
    hospital_quiz_count: int
    practice_count: int
    completed_count: int
    completion_rate: float


class StudentPracticeItem(BaseModel):
    practice_id: int
    quiz_id: int
    quiz_title: str
    status: str
    started_at: str
    completed_at: str | None = None


class StudentStatsPageData(BaseModel):
    items: list[StudentStatsItem]
    total: int
    page: int
    page_size: int


class QuizStatsPageData(BaseModel):
    items: list[QuizStatsItem]
    total: int
    page: int
    page_size: int


class HospitalComparePageData(BaseModel):
    items: list[HospitalCompareItem]
    total: int
    page: int
    page_size: int


class StudentPracticePageData(BaseModel):
    items: list[StudentPracticeItem]
    total: int
    page: int
    page_size: int


class CommentRequest(BaseModel):
    content: str


class CommentData(BaseModel):
    comment_id: int
    practice_id: int
    admin_id: int
    content: str
    created_at: datetime


class ApiResponse(BaseModel):
    code: int
    message: str
    data: (
        OverviewData
        | TrendsData
        | StudentStatsPageData
        | QuizStatsPageData
        | HospitalComparePageData
        | StudentPracticePageData
        | SystemHealthData
        | CommentData
        | list[dict]
        | dict
        | None
    ) = None
