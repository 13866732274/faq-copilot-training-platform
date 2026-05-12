"""add practices and practice_replies

Revision ID: 20260305_02
Revises: 20260305_01
Create Date: 2026-03-05 16:25:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260305_02"
down_revision = "20260305_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "practices",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("quiz_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("in_progress", "completed", name="practice_status"),
            nullable=False,
            server_default="in_progress",
        ),
        sa.Column("current_step", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["quiz_id"], ["quizzes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_practice_user", "practices", ["user_id"], unique=False)
    op.create_index("idx_practice_quiz", "practices", ["quiz_id"], unique=False)
    op.create_index("idx_practice_status", "practices", ["status"], unique=False)

    op.create_table(
        "practice_replies",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("practice_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("reply_content", sa.Text(), nullable=False),
        sa.Column("reply_time", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["practice_id"], ["practices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("practice_id", "message_id", name="uq_practice_message"),
    )
    op.create_index("idx_reply_practice", "practice_replies", ["practice_id"], unique=False)
    op.create_index("idx_reply_message", "practice_replies", ["message_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_reply_message", table_name="practice_replies")
    op.drop_index("idx_reply_practice", table_name="practice_replies")
    op.drop_table("practice_replies")
    op.drop_index("idx_practice_status", table_name="practices")
    op.drop_index("idx_practice_quiz", table_name="practices")
    op.drop_index("idx_practice_user", table_name="practices")
    op.drop_table("practices")
    sa.Enum(name="practice_status").drop(op.get_bind(), checkfirst=True)
