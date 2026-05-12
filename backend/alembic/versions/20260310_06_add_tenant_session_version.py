"""add tenants.session_version for mass session invalidation

Revision ID: 20260310_06
Revises: 20260310_05
Create Date: 2026-03-10 17:55:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260310_06"
down_revision = "20260310_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("session_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.execute(sa.text("UPDATE tenants SET session_version = 1 WHERE session_version IS NULL"))


def downgrade() -> None:
    op.drop_column("tenants", "session_version")
