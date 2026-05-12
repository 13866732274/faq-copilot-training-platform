from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PracticeReply(Base):
    __tablename__ = "practice_replies"
    __table_args__ = (
        Index("idx_reply_message", "message_id"),
        Index("idx_reply_tenant", "tenant_id"),
        UniqueConstraint("practice_id", "message_id", name="uq_practice_message"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="SET NULL"),
        nullable=True,
    )
    practice_id: Mapped[int] = mapped_column(
        ForeignKey("practices.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    reply_content: Mapped[str] = mapped_column(Text, nullable=False)
    reply_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    practice: Mapped["Practice"] = relationship(back_populates="replies")
    message: Mapped["Message"] = relationship()
