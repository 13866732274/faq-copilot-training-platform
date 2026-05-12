"""expand faq_copilot_logs.mode length

Revision ID: 20260314_02
Revises: 20260314_01
"""

import sqlalchemy as sa
from alembic import op

revision = "20260314_02"
down_revision = "20260314_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "faq_copilot_logs",
        "mode",
        existing_type=sa.String(length=20),
        type_=sa.String(length=64),
        existing_nullable=False,
        existing_server_default="copilot",
    )


def downgrade() -> None:
    op.alter_column(
        "faq_copilot_logs",
        "mode",
        existing_type=sa.String(length=64),
        type_=sa.String(length=20),
        existing_nullable=False,
        existing_server_default="copilot",
    )
