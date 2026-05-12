from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class UserItem(BaseModel):
    id: int
    username: str
    real_name: str
    role: str
    hospital_id: int | None = None
    hospital_name: str | None = None
    hospital_ids: list[int] = []
    department_id: int | None = None
    department_name: str | None = None
    department_ids: list[int] = []
    menu_permissions: list[str] | None = None
    is_all_hospitals: bool = False
    is_active: bool
    tenant_id: int | None = None
    tenant_name: str | None = None
    created_at: datetime


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6, max_length=100)
    real_name: str = Field(min_length=1, max_length=50)
    role: str = Field(default="student")
    hospital_id: int | None = None
    hospital_ids: list[int] = []
    department_id: int | None = None
    department_ids: list[int] = []
    menu_permissions: list[str] | None = None
    is_all_hospitals: bool = False
    tenant_id: int | None = None


class UserUpdateRequest(BaseModel):
    real_name: str | None = Field(default=None, max_length=50)
    role: str | None = None
    password: str | None = Field(default=None, min_length=6, max_length=100)
    hospital_id: int | None = None
    hospital_ids: list[int] | None = None
    department_id: int | None = None
    department_ids: list[int] | None = None
    menu_permissions: list[str] | None = None
    is_all_hospitals: bool | None = None
    tenant_id: int | None = None


class BulkUserImportItem(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    real_name: str = Field(min_length=1, max_length=50)
    password: str | None = Field(default=None, min_length=6, max_length=100)
    hospital_id: int | None = None
    department_id: int | None = None


class BulkUserImportRequest(BaseModel):
    role: str = Field(default="student")
    hospital_id: int | None = None
    department_id: int | None = None
    default_password: str = Field(default="123456", min_length=6, max_length=100)
    items: list[BulkUserImportItem]


class BulkUserImportData(BaseModel):
    total: int
    created: int
    skipped: int
    errors: list[str] = []
    failed_items: list[dict[str, str | int]] = []


class BulkUserStatusRequest(BaseModel):
    user_ids: list[int] = []
    is_active: bool = False


class BulkUserStatusData(BaseModel):
    total: int
    updated: int
    skipped: int
    skipped_user_ids: list[int] = []


class BulkUserMenuPermissionsRequest(BaseModel):
    user_ids: list[int] = []
    menu_permissions: list[str] | None = None


class BulkUserMenuPermissionsData(BaseModel):
    total: int
    updated: int
    skipped: int
    skipped_user_ids: list[int] = []
    skipped_reason_ids: dict[str, list[int]] = {}


class UserListData(BaseModel):
    items: list[UserItem]
    total: int
    page: int
    page_size: int


class ApiResponse(BaseModel):
    code: int
    message: str
    data: UserItem | UserListData | BulkUserImportData | BulkUserStatusData | BulkUserMenuPermissionsData | None = None
