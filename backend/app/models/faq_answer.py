from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class FaqAnswer(Base):
    __tablename__ = "faq_answers"
    __table_args__ = (
        Index("idx_faq_answer_cluster", "cluster_id"),
        Index("idx_faq_answer_quiz", "quiz_id"),
        Index("idx_faq_answer_tenant", "tenant_id"),
        Index("idx_faq_answer_quality", "quality_score"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True,
    )
    cluster_id: Mapped[int] = mapped_column(
        ForeignKey("faq_clusters.id", ondelete="CASCADE"), nullable=False,
    )
    quiz_id: Mapped[int | None] = mapped_column(
        ForeignKey("quizzes.id", ondelete="SET NULL"), nullable=True,
    )
    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    quality_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    is_best: Mapped[bool] = mapped_column(default=False, nullable=False)
    upvotes: Mapped[int] = mapped_column(default=0, nullable=False)
    source_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False,
    )

    cluster: Mapped["FaqCluster"] = relationship(back_populates="answers")
