"""add faq_clusters, faq_questions, faq_answers, faq_tasks tables

Revision ID: 20260313_01
Revises: 20260311_02
"""

import sqlalchemy as sa
from alembic import op

revision = "20260313_01"
down_revision = "20260311_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "faq_clusters",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("category", sa.String(200), nullable=True),
        sa.Column("tags", sa.String(500), nullable=True),
        sa.Column("representative_question", sa.Text, nullable=True),
        sa.Column("best_answer", sa.Text, nullable=True),
        sa.Column("embedding_json", sa.Text, nullable=True),
        sa.Column("question_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("answer_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("1")),
        sa.Column("is_locked", sa.Boolean, nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_faq_cluster_tenant", "faq_clusters", ["tenant_id"])
    op.create_index("idx_faq_cluster_category", "faq_clusters", ["category"])
    op.create_index("idx_faq_cluster_active", "faq_clusters", ["is_active"])

    op.create_table(
        "faq_questions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True),
        sa.Column("cluster_id", sa.Integer, sa.ForeignKey("faq_clusters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("quiz_id", sa.Integer, sa.ForeignKey("quizzes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("message_id", sa.Integer, sa.ForeignKey("messages.id", ondelete="SET NULL"), nullable=True),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("embedding_json", sa.Text, nullable=True),
        sa.Column("similarity_score", sa.Float, nullable=False, server_default="0"),
        sa.Column("is_representative", sa.Boolean, nullable=False, server_default=sa.text("0")),
        sa.Column("source_context", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_faq_question_cluster", "faq_questions", ["cluster_id"])
    op.create_index("idx_faq_question_quiz", "faq_questions", ["quiz_id"])
    op.create_index("idx_faq_question_tenant", "faq_questions", ["tenant_id"])

    op.create_table(
        "faq_answers",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True),
        sa.Column("cluster_id", sa.Integer, sa.ForeignKey("faq_clusters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("quiz_id", sa.Integer, sa.ForeignKey("quizzes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("message_id", sa.Integer, sa.ForeignKey("messages.id", ondelete="SET NULL"), nullable=True),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("quality_score", sa.Float, nullable=False, server_default="0"),
        sa.Column("is_best", sa.Boolean, nullable=False, server_default=sa.text("0")),
        sa.Column("upvotes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("source_context", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_faq_answer_cluster", "faq_answers", ["cluster_id"])
    op.create_index("idx_faq_answer_quiz", "faq_answers", ["quiz_id"])
    op.create_index("idx_faq_answer_tenant", "faq_answers", ["tenant_id"])
    op.create_index("idx_faq_answer_quality", "faq_answers", ["quality_score"])

    op.create_table(
        "faq_tasks",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True),
        sa.Column("operator_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.Enum(
            "pending", "extracting", "embedding", "clustering", "refining", "completed", "failed",
            name="faq_task_status",
        ), nullable=False, server_default="pending"),
        sa.Column("total_quizzes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_messages", sa.Integer, nullable=False, server_default="0"),
        sa.Column("extracted_pairs", sa.Integer, nullable=False, server_default="0"),
        sa.Column("clusters_created", sa.Integer, nullable=False, server_default="0"),
        sa.Column("clusters_updated", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("config_json", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime, nullable=True),
        sa.Column("finished_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_faq_task_tenant", "faq_tasks", ["tenant_id"])
    op.create_index("idx_faq_task_status", "faq_tasks", ["status"])


def downgrade() -> None:
    op.drop_table("faq_answers")
    op.drop_table("faq_questions")
    op.drop_table("faq_tasks")
    op.drop_table("faq_clusters")
    op.execute("DROP TYPE IF EXISTS faq_task_status")
