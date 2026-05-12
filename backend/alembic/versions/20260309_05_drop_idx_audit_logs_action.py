"""drop idx_audit_logs_action in phase-2

Revision ID: 20260309_05
Revises: 20260309_04
Create Date: 2026-03-09 01:20:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260309_05"
down_revision = "20260309_04"
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


def upgrade() -> None:
    if _index_exists("audit_logs", "idx_audit_logs_action"):
        op.drop_index("idx_audit_logs_action", table_name="audit_logs")


def downgrade() -> None:
    if not _index_exists("audit_logs", "idx_audit_logs_action"):
        op.create_index("idx_audit_logs_action", "audit_logs", ["action"], unique=False)
