from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

DEFAULT_RISK_KEYWORDS = "费用,价格,多少钱,收费,医保,报销,疗程,疗效,副作用,禁忌,复发,手术,住院,风险,药物,孕妇,儿童,老人"


class SystemSetting(Base):
    __tablename__ = "system_settings"
    __table_args__ = (
        Index("idx_system_settings_tenant", "tenant_id"),
        Index("idx_system_settings_updated_at", "updated_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True)
    site_name: Mapped[str] = mapped_column(String(120), nullable=False, default="咨询话术模拟训练系统")
    site_subtitle: Mapped[str] = mapped_column(String(120), nullable=False, default="运营管理中台")
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    brand_accent: Mapped[str] = mapped_column(String(20), nullable=False, default="#07c160")
    enable_ai_scoring: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enable_export_center: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    enable_audit_enhanced: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    admin_menu_template_lock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    faq_task_timeout_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    copilot_risk_keywords: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=DEFAULT_RISK_KEYWORDS,
    )
    faq_similarity_threshold: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.35,
    )
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
