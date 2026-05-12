"""add retry_from_task_id to faq_tasks

Revision ID: 20260313_04
Revises: 20260313_03
"""

import sqlalchemy as sa
from alembic import op

revision = "20260313_04"
down_revision = "20260313_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("faq_tasks", sa.Column("retry_from_task_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_faq_tasks_retry_from_task_id",
        "faq_tasks",
        "faq_tasks",
        ["retry_from_task_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_faq_task_retry_from", "faq_tasks", ["retry_from_task_id"])


def downgrade() -> None:
    op.drop_index("idx_faq_task_retry_from", table_name="faq_tasks")
    op.drop_constraint("fk_faq_tasks_retry_from_task_id", "faq_tasks", type_="foreignkey")
    op.drop_column("faq_tasks", "retry_from_task_id")
