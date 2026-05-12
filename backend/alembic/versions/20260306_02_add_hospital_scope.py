"""add hospital and quiz scope

Revision ID: 20260306_02
Revises: 20260306_01
Create Date: 2026-03-06 21:20:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260306_02"
down_revision = "20260306_01"
branch_labels = None
depends_on = None


quiz_scope_enum = sa.Enum("common", "hospital", name="quiz_scope")


def upgrade() -> None:
    op.create_table(
        "hospitals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("idx_hospital_code", "hospitals", ["code"], unique=False)
    op.create_index("idx_hospital_active", "hospitals", ["is_active"], unique=False)

    op.execute(
        """
        INSERT INTO hospitals (code, name, is_active)
        SELECT 'sh-hq-ent', '上海虹桥耳鼻咽喉科', 1
        WHERE NOT EXISTS (SELECT 1 FROM hospitals WHERE code = 'sh-hq-ent')
        """
    )

    quiz_scope_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "quizzes",
        sa.Column("scope", quiz_scope_enum, nullable=False, server_default="hospital"),
    )
    op.add_column("quizzes", sa.Column("hospital_id", sa.Integer(), nullable=True))
    op.create_index("idx_quiz_scope", "quizzes", ["scope"], unique=False)
    op.create_index("idx_quiz_hospital", "quizzes", ["hospital_id"], unique=False)
    op.create_foreign_key(
        "fk_quizzes_hospital_id_hospitals",
        "quizzes",
        "hospitals",
        ["hospital_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute(
        """
        UPDATE quizzes
        SET hospital_id = (SELECT id FROM hospitals WHERE code='sh-hq-ent' LIMIT 1)
        WHERE hospital_id IS NULL
        """
    )

    op.add_column("users", sa.Column("hospital_id", sa.Integer(), nullable=True))
    op.create_index("idx_user_hospital", "users", ["hospital_id"], unique=False)
    op.create_foreign_key(
        "fk_users_hospital_id_hospitals",
        "users",
        "hospitals",
        ["hospital_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute(
        """
        UPDATE users
        SET hospital_id = (SELECT id FROM hospitals WHERE code='sh-hq-ent' LIMIT 1)
        WHERE role IN ('admin','student') AND hospital_id IS NULL
        """
    )

    op.add_column("practices", sa.Column("hospital_id", sa.Integer(), nullable=True))
    op.create_index("idx_practice_hospital", "practices", ["hospital_id"], unique=False)
    op.create_foreign_key(
        "fk_practices_hospital_id_hospitals",
        "practices",
        "hospitals",
        ["hospital_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute(
        """
        UPDATE practices p
        LEFT JOIN users u ON u.id = p.user_id
        LEFT JOIN quizzes q ON q.id = p.quiz_id
        SET p.hospital_id = COALESCE(u.hospital_id, q.hospital_id)
        WHERE p.hospital_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_constraint("fk_practices_hospital_id_hospitals", "practices", type_="foreignkey")
    op.drop_index("idx_practice_hospital", table_name="practices")
    op.drop_column("practices", "hospital_id")

    op.drop_constraint("fk_users_hospital_id_hospitals", "users", type_="foreignkey")
    op.drop_index("idx_user_hospital", table_name="users")
    op.drop_column("users", "hospital_id")

    op.drop_constraint("fk_quizzes_hospital_id_hospitals", "quizzes", type_="foreignkey")
    op.drop_index("idx_quiz_hospital", table_name="quizzes")
    op.drop_index("idx_quiz_scope", table_name="quizzes")
    op.drop_column("quizzes", "hospital_id")
    op.drop_column("quizzes", "scope")
    quiz_scope_enum.drop(op.get_bind(), checkfirst=True)

    op.drop_index("idx_hospital_active", table_name="hospitals")
    op.drop_index("idx_hospital_code", table_name="hospitals")
    op.drop_table("hospitals")
