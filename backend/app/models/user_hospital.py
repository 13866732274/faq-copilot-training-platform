from __future__ import annotations

from sqlalchemy import ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class UserHospital(Base):
    __tablename__ = "user_hospitals"
    __table_args__ = (
        Index("idx_user_hospitals_hospital", "hospital_id"),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    hospital_id: Mapped[int] = mapped_column(
        ForeignKey("hospitals.id", ondelete="CASCADE"),
        primary_key=True,
    )

    user: Mapped["User"] = relationship(back_populates="hospital_links")
    hospital: Mapped["Hospital"] = relationship(back_populates="user_links")
