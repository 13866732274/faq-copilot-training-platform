"""add tenants and users.tenant_id

Revision ID: 20260310_03
Revises: 20260310_02
Create Date: 2026-03-10 20:05:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260310_03"
down_revision = "20260310_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            server_onupdate=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index("idx_tenant_code", "tenants", ["code"], unique=False)
    op.create_index("idx_tenant_active", "tenants", ["is_active"], unique=False)

    op.add_column("users", sa.Column("tenant_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_users_tenant_id", "users", "tenants", ["tenant_id"], ["id"], ondelete="SET NULL")
    op.create_index("idx_user_tenant", "users", ["tenant_id"], unique=False)
    op.create_index("idx_user_role_tenant", "users", ["role", "tenant_id"], unique=False)

    op.execute(
        sa.text(
            """
            INSERT INTO tenants (id, code, name, is_active)
            VALUES (1, 'default', '默认租户', 1)
            """
        )
    )
    op.execute(sa.text("UPDATE users SET tenant_id = 1 WHERE tenant_id IS NULL"))


def downgrade() -> None:
    op.drop_index("idx_user_role_tenant", table_name="users")
    op.drop_index("idx_user_tenant", table_name="users")
    op.drop_constraint("fk_users_tenant_id", "users", type_="foreignkey")
    op.drop_column("users", "tenant_id")

    op.drop_index("idx_tenant_active", table_name="tenants")
    op.drop_index("idx_tenant_code", table_name="tenants")
    op.drop_table("tenants")
