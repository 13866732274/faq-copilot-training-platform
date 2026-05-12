"""add hospital short_name field

Revision ID: 20260307_02
Revises: 20260307_01
Create Date: 2026-03-07
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260307_02"
down_revision = "20260307_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("hospitals", sa.Column("short_name", sa.String(length=100), nullable=True))
    op.execute(
        """
        UPDATE hospitals
        SET short_name = CASE
            WHEN name LIKE '%耳鼻咽喉科' THEN TRIM(REPLACE(name, '耳鼻咽喉科', ''))
            ELSE name
        END
        WHERE short_name IS NULL OR short_name = ''
        """
    )


def downgrade() -> None:
    op.drop_column("hospitals", "short_name")
