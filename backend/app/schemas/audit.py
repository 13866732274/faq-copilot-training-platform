from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditLogItem(BaseModel):
    id: int
    user_id: int | None = None
    username: str | None = None
    real_name: str | None = None
    action: str
    target_type: str
    target_id: int | None = None
    hospital_id: int | None = None
    hospital_name: str | None = None
    department_id: int | None = None
    department_name: str | None = None
    detail: dict[str, Any] | None = None
    ip: str | None = None
    created_at: datetime


class AuditLogListData(BaseModel):
    items: list[AuditLogItem]
    total: int
    page: int
    page_size: int


class ApiResponse(BaseModel):
    code: int
    message: str
    data: AuditLogListData | None = None
