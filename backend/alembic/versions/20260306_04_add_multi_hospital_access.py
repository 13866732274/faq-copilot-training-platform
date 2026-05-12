"""add multi hospital access

Revision ID: 20260306_04
Revises: 20260306_03
Create Date: 2026-03-06 23:25:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260306_04"
down_revision = "20260306_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_all_hospitals", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("idx_user_all_hospitals", "users", ["is_all_hospitals"], unique=False)

    op.create_table(
        "user_hospitals",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("hospital_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["hospital_id"], ["hospitals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "hospital_id"),
    )
    op.create_index("idx_user_hospitals_user", "user_hospitals", ["user_id"], unique=False)
    op.create_index("idx_user_hospitals_hospital", "user_hospitals", ["hospital_id"], unique=False)

    # 给现有非超管管理员初始化“负责医院”关系（按当前 hospital_id）
    op.execute(
        """
        INSERT IGNORE INTO user_hospitals (user_id, hospital_id)
        SELECT id, hospital_id
        FROM users
        WHERE role='admin' AND hospital_id IS NOT NULL
        """
    )

    # 超级管理员默认全院可见
    op.execute(
        """
        UPDATE users
        SET is_all_hospitals=1
        WHERE role='super_admin'
        """
    )

    # 历史遗留医院数据清理由后续迁移统一处理


def downgrade() -> None:
    op.drop_index("idx_user_hospitals_hospital", table_name="user_hospitals")
    op.drop_index("idx_user_hospitals_user", table_name="user_hospitals")
    op.drop_table("user_hospitals")

    op.drop_index("idx_user_all_hospitals", table_name="users")
    op.drop_column("users", "is_all_hospitals")
