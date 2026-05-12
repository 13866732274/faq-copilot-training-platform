"""add quiz_versions and bulk import support

Revision ID: 20260306_03
Revises: 20260306_02
Create Date: 2026-03-06 22:10:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260306_03"
down_revision = "20260306_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quiz_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("quiz_id", sa.Integer(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("source_file", sa.String(length=500), nullable=True),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["quiz_id"], ["quizzes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_quiz_version_quiz", "quiz_versions", ["quiz_id"], unique=False)
    op.create_index("idx_quiz_version_no", "quiz_versions", ["quiz_id", "version_no"], unique=False)

    op.execute(
        """
        INSERT INTO quiz_versions (quiz_id, version_no, source_file, message_count, created_by)
        SELECT id, 1, source_file, message_count, created_by
        FROM quizzes
        WHERE is_deleted = 0
        """
    )


def downgrade() -> None:
    op.drop_index("idx_quiz_version_no", table_name="quiz_versions")
    op.drop_index("idx_quiz_version_quiz", table_name="quiz_versions")
    op.drop_table("quiz_versions")
