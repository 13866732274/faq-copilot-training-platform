"""add tenant_id for management tables

Revision ID: 20260310_05
Revises: 20260310_04
Create Date: 2026-03-10 22:05:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260310_05"
down_revision = "20260310_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_logs", sa.Column("tenant_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_audit_logs_tenant_id", "audit_logs", "tenants", ["tenant_id"], ["id"], ondelete="SET NULL")
    op.create_index("idx_audit_logs_tenant", "audit_logs", ["tenant_id"], unique=False)

    op.add_column("system_settings", sa.Column("tenant_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_system_settings_tenant_id",
        "system_settings",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_system_settings_tenant", "system_settings", ["tenant_id"], unique=False)

    op.add_column("import_tasks", sa.Column("tenant_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_import_tasks_tenant_id",
        "import_tasks",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_import_tasks_tenant", "import_tasks", ["tenant_id"], unique=False)

    # 回填 audit_logs：优先 user -> hospital -> department -> 默认
    op.execute(
        sa.text(
            """
            UPDATE audit_logs a
            LEFT JOIN users u ON u.id = a.user_id
            LEFT JOIN hospitals h ON h.id = a.hospital_id
            LEFT JOIN departments d ON d.id = a.department_id
            SET a.tenant_id = COALESCE(u.tenant_id, h.tenant_id, d.tenant_id, 1)
            WHERE a.tenant_id IS NULL
            """
        )
    )
    # 回填 system_settings：历史单租户配置归属默认租户
    op.execute(sa.text("UPDATE system_settings SET tenant_id = 1 WHERE tenant_id IS NULL"))
    # 回填 import_tasks：优先 operator -> hospital -> department -> 默认
    op.execute(
        sa.text(
            """
            UPDATE import_tasks t
            LEFT JOIN users u ON u.id = t.operator_id
            LEFT JOIN hospitals h ON h.id = t.hospital_id
            LEFT JOIN departments d ON d.id = t.department_id
            SET t.tenant_id = COALESCE(u.tenant_id, h.tenant_id, d.tenant_id, 1)
            WHERE t.tenant_id IS NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_index("idx_import_tasks_tenant", table_name="import_tasks")
    op.drop_constraint("fk_import_tasks_tenant_id", "import_tasks", type_="foreignkey")
    op.drop_column("import_tasks", "tenant_id")

    op.drop_index("idx_system_settings_tenant", table_name="system_settings")
    op.drop_constraint("fk_system_settings_tenant_id", "system_settings", type_="foreignkey")
    op.drop_column("system_settings", "tenant_id")

    op.drop_index("idx_audit_logs_tenant", table_name="audit_logs")
    op.drop_constraint("fk_audit_logs_tenant_id", "audit_logs", type_="foreignkey")
    op.drop_column("audit_logs", "tenant_id")
