"""add content_hash to quizzes

Revision ID: 20260308_02
Revises: 20260308_01
Create Date: 2026-03-08 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260308_02"
down_revision = "20260308_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("quizzes", sa.Column("content_hash", sa.String(length=64), nullable=True))
    op.create_index("idx_quiz_content_hash", "quizzes", ["content_hash"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_quiz_content_hash", table_name="quizzes")
    op.drop_column("quizzes", "content_hash")
