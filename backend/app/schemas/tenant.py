from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TenantItem(BaseModel):
    id: int
    code: str
    name: str
    is_active: bool
    session_version: int
    created_at: datetime
    updated_at: datetime


class TenantCreateRequest(BaseModel):
    code: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=1, max_length=120)


class TenantUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    is_active: bool | None = None


class TenantListData(BaseModel):
    items: list[TenantItem]
    total: int


class ModuleDefinitionItem(BaseModel):
    module_id: str
    name: str
    description: str | None = None
    icon: str | None = None
    menu_keys: list[str] = []
    permission_points: list[str] = []
    dependencies: list[str] = []
    is_default: bool = False
    sort_order: int = 0


class ModuleDefinitionListData(BaseModel):
    items: list[ModuleDefinitionItem]
    total: int


class TenantModuleItem(BaseModel):
    tenant_id: int
    module_id: str
    name: str
    description: str | None = None
    icon: str | None = None
    menu_keys: list[str] = []
    dependencies: list[str] = []
    depended_by: list[str] = []
    is_default: bool = False
    is_enabled: bool
    source: str
    enabled_at: datetime | None = None
    disabled_at: datetime | None = None
    sort_order: int = 0


class TenantModuleListData(BaseModel):
    tenant_id: int
    tenant_name: str
    items: list[TenantModuleItem]
    total: int


class TenantModuleUpdateRequest(BaseModel):
    module_id: str = Field(min_length=2, max_length=50)
    is_enabled: bool
    config_json: str | None = None


class ApiResponse(BaseModel):
    code: int
    message: str
    data: (
        TenantItem
        | TenantListData
        | ModuleDefinitionListData
        | TenantModuleListData
        | None
    ) = None
