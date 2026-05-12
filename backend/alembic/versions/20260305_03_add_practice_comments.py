"""add practice comments

Revision ID: 20260305_03
Revises: 20260305_02
Create Date: 2026-03-05 16:48:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260305_03"
down_revision = "20260305_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "practice_comments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("practice_id", sa.Integer(), nullable=False),
        sa.Column("admin_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["practice_id"], ["practices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["admin_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_comment_practice", "practice_comments", ["practice_id"], unique=False)
    op.create_index("idx_comment_admin", "practice_comments", ["admin_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_comment_admin", table_name="practice_comments")
    op.drop_index("idx_comment_practice", table_name="practice_comments")
    op.drop_table("practice_comments")
