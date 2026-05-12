"""create users quizzes messages

Revision ID: 20260305_01
Revises:
Create Date: 2026-03-05 14:50:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260305_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(length=50), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("real_name", sa.String(length=50), nullable=False),
        sa.Column(
            "role",
            sa.Enum("super_admin", "admin", "student", name="user_role"),
            nullable=False,
            server_default="student",
        ),
        sa.Column("avatar", sa.String(length=500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )
    op.create_index("idx_role", "users", ["role"], unique=False)
    op.create_index("idx_active", "users", ["is_active"], unique=False)

    op.create_table(
        "quizzes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=50), nullable=True),
        sa.Column("difficulty", sa.Integer(), nullable=True, server_default="1"),
        sa.Column("tags", sa.String(length=500), nullable=True),
        sa.Column("patient_name", sa.String(length=100), nullable=True),
        sa.Column("counselor_name", sa.String(length=100), nullable=True),
        sa.Column("message_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("source_file", sa.String(length=500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_category", "quizzes", ["category"], unique=False)
    op.create_index("idx_active_deleted", "quizzes", ["is_active", "is_deleted"], unique=False)

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("quiz_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column(
            "role",
            sa.Enum("patient", "counselor", name="message_role"),
            nullable=False,
        ),
        sa.Column(
            "content_type",
            sa.Enum("text", "image", "audio", "system", name="message_content_type"),
            nullable=False,
            server_default="text",
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sender_name", sa.String(length=100), nullable=True),
        sa.Column("original_time", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["quiz_id"], ["quizzes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_quiz_sequence", "messages", ["quiz_id", "sequence"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_quiz_sequence", table_name="messages")
    op.drop_table("messages")
    op.drop_index("idx_active_deleted", table_name="quizzes")
    op.drop_index("idx_category", table_name="quizzes")
    op.drop_table("quizzes")
    op.drop_index("idx_active", table_name="users")
    op.drop_index("idx_role", table_name="users")
    op.drop_table("users")

    sa.Enum(name="message_content_type").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="message_role").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="user_role").drop(op.get_bind(), checkfirst=True)
