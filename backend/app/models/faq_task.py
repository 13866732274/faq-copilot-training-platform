from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FaqTask(Base):
    __tablename__ = "faq_tasks"
    __table_args__ = (
        Index("idx_faq_task_tenant", "tenant_id"),
        Index("idx_faq_task_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True,
    )
    operator_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    retry_from_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("faq_tasks.id", ondelete="SET NULL"), nullable=True,
    )
    status: Mapped[str] = mapped_column(
        Enum("pending", "extracting", "embedding", "clustering", "refining", "completed", "failed",
             name="faq_task_status"),
        default="pending", nullable=False,
    )
    total_quizzes: Mapped[int] = mapped_column(default=0, nullable=False)
    total_messages: Mapped[int] = mapped_column(default=0, nullable=False)
    extracted_pairs: Mapped[int] = mapped_column(default=0, nullable=False)
    clusters_created: Mapped[int] = mapped_column(default=0, nullable=False)
    clusters_updated: Mapped[int] = mapped_column(default=0, nullable=False)
    heartbeat_timeout_minutes: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    stage_durations_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    config_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    stage_changed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False,
    )
