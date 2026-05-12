from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class FaqCluster(Base):
    __tablename__ = "faq_clusters"
    __table_args__ = (
        Index("idx_faq_cluster_tenant", "tenant_id"),
        Index("idx_faq_cluster_category", "category"),
        Index("idx_faq_cluster_active", "is_active"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tags: Mapped[str | None] = mapped_column(String(500), nullable=True)
    representative_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    best_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    question_count: Mapped[int] = mapped_column(default=0, nullable=False)
    answer_count: Mapped[int] = mapped_column(default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    is_locked: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False,
    )

    questions: Mapped[list["FaqQuestion"]] = relationship(
        back_populates="cluster", cascade="all, delete-orphan",
    )
    answers: Mapped[list["FaqAnswer"]] = relationship(
        back_populates="cluster", cascade="all, delete-orphan",
    )
