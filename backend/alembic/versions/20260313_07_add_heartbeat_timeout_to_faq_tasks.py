"""add heartbeat_timeout_minutes to faq_tasks

Revision ID: 20260313_07
Revises: 20260313_06
"""

import sqlalchemy as sa
from alembic import op

revision = "20260313_07"
down_revision = "20260313_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "faq_tasks",
        sa.Column("heartbeat_timeout_minutes", sa.Integer(), nullable=False, server_default="15"),
    )
    op.alter_column("faq_tasks", "heartbeat_timeout_minutes", server_default=None)


def downgrade() -> None:
    op.drop_column("faq_tasks", "heartbeat_timeout_minutes")
