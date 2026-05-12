from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Practice(Base):
    __tablename__ = "practices"
    __table_args__ = (
        Index("idx_practice_quiz", "quiz_id"),
        Index("idx_practice_department", "department_id"),
        Index("idx_practice_status", "status"),
        Index("idx_practice_tenant", "tenant_id"),
        Index("idx_practice_user_id", "user_id", "id"),
        Index("idx_practice_hospital_created_at", "hospital_id", "created_at"),
        Index("idx_practice_user_tenant", "user_id", "tenant_id"),
        Index("idx_practice_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False)
    hospital_id: Mapped[int | None] = mapped_column(
        ForeignKey("hospitals.id", ondelete="SET NULL"),
        nullable=True,
    )
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("departments.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        Enum("in_progress", "completed", name="practice_status"),
        nullable=False,
        default="in_progress",
    )
    current_step: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="practices")
    quiz: Mapped["Quiz"] = relationship(back_populates="practices")
    hospital: Mapped["Hospital | None"] = relationship(back_populates="practices")
    department: Mapped["Department | None"] = relationship(back_populates="practices")
    replies: Mapped[list["PracticeReply"]] = relationship(
        back_populates="practice", cascade="all, delete-orphan"
    )
    comments: Mapped[list["PracticeComment"]] = relationship(
        back_populates="practice", cascade="all, delete-orphan"
    )
