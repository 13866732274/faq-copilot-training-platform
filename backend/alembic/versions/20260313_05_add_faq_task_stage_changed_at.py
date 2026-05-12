"""add stage_changed_at to faq_tasks

Revision ID: 20260313_05
Revises: 20260313_04
"""

import sqlalchemy as sa
from alembic import op

revision = "20260313_05"
down_revision = "20260313_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("faq_tasks", sa.Column("stage_changed_at", sa.DateTime(), nullable=True))
    op.create_index("idx_faq_task_stage_changed_at", "faq_tasks", ["stage_changed_at"])


def downgrade() -> None:
    op.drop_index("idx_faq_task_stage_changed_at", table_name="faq_tasks")
    op.drop_column("faq_tasks", "stage_changed_at")
