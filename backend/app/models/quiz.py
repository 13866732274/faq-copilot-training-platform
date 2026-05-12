from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Quiz(Base):
    __tablename__ = "quizzes"
    __table_args__ = (
        Index("idx_category", "category"),
        Index("idx_chat_type", "chat_type"),
        Index("idx_quiz_scope", "scope"),
        Index("idx_quiz_hospital", "hospital_id"),
        Index("idx_quiz_department", "department_id"),
        Index("idx_quiz_tenant", "tenant_id"),
        Index("idx_quiz_content_hash", "content_hash"),
        Index("idx_active_deleted", "is_active", "is_deleted"),
        Index("idx_quiz_deleted_scope_hospital_id", "is_deleted", "scope", "hospital_id", "id"),
        Index("idx_quiz_deleted_scope_department_id", "is_deleted", "scope", "department_id", "id"),
        Index("idx_quiz_tenant_scope_chat_hash", "tenant_id", "scope", "chat_type", "content_hash"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    scope: Mapped[str] = mapped_column(
        Enum("common", "hospital", "department", name="quiz_scope"),
        nullable=False,
        default="hospital",
    )
    hospital_id: Mapped[int | None] = mapped_column(
        ForeignKey("hospitals.id", ondelete="SET NULL"),
        nullable=True,
    )
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("departments.id", ondelete="SET NULL"),
        nullable=True,
    )
    chat_type: Mapped[str] = mapped_column(String(20), nullable=False, default="passive")
    difficulty: Mapped[int] = mapped_column(Integer, default=1)
    tags: Mapped[str | None] = mapped_column(String(500), nullable=True)
    patient_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    counselor_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    source_file: Mapped[str | None] = mapped_column(String(500), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    creator: Mapped["User | None"] = relationship(back_populates="quizzes")
    hospital: Mapped["Hospital | None"] = relationship(back_populates="quizzes")
    department: Mapped["Department | None"] = relationship(back_populates="quizzes")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="quiz", cascade="all, delete-orphan"
    )
    practices: Mapped[list["Practice"]] = relationship(back_populates="quiz")
    versions: Mapped[list["QuizVersion"]] = relationship(
        back_populates="quiz",
        cascade="all, delete-orphan",
        order_by="QuizVersion.version_no.desc()",
    )
