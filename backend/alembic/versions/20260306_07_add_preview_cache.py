"""add preview cache table

Revision ID: 20260306_07
Revises: 20260306_06
Create Date: 2026-03-06 20:05:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260306_07"
down_revision = "20260306_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "preview_cache",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_preview_cache_expires_at", "preview_cache", ["expires_at"])
    op.create_index("idx_preview_cache_created_at", "preview_cache", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_preview_cache_created_at", table_name="preview_cache")
    op.drop_index("idx_preview_cache_expires_at", table_name="preview_cache")
    op.drop_table("preview_cache")
