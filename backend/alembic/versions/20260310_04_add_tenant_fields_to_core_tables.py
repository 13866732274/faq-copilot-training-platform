"""add tenant_id to core business tables

Revision ID: 20260310_04
Revises: 20260310_03
Create Date: 2026-03-10 20:55:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260310_04"
down_revision = "20260310_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    core_tables = [
        ("hospitals", "idx_hospital_tenant"),
        ("departments", "idx_dept_tenant"),
        ("quizzes", "idx_quiz_tenant"),
        ("messages", "idx_message_tenant"),
        ("quiz_versions", "idx_quiz_version_tenant"),
        ("practices", "idx_practice_tenant"),
        ("practice_comments", "idx_comment_tenant"),
        ("practice_replies", "idx_reply_tenant"),
    ]
    for table_name, index_name in core_tables:
        op.add_column(table_name, sa.Column("tenant_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            f"fk_{table_name}_tenant_id",
            table_name,
            "tenants",
            ["tenant_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index(index_name, table_name, ["tenant_id"], unique=False)

    # hospitals: 使用默认租户兜底
    op.execute(sa.text("UPDATE hospitals SET tenant_id = 1 WHERE tenant_id IS NULL"))
    # departments: 继承医院租户
    op.execute(
        sa.text(
            """
            UPDATE departments d
            JOIN hospitals h ON h.id = d.hospital_id
            SET d.tenant_id = h.tenant_id
            WHERE d.tenant_id IS NULL
            """
        )
    )
    op.execute(sa.text("UPDATE departments SET tenant_id = 1 WHERE tenant_id IS NULL"))
    # quizzes: 优先继承创建人租户，再回退医院/科室
    op.execute(
        sa.text(
            """
            UPDATE quizzes q
            LEFT JOIN users u ON u.id = q.created_by
            LEFT JOIN hospitals h ON h.id = q.hospital_id
            LEFT JOIN departments d ON d.id = q.department_id
            SET q.tenant_id = COALESCE(u.tenant_id, h.tenant_id, d.tenant_id, 1)
            WHERE q.tenant_id IS NULL
            """
        )
    )
    # messages / versions: 继承 quiz
    op.execute(
        sa.text(
            """
            UPDATE messages m
            JOIN quizzes q ON q.id = m.quiz_id
            SET m.tenant_id = q.tenant_id
            WHERE m.tenant_id IS NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE quiz_versions v
            JOIN quizzes q ON q.id = v.quiz_id
            SET v.tenant_id = q.tenant_id
            WHERE v.tenant_id IS NULL
            """
        )
    )
    # practices: 优先 user，再回退 quiz/hospital/department
    op.execute(
        sa.text(
            """
            UPDATE practices p
            LEFT JOIN users u ON u.id = p.user_id
            LEFT JOIN quizzes q ON q.id = p.quiz_id
            LEFT JOIN hospitals h ON h.id = p.hospital_id
            LEFT JOIN departments d ON d.id = p.department_id
            SET p.tenant_id = COALESCE(u.tenant_id, q.tenant_id, h.tenant_id, d.tenant_id, 1)
            WHERE p.tenant_id IS NULL
            """
        )
    )
    # comment/reply: 继承 practice
    op.execute(
        sa.text(
            """
            UPDATE practice_comments c
            JOIN practices p ON p.id = c.practice_id
            SET c.tenant_id = p.tenant_id
            WHERE c.tenant_id IS NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE practice_replies r
            JOIN practices p ON p.id = r.practice_id
            SET r.tenant_id = p.tenant_id
            WHERE r.tenant_id IS NULL
            """
        )
    )


def downgrade() -> None:
    core_tables = [
        ("practice_replies", "idx_reply_tenant"),
        ("practice_comments", "idx_comment_tenant"),
        ("practices", "idx_practice_tenant"),
        ("quiz_versions", "idx_quiz_version_tenant"),
        ("messages", "idx_message_tenant"),
        ("quizzes", "idx_quiz_tenant"),
        ("departments", "idx_dept_tenant"),
        ("hospitals", "idx_hospital_tenant"),
    ]
    for table_name, index_name in core_tables:
        op.drop_index(index_name, table_name=table_name)
        op.drop_constraint(f"fk_{table_name}_tenant_id", table_name, type_="foreignkey")
        op.drop_column(table_name, "tenant_id")
