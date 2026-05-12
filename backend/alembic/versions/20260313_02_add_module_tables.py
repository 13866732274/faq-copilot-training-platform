"""add module_definitions and tenant_modules tables

Revision ID: 20260313_02
Revises: 20260313_01
"""

import sqlalchemy as sa
from alembic import op

revision = "20260313_02"
down_revision = "20260313_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "module_definitions",
        sa.Column("module_id", sa.String(length=50), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("icon", sa.String(length=50), nullable=True),
        sa.Column("menu_keys", sa.Text(), nullable=False),
        sa.Column("permission_points", sa.Text(), nullable=True),
        sa.Column("dependencies", sa.Text(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "tenant_modules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "module_id",
            sa.String(length=50),
            sa.ForeignKey("module_definitions.module_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("enabled_at", sa.DateTime(), nullable=True),
        sa.Column("disabled_at", sa.DateTime(), nullable=True),
        sa.Column("config_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "module_id", name="uk_tenant_module"),
    )
    op.create_index("idx_tenant_modules_tenant", "tenant_modules", ["tenant_id"])
    op.create_index("idx_tenant_modules_module", "tenant_modules", ["module_id"])
    op.create_index("idx_tenant_modules_enabled", "tenant_modules", ["is_enabled"])


def downgrade() -> None:
    op.drop_index("idx_tenant_modules_enabled", table_name="tenant_modules")
    op.drop_index("idx_tenant_modules_module", table_name="tenant_modules")
    op.drop_index("idx_tenant_modules_tenant", table_name="tenant_modules")
    op.drop_table("tenant_modules")
    op.drop_table("module_definitions")

