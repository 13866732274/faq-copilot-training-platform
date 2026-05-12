"""add stage_durations_json to faq_tasks

Revision ID: 20260313_08
Revises: 20260313_07
"""

import sqlalchemy as sa
from alembic import op

revision = "20260313_08"
down_revision = "20260313_07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "faq_tasks",
        sa.Column("stage_durations_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("faq_tasks", "stage_durations_json")
