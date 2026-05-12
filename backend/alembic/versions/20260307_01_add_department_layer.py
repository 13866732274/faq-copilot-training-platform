"""add hospital-department layer

Revision ID: 20260307_01
Revises: 20260306_07
Create Date: 2026-03-07 10:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260307_01"
down_revision = "20260306_07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("hospital_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["hospital_id"], ["hospitals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index("idx_dept_hospital", "departments", ["hospital_id"], unique=False)
    op.create_index("idx_dept_active", "departments", ["is_active"], unique=False)

    op.create_table(
        "user_departments",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("department_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "department_id"),
    )
    op.create_index("idx_user_departments_user", "user_departments", ["user_id"], unique=False)
    op.create_index("idx_user_departments_department", "user_departments", ["department_id"], unique=False)

    op.add_column("users", sa.Column("department_id", sa.Integer(), nullable=True))
    op.add_column("quizzes", sa.Column("department_id", sa.Integer(), nullable=True))
    op.add_column("practices", sa.Column("department_id", sa.Integer(), nullable=True))
    op.add_column("audit_logs", sa.Column("department_id", sa.Integer(), nullable=True))

    op.create_index("idx_user_department", "users", ["department_id"], unique=False)
    op.create_index("idx_quiz_department", "quizzes", ["department_id"], unique=False)
    op.create_index("idx_practice_department", "practices", ["department_id"], unique=False)
    op.create_index("idx_audit_logs_department", "audit_logs", ["department_id"], unique=False)

    op.create_foreign_key("fk_users_department_id", "users", "departments", ["department_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key(
        "fk_quizzes_department_id", "quizzes", "departments", ["department_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_practices_department_id", "practices", "departments", ["department_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_audit_logs_department_id", "audit_logs", "departments", ["department_id"], ["id"], ondelete="SET NULL"
    )

    op.execute(
        """
        ALTER TABLE quizzes
        MODIFY COLUMN scope ENUM('common','hospital','department') NOT NULL DEFAULT 'hospital'
        """
    )

    op.execute(
        """
        INSERT INTO departments (hospital_id, code, name, is_active, created_at, updated_at)
        SELECT h.id, CONCAT(h.code, '-default'), h.name, 1, NOW(), NOW()
        FROM hospitals h
        WHERE NOT EXISTS (
            SELECT 1 FROM departments d WHERE d.hospital_id = h.id
        )
        """
    )

    op.execute(
        """
        UPDATE users u
        JOIN (
            SELECT hospital_id, MIN(id) AS dept_id
            FROM departments
            GROUP BY hospital_id
        ) d ON d.hospital_id = u.hospital_id
        SET u.department_id = d.dept_id
        WHERE u.hospital_id IS NOT NULL AND u.department_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE quizzes q
        JOIN (
            SELECT hospital_id, MIN(id) AS dept_id
            FROM departments
            GROUP BY hospital_id
        ) d ON d.hospital_id = q.hospital_id
        SET q.department_id = d.dept_id
        WHERE q.scope = 'hospital' AND q.hospital_id IS NOT NULL AND q.department_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE practices p
        JOIN (
            SELECT hospital_id, MIN(id) AS dept_id
            FROM departments
            GROUP BY hospital_id
        ) d ON d.hospital_id = p.hospital_id
        SET p.department_id = d.dept_id
        WHERE p.hospital_id IS NOT NULL AND p.department_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE audit_logs a
        JOIN (
            SELECT hospital_id, MIN(id) AS dept_id
            FROM departments
            GROUP BY hospital_id
        ) d ON d.hospital_id = a.hospital_id
        SET a.department_id = d.dept_id
        WHERE a.hospital_id IS NOT NULL AND a.department_id IS NULL
        """
    )

    op.execute(
        """
        INSERT IGNORE INTO user_departments (user_id, department_id)
        SELECT uh.user_id, d.id
        FROM user_hospitals uh
        JOIN departments d ON d.hospital_id = uh.hospital_id
        """
    )
    op.execute(
        """
        INSERT IGNORE INTO user_departments (user_id, department_id)
        SELECT u.id, u.department_id
        FROM users u
        WHERE u.department_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("UPDATE quizzes SET scope='hospital' WHERE scope='department'")
    op.execute(
        """
        ALTER TABLE quizzes
        MODIFY COLUMN scope ENUM('common','hospital') NOT NULL DEFAULT 'hospital'
        """
    )

    op.drop_constraint("fk_audit_logs_department_id", "audit_logs", type_="foreignkey")
    op.drop_constraint("fk_practices_department_id", "practices", type_="foreignkey")
    op.drop_constraint("fk_quizzes_department_id", "quizzes", type_="foreignkey")
    op.drop_constraint("fk_users_department_id", "users", type_="foreignkey")

    op.drop_index("idx_audit_logs_department", table_name="audit_logs")
    op.drop_index("idx_practice_department", table_name="practices")
    op.drop_index("idx_quiz_department", table_name="quizzes")
    op.drop_index("idx_user_department", table_name="users")

    op.drop_column("audit_logs", "department_id")
    op.drop_column("practices", "department_id")
    op.drop_column("quizzes", "department_id")
    op.drop_column("users", "department_id")

    op.drop_index("idx_user_departments_department", table_name="user_departments")
    op.drop_index("idx_user_departments_user", table_name="user_departments")
    op.drop_table("user_departments")

    op.drop_index("idx_dept_active", table_name="departments")
    op.drop_index("idx_dept_hospital", table_name="departments")
    op.drop_table("departments")
