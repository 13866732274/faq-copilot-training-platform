"""drop redundant single-column indexes

Revision ID: 20260309_02
Revises: 20260309_01
Create Date: 2026-03-09 00:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260309_02"
down_revision = "20260309_01"
branch_labels = None
depends_on = None


def _index_exists(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    stmt = sa.text(
        """
        SELECT 1
        FROM information_schema.statistics
        WHERE table_schema = DATABASE()
          AND table_name = :table_name
          AND index_name = :index_name
        LIMIT 1
        """
    )
    return bool(bind.execute(stmt, {"table_name": table_name, "index_name": index_name}).scalar())


def _drop_if_exists(index_name: str, table_name: str) -> None:
    if _index_exists(table_name, index_name):
        op.drop_index(index_name, table_name=table_name)


def _create_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    if not _index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=False)


def upgrade() -> None:
    _drop_if_exists("idx_hospital_code", "hospitals")
    _drop_if_exists("idx_reply_practice", "practice_replies")
    _drop_if_exists("idx_user_hospitals_user", "user_hospitals")
    _drop_if_exists("idx_user_departments_user", "user_departments")
    _drop_if_exists("idx_quiz_version_quiz", "quiz_versions")


def downgrade() -> None:
    _create_if_missing("idx_hospital_code", "hospitals", ["code"])
    _create_if_missing("idx_reply_practice", "practice_replies", ["practice_id"])
    _create_if_missing("idx_user_hospitals_user", "user_hospitals", ["user_id"])
    _create_if_missing("idx_user_departments_user", "user_departments", ["user_id"])
    _create_if_missing("idx_quiz_version_quiz", "quiz_versions", ["quiz_id"])
