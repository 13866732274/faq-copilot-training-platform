from __future__ import annotations

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str
    tenant_code: str | None = None


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class ProfileUpdateRequest(BaseModel):
    real_name: str | None = None
    avatar: str | None = None


class LoginUser(BaseModel):
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
    avatar: str | None = None
    tenant_id: int | None = None
    tenant_name: str | None = None
    is_platform_super_admin: bool = False
    is_impersonating: bool = False
    impersonation_tenant_id: int | None = None
    impersonation_tenant_name: str | None = None
    impersonation_expires_at: str | None = None
    impersonation_reason: str | None = None
    enabled_modules: list[str] = []


class LoginData(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: LoginUser


class MeData(BaseModel):
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
    avatar: str | None = None
    tenant_id: int | None = None
    tenant_name: str | None = None
    is_platform_super_admin: bool = False
    is_impersonating: bool = False
    impersonation_tenant_id: int | None = None
    impersonation_tenant_name: str | None = None
    impersonation_expires_at: str | None = None
    impersonation_reason: str | None = None
    enabled_modules: list[str] = []


class ImpersonationStartRequest(BaseModel):
    tenant_id: int
    reason: str | None = None
    duration_minutes: int = 30


class LoginHistoryItem(BaseModel):
    id: int
    status: str
    ip: str | None = None
    reason: str | None = None
    created_at: str


class PasswordChangeData(BaseModel):
    updated: bool = True


class ProfileUpdateData(BaseModel):
    id: int
    username: str
    real_name: str
    avatar: str | None = None


class PermissionPointItem(BaseModel):
    point: str
    allowed: bool
    reason: str = ""


class MenuAccessItem(BaseModel):
    menu_key: str
    allowed: bool
    reason: str = ""


class PermissionPointsData(BaseModel):
    points: list[PermissionPointItem]
    menus: list[MenuAccessItem] = []


class ApiResponse(BaseModel):
    code: int
    message: str
    data: (
        LoginData
        | MeData
        | PasswordChangeData
        | ProfileUpdateData
        | PermissionPointsData
        | list[LoginHistoryItem]
        | None
    ) = None
