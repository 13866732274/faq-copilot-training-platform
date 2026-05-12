from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PracticeStartRequest(BaseModel):
    quiz_id: int


class PracticeRandomStartRequest(BaseModel):
    chat_type: str | None = None
    keyword: str | None = None
    category: str | None = None
    tag: str | None = None


class PracticeStartData(BaseModel):
    practice_id: int
    quiz_id: int
    status: str


class PracticeDashboardHeatmapItem(BaseModel):
    date: str
    count: int


class PracticeDashboardRecentItem(BaseModel):
    practice_id: int
    quiz_id: int
    quiz_title: str
    status: str
    started_at: str
    completed_at: str | None = None


class PracticeDashboardContinueItem(BaseModel):
    practice_id: int
    quiz_id: int
    quiz_title: str
    started_at: str


class PracticeDashboardData(BaseModel):
    total_quizzes: int
    completed_quizzes: int
    total_practices: int
    this_week_practices: int
    streak_days: int
    avg_rounds: float
    weekly_heatmap: list[PracticeDashboardHeatmapItem]
    recent_practices: list[PracticeDashboardRecentItem]
    in_progress_count: int
    last_in_progress: PracticeDashboardContinueItem | None = None


class PracticeAvailableItem(BaseModel):
    id: int
    title: str
    scope: str
    hospital_id: int | None = None
    hospital_name: str | None = None
    department_id: int | None = None
    department_name: str | None = None
    chat_type: str
    category: str | None = None
    tags: str | None = None
    difficulty: int
    message_count: int
    patient_name: str | None = None
    counselor_name: str | None = None


class PracticeAvailablePageData(BaseModel):
    items: list[PracticeAvailableItem]
    total: int
    page: int
    page_size: int


class PracticeFilterOptionItem(BaseModel):
    name: str
    count: int


class PracticeAvailableFilterOptionsData(BaseModel):
    categories: list[PracticeFilterOptionItem] = []
    tags: list[PracticeFilterOptionItem] = []


class PracticeMessage(BaseModel):
    id: int
    role: str
    content_type: str
    content: str
    sender_name: str | None = None
    original_time: str | None = None


class NextData(BaseModel):
    messages: list[PracticeMessage]
    need_reply: bool
    reply_to_message_id: int | None = None
    is_last: bool


class PracticeHistoryData(BaseModel):
    messages: list[PracticeMessage]


class ReplyRequest(BaseModel):
    message_id: int
    content: str = Field(min_length=1)


class ReplyData(BaseModel):
    practice_id: int
    message_id: int
    current_step: int


class CompleteData(BaseModel):
    practice_id: int
    status: str
    completed_at: datetime


class ReviewDialogue(BaseModel):
    patient_messages: list[PracticeMessage]
    standard_answer: PracticeMessage
    standard_answers: list[PracticeMessage] = []
    student_reply: dict | None = None


class ReviewData(BaseModel):
    quiz_title: str
    dialogues: list[ReviewDialogue]
    comments: list[dict] = []


class PracticeAiScoreData(BaseModel):
    practice_id: int
    overall_score: int
    completion_rate: float
    avg_reply_length: float
    empathy_hits: int
    suggestions: list[str] = []
    dimension_scores: dict[str, float] = {}
    deduction_reasons: list[str] = []
    llm_audit: dict | None = None


class PracticeFaqMatchedItem(BaseModel):
    cluster_id: int
    title: str
    summary: str | None = None
    category: str | None = None
    representative_question: str | None = None
    best_answer: str | None = None
    question_count: int
    answer_count: int
    similarity: float


class PracticeFaqCopilotData(BaseModel):
    recommended_reply: str
    confidence: float
    matched_faqs: list[PracticeFaqMatchedItem]
    latency_ms: int
    quality_mode_requested: str = "auto"
    quality_mode_effective: str = "balanced"
    quality_route_reason: str | None = None


class PracticeFaqSearchData(BaseModel):
    results: list[PracticeFaqMatchedItem]
    latency_ms: int


class PracticeFaqClusterItem(BaseModel):
    cluster_id: int
    title: str
    category: str | None = None
    summary: str | None = None
    representative_question: str | None = None
    best_answer: str | None = None
    question_count: int
    answer_count: int


class PracticeFaqClusterListData(BaseModel):
    items: list[PracticeFaqClusterItem]
    total: int
    page: int
    page_size: int
    categories: list[str] = []


class ApiResponse(BaseModel):
    code: int
    message: str
    data: (
        PracticeStartData
        | PracticeDashboardData
        | PracticeAvailablePageData
        | PracticeAvailableFilterOptionsData
        | NextData
        | PracticeHistoryData
        | ReplyData
        | CompleteData
        | ReviewData
        | PracticeAiScoreData
        | PracticeFaqCopilotData
        | PracticeFaqSearchData
        | PracticeFaqClusterListData
        | None
    ) = None
