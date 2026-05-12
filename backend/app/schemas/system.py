from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class SystemSettingsItem(BaseModel):
    site_name: str
    site_subtitle: str
    logo_url: str | None = None
    brand_accent: str
    enable_ai_scoring: bool
    enable_export_center: bool
    enable_audit_enhanced: bool
    admin_menu_template_lock: bool
    faq_task_timeout_minutes: int
    updated_at: datetime


class PublicSystemSettingsItem(BaseModel):
    site_name: str
    site_subtitle: str
    logo_url: str | None = None
    brand_accent: str
    default_tenant_code: str | None = None
    show_tenant_input: bool = False


class SystemSettingsUpdateRequest(BaseModel):
    site_name: str = Field(min_length=2, max_length=120)
    site_subtitle: str = Field(min_length=2, max_length=120)
    logo_url: str | None = Field(default=None, max_length=500)
    brand_accent: str = Field(min_length=4, max_length=20)
    enable_ai_scoring: bool
    enable_export_center: bool
    enable_audit_enhanced: bool
    admin_menu_template_lock: bool
    faq_task_timeout_minutes: int = Field(default=15, ge=5, le=30)

    @field_validator("faq_task_timeout_minutes")
    @classmethod
    def validate_faq_task_timeout_minutes(cls, v: int) -> int:
        if v not in {5, 15, 30}:
            raise ValueError("FAQ 任务超时阈值仅支持 5/15/30 分钟")
        return v


class ApiResponse(BaseModel):
    code: int
    message: str
    data: SystemSettingsItem | PublicSystemSettingsItem | None = None
