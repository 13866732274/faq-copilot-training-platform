"""add quiz chat type

Revision ID: 20260306_01
Revises: 20260305_03
Create Date: 2026-03-06 09:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260306_01"
down_revision = "20260305_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "quizzes",
        sa.Column("chat_type", sa.String(length=20), nullable=False, server_default="passive"),
    )
    op.create_index("idx_chat_type", "quizzes", ["chat_type"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_chat_type", table_name="quizzes")
    op.drop_column("quizzes", "chat_type")

