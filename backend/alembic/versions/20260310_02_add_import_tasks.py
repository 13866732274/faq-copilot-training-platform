"""add import_tasks table

Revision ID: 20260310_02
Revises: 20260310_01
Create Date: 2026-03-10 16:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260310_02"
down_revision = "20260310_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "import_tasks",
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("operator_id", sa.Integer(), nullable=False),
        sa.Column("scope", sa.Enum("common", "hospital", "department", name="import_task_scope"), nullable=False),
        sa.Column("hospital_id", sa.Integer(), nullable=True),
        sa.Column("department_id", sa.Integer(), nullable=True),
        sa.Column("total", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("success", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("duplicate", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("failed", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("updated", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.Enum("running", "completed", "partial_fail", name="import_task_status"), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["hospital_id"], ["hospitals.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["operator_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_import_tasks_operator", "import_tasks", ["operator_id"], unique=False)
    op.create_index(
        "idx_import_tasks_scope_hospital_department",
        "import_tasks",
        ["scope", "hospital_id", "department_id"],
        unique=False,
    )
    op.create_index("idx_import_tasks_status", "import_tasks", ["status"], unique=False)
    op.create_index("idx_import_tasks_created_at", "import_tasks", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_import_tasks_created_at", table_name="import_tasks")
    op.drop_index("idx_import_tasks_status", table_name="import_tasks")
    op.drop_index("idx_import_tasks_scope_hospital_department", table_name="import_tasks")
    op.drop_index("idx_import_tasks_operator", table_name="import_tasks")
    op.drop_table("import_tasks")
