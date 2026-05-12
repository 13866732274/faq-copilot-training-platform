from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class DepartmentItem(BaseModel):
    id: int
    hospital_id: int
    hospital_name: str | None = None
    code: str
    name: str
    is_active: bool
    created_at: datetime


class DepartmentCreateRequest(BaseModel):
    hospital_id: int
    code: str | None = Field(default=None, min_length=2, max_length=50)
    name: str = Field(min_length=2, max_length=100)


class DepartmentUpdateRequest(BaseModel):
    code: str | None = Field(default=None, min_length=2, max_length=50)
    name: str | None = Field(default=None, min_length=2, max_length=100)
    is_active: bool | None = None


class DepartmentAssignUsersRequest(BaseModel):
    user_ids: list[int] = Field(default_factory=list)
    mode: Literal["append", "replace"] = "append"


class ApiResponse(BaseModel):
    code: int
    message: str
    data: DepartmentItem | list[DepartmentItem] | None = None
