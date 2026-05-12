from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "username", name="uq_user_tenant_username"),
        Index("idx_role", "role"),
        Index("idx_active", "is_active"),
        Index("idx_user_hospital", "hospital_id"),
        Index("idx_user_department", "department_id"),
        Index("idx_user_tenant", "tenant_id"),
        Index("idx_user_all_hospitals", "is_all_hospitals"),
        Index("idx_user_role_hospital_department", "role", "hospital_id", "department_id"),
        Index("idx_user_role_tenant", "role", "tenant_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    real_name: Mapped[str] = mapped_column(String(50), nullable=False)
    role: Mapped[str] = mapped_column(
        Enum("super_admin", "admin", "student", name="user_role"),
        default="student",
        nullable=False,
    )
    avatar: Mapped[str | None] = mapped_column(String(500), nullable=True)
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="SET NULL"),
        nullable=True,
    )
    hospital_id: Mapped[int | None] = mapped_column(
        ForeignKey("hospitals.id", ondelete="SET NULL"),
        nullable=True,
    )
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("departments.id", ondelete="SET NULL"),
        nullable=True,
    )
    menu_permissions: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_all_hospitals: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    tenant: Mapped["Tenant | None"] = relationship(back_populates="users")
    hospital: Mapped["Hospital | None"] = relationship(back_populates="users")
    department: Mapped["Department | None"] = relationship(back_populates="users")
    hospital_links: Mapped[list["UserHospital"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    department_links: Mapped[list["UserDepartment"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    quizzes: Mapped[list["Quiz"]] = relationship(back_populates="creator")
    practices: Mapped[list["Practice"]] = relationship(back_populates="user")
    practice_comments: Mapped[list["PracticeComment"]] = relationship(back_populates="admin")
