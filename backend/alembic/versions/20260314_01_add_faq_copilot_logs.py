"""add faq_copilot_logs table

Revision ID: 20260314_01
Revises: 20260313_08
"""

import sqlalchemy as sa
from alembic import op

revision = "20260314_01"
down_revision = "20260313_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "faq_copilot_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("mode", sa.String(20), nullable=False, server_default="copilot"),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("reply", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("sources_json", sa.Text(), nullable=True),
        sa.Column("matched_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_copilot_log_tenant", "faq_copilot_logs", ["tenant_id"])
    op.create_index("idx_copilot_log_user", "faq_copilot_logs", ["user_id"])
    op.create_index("idx_copilot_log_created", "faq_copilot_logs", ["created_at"])


def downgrade() -> None:
    op.drop_table("faq_copilot_logs")
