"""add faq_task_timeout_minutes to system_settings

Revision ID: 20260313_06
Revises: 20260313_05
"""

import sqlalchemy as sa
from alembic import op

revision = "20260313_06"
down_revision = "20260313_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column("faq_task_timeout_minutes", sa.Integer(), nullable=False, server_default="15"),
    )
    op.alter_column("system_settings", "faq_task_timeout_minutes", server_default=None)


def downgrade() -> None:
    op.drop_column("system_settings", "faq_task_timeout_minutes")
