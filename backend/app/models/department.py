from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Department(Base):
    __tablename__ = "departments"
    __table_args__ = (
        Index("idx_dept_hospital", "hospital_id"),
        Index("idx_dept_active", "is_active"),
        Index("idx_dept_tenant", "tenant_id"),
        Index("idx_dept_tenant_active", "tenant_id", "is_active"),
        Index("idx_dept_hospital_tenant", "hospital_id", "tenant_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="SET NULL"),
        nullable=True,
    )
    hospital_id: Mapped[int] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    hospital: Mapped["Hospital"] = relationship(back_populates="departments")
    users: Mapped[list["User"]] = relationship(back_populates="department")
    user_links: Mapped[list["UserDepartment"]] = relationship(
        back_populates="department",
        cascade="all, delete-orphan",
    )
    quizzes: Mapped[list["Quiz"]] = relationship(back_populates="department")
    practices: Mapped[list["Practice"]] = relationship(back_populates="department")
