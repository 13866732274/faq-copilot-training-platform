"""add performance indexes for stats and lists

Revision ID: 20260309_01
Revises: 20260308_02
Create Date: 2026-03-09 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260309_01"
down_revision = "20260308_02"
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


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    if not _index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=False)


def _drop_index_if_exists(index_name: str, table_name: str) -> None:
    if _index_exists(table_name, index_name):
        op.drop_index(index_name, table_name=table_name)


def upgrade() -> None:
    _create_index_if_missing("idx_practice_user_id", "practices", ["user_id", "id"])
    _create_index_if_missing("idx_practice_hospital_created_at", "practices", ["hospital_id", "created_at"])
    _create_index_if_missing(
        "idx_quiz_deleted_scope_hospital_id", "quizzes", ["is_deleted", "scope", "hospital_id", "id"]
    )
    _create_index_if_missing(
        "idx_quiz_deleted_scope_department_id", "quizzes", ["is_deleted", "scope", "department_id", "id"]
    )
    _create_index_if_missing("idx_audit_logs_action_created_id", "audit_logs", ["action", "created_at", "id"])
    _create_index_if_missing(
        "idx_user_role_hospital_department", "users", ["role", "hospital_id", "department_id"]
    )


def downgrade() -> None:
    _drop_index_if_exists("idx_user_role_hospital_department", "users")
    _drop_index_if_exists("idx_audit_logs_action_created_id", "audit_logs")
    _drop_index_if_exists("idx_quiz_deleted_scope_department_id", "quizzes")
    _drop_index_if_exists("idx_quiz_deleted_scope_hospital_id", "quizzes")
    _drop_index_if_exists("idx_practice_hospital_created_at", "practices")
    _drop_index_if_exists("idx_practice_user_id", "practices")
