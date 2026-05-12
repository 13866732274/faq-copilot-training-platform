from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ImportTaskCreateRequest(BaseModel):
    scope: Literal["common", "hospital", "department"]
    hospital_id: int | None = None
    department_id: int | None = None
    total: int = Field(default=0, ge=0)
    detail: dict | None = None


class ImportTaskFinishRequest(BaseModel):
    success: int = Field(default=0, ge=0)
    duplicate: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    updated: int = Field(default=0, ge=0)
    detail: dict | None = None


class ImportTaskItem(BaseModel):
    id: int
    operator_id: int
    operator_name: str | None = None
    scope: Literal["common", "hospital", "department"]
    hospital_id: int | None = None
    hospital_name: str | None = None
    department_id: int | None = None
    department_name: str | None = None
    total: int
    success: int
    duplicate: int
    failed: int
    updated: int
    status: Literal["running", "completed", "partial_fail"]
    detail: dict | None = None
    started_at: datetime
    finished_at: datetime | None = None
    created_at: datetime


class ImportTaskPageData(BaseModel):
    items: list[ImportTaskItem]
    total: int
    page: int
    page_size: int


class ApiResponse(BaseModel):
    code: int
    message: str
    data: ImportTaskItem | ImportTaskPageData | None = None
