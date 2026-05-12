from __future__ import annotations

from datetime import datetime

from typing import Literal

from pydantic import BaseModel, Field


class HospitalItem(BaseModel):
    id: int
    code: str
    name: str
    short_name: str | None = None
    is_active: bool
    created_at: datetime


class HospitalCreateRequest(BaseModel):
    code: str | None = Field(default=None, min_length=2, max_length=50)
    name: str = Field(min_length=2, max_length=100)
    short_name: str | None = Field(default=None, min_length=1, max_length=100)


class HospitalUpdateRequest(BaseModel):
    code: str | None = Field(default=None, min_length=2, max_length=50)
    name: str | None = Field(default=None, min_length=2, max_length=100)
    short_name: str | None = Field(default=None, min_length=1, max_length=100)
    is_active: bool | None = None


class HospitalAssignUsersRequest(BaseModel):
    user_ids: list[int] = Field(default_factory=list)
    mode: Literal["append", "replace"] = "append"


class ApiResponse(BaseModel):
    code: int
    message: str
    data: HospitalItem | list[HospitalItem] | None = None
