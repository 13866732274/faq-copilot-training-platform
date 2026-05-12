from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class RecordListItem(BaseModel):
    practice_id: int
    quiz_id: int
    quiz_title: str
    status: str
    started_at: datetime
    completed_at: datetime | None = None


class RecordListPageData(BaseModel):
    items: list[RecordListItem]
    total: int
    page: int
    page_size: int


class RecordDialogue(BaseModel):
    patient_messages: list[dict]
    standard_answer: dict
    standard_answers: list[dict] = []
    student_reply: dict | None = None


class RecordDetailData(BaseModel):
    practice_id: int
    quiz_title: str
    status: str
    dialogues: list[RecordDialogue]
    comments: list[dict]


class ApiResponse(BaseModel):
    code: int
    message: str
    data: RecordListPageData | RecordDetailData | None = None
