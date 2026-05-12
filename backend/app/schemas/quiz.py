from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ChatType = Literal["active", "passive"]


class MessageItem(BaseModel):
    sequence: int
    role: str
    content_type: str
    content: str
    sender_name: str
    original_time: str | None = None


class ImportQualityReport(BaseModel):
    total_messages: int = 0
    patient_count: int = 0
    counselor_count: int = 0
    text_count: int = 0
    image_count: int = 0
    audio_count: int = 0
    skipped_empty: int = 0
    role_alternation_rate: float = 0.0
    unique_patient_names: list[str] = []
    unique_counselor_names: list[str] = []
    name_collision: bool = False
    quality_score: float = 0.0
    warnings: list[str] = []


class UploadPreviewData(BaseModel):
    preview_id: str
    source_file: str
    patient_name: str | None = None
    counselor_name: str | None = None
    message_count: int
    messages: list[MessageItem]
    quality_report: ImportQualityReport | None = None


class ConfirmImportRequest(BaseModel):
    preview_id: str
    title: str = Field(min_length=1, max_length=200)
    scope: Literal["common", "hospital", "department"] = "hospital"
    hospital_id: int | None = None
    department_id: int | None = None
    chat_type: ChatType
    category: str | None = Field(default=None, max_length=50)
    difficulty: int = Field(default=1, ge=1, le=5)
    tags: str | None = Field(default=None, max_length=500)
    description: str | None = None


class BatchReparseRequest(BaseModel):
    scope: Literal["common", "hospital", "department"] = "hospital"
    hospital_id: int | None = None
    department_id: int | None = None
    chat_type: ChatType | None = None
    limit: int = Field(default=500, ge=1, le=2000)
    only_legacy_or_empty_hash: bool = False


class QuizVersionItem(BaseModel):
    id: int
    version_no: int
    source_file: str | None = None
    message_count: int
    created_by: int | None = None
    created_at: datetime


class ConfirmImportData(BaseModel):
    quiz_id: int
    title: str
    message_count: int


class QuizUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    scope: Literal["common", "hospital", "department"] = "hospital"
    hospital_id: int | None = None
    department_id: int | None = None
    chat_type: ChatType
    category: str | None = Field(default=None, max_length=50)
    difficulty: int = Field(default=1, ge=1, le=5)
    tags: str | None = Field(default=None, max_length=500)
    description: str | None = None
    patient_name: str | None = Field(default=None, max_length=100)
    counselor_name: str | None = Field(default=None, max_length=100)


class QuizUpdateData(BaseModel):
    quiz_id: int
    title: str
    scope: Literal["common", "hospital", "department"]
    hospital_id: int | None = None
    department_id: int | None = None
    chat_type: ChatType
    category: str | None = None
    difficulty: int
    tags: str | None = None
    description: str | None = None
    patient_name: str | None = None
    counselor_name: str | None = None


class QuizMetaOptionItem(BaseModel):
    name: str
    count: int


class QuizMetaOptionsData(BaseModel):
    categories: list[QuizMetaOptionItem] = []
    tags: list[QuizMetaOptionItem] = []


class BatchQuizMetaUpdateRequest(BaseModel):
    quiz_ids: list[int] = []
    keyword: str | None = None
    scope: Literal["common", "hospital", "department"] | None = None
    hospital_id: int | None = None
    department_id: int | None = None
    chat_type: ChatType | None = None
    set_category: str | None = Field(default=None, max_length=50)
    clear_category: bool = False
    add_tags: list[str] = []
    remove_tags: list[str] = []
    replace_tags: list[str] | None = None
    clear_tags: bool = False


class BatchQuizMetaUpdateData(BaseModel):
    matched: int
    updated: int


class QuizMetaOperateFilter(BaseModel):
    scope: Literal["common", "hospital", "department"] | None = None
    hospital_id: int | None = None
    department_id: int | None = None
    chat_type: ChatType | None = None


class CategoryRenameRequest(QuizMetaOperateFilter):
    old_name: str = Field(min_length=1, max_length=50)
    new_name: str = Field(min_length=1, max_length=50)


class CategoryMergeRequest(QuizMetaOperateFilter):
    source_names: list[str] = []
    target_name: str = Field(min_length=1, max_length=50)


class CategoryDeleteRequest(QuizMetaOperateFilter):
    names: list[str] = []


class TagRenameRequest(QuizMetaOperateFilter):
    old_name: str = Field(min_length=1, max_length=50)
    new_name: str = Field(min_length=1, max_length=50)


class TagMergeRequest(QuizMetaOperateFilter):
    source_names: list[str] = []
    target_name: str = Field(min_length=1, max_length=50)


class TagDeleteRequest(QuizMetaOperateFilter):
    names: list[str] = []


class QuizMetaOperateData(BaseModel):
    matched: int
    updated: int


class BatchReparseData(BaseModel):
    matched: int
    processed: int
    updated: int
    skipped: int
    failed: int
    detail: list[dict] = []


class BatchReparseEstimateData(BaseModel):
    matched: int
    limit: int
    only_legacy_or_empty_hash: bool


class QuizListItem(BaseModel):
    id: int
    title: str
    scope: Literal["common", "hospital", "department"]
    hospital_id: int | None = None
    hospital_name: str | None = None
    department_id: int | None = None
    department_name: str | None = None
    chat_type: ChatType
    category: str | None = None
    difficulty: int
    tags: str | None = None
    patient_name: str | None = None
    counselor_name: str | None = None
    message_count: int
    is_active: bool
    is_deleted: bool = False
    created_at: datetime


class QuizDetailData(BaseModel):
    id: int
    title: str
    scope: Literal["common", "hospital", "department"]
    hospital_id: int | None = None
    hospital_name: str | None = None
    department_id: int | None = None
    department_name: str | None = None
    chat_type: ChatType
    description: str | None = None
    category: str | None = None
    difficulty: int
    tags: str | None = None
    patient_name: str | None = None
    counselor_name: str | None = None
    message_count: int
    source_file: str | None = None
    is_active: bool
    is_deleted: bool = False
    created_at: datetime
    versions: list[QuizVersionItem] = []
    messages: list[MessageItem]


class PageData(BaseModel):
    items: list[QuizListItem]
    total: int
    page: int
    page_size: int


class ApiResponse(BaseModel):
    code: int
    message: str
    data: (
        UploadPreviewData
        | ConfirmImportData
        | QuizUpdateData
        | QuizMetaOptionsData
        | BatchQuizMetaUpdateData
        | QuizMetaOperateData
        | BatchReparseData
        | BatchReparseEstimateData
        | QuizDetailData
        | PageData
        | None
    ) = None
