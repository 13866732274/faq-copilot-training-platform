"""add menu_permissions to users

Revision ID: 20260308_01
Revises: 20260307_02
Create Date: 2026-03-08 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260308_01"
down_revision = "20260307_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("menu_permissions", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "menu_permissions")
