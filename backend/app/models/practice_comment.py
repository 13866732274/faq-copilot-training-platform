from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PracticeComment(Base):
    __tablename__ = "practice_comments"
    __table_args__ = (
        Index("idx_comment_practice", "practice_id"),
        Index("idx_comment_admin", "admin_id"),
        Index("idx_comment_tenant", "tenant_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="SET NULL"),
        nullable=True,
    )
    practice_id: Mapped[int] = mapped_column(
        ForeignKey("practices.id", ondelete="CASCADE"), nullable=False
    )
    admin_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    practice: Mapped["Practice"] = relationship(back_populates="comments")
    admin: Mapped["User"] = relationship(back_populates="practice_comments")
