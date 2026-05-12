"""add usage_records table

Revision ID: 20260313_03
Revises: 20260313_02
"""

import sqlalchemy as sa
from alembic import op

revision = "20260313_03"
down_revision = "20260313_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usage_records",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("module_id", sa.String(length=50), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False, server_default="api_request"),
        sa.Column("endpoint", sa.String(length=255), nullable=True),
        sa.Column("method", sa.String(length=10), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("unit", sa.String(length=20), nullable=False, server_default="request"),
        sa.Column("cost_estimate", sa.Numeric(18, 6), nullable=True),
        sa.Column("meta_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_usage_records_tenant", "usage_records", ["tenant_id"])
    op.create_index("idx_usage_records_user", "usage_records", ["user_id"])
    op.create_index("idx_usage_records_module", "usage_records", ["module_id"])
    op.create_index("idx_usage_records_created_at", "usage_records", ["created_at"])
    op.create_index(
        "idx_usage_records_tenant_module_created",
        "usage_records",
        ["tenant_id", "module_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_usage_records_tenant_module_created", table_name="usage_records")
    op.drop_index("idx_usage_records_created_at", table_name="usage_records")
    op.drop_index("idx_usage_records_module", table_name="usage_records")
    op.drop_index("idx_usage_records_user", table_name="usage_records")
    op.drop_index("idx_usage_records_tenant", table_name="usage_records")
    op.drop_table("usage_records")

