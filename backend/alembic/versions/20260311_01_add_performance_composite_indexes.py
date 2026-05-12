"""add performance composite indexes for tenant queries

Revision ID: 20260311_01
Revises: 20260310_06_add_tenant_session_version
Create Date: 2026-03-11 00:00:00
"""

from alembic import op

revision = "20260311_01"
down_revision = "20260310_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("idx_dept_tenant_active", "departments", ["tenant_id", "is_active"])
    op.create_index("idx_dept_hospital_tenant", "departments", ["hospital_id", "tenant_id"])
    op.create_index("idx_practice_user_tenant", "practices", ["user_id", "tenant_id"])
    op.create_index("idx_practice_tenant_status", "practices", ["tenant_id", "status"])
    op.create_index("idx_message_quiz_tenant", "messages", ["quiz_id", "tenant_id"])
    op.create_index("idx_quiz_version_quiz_tenant", "quiz_versions", ["quiz_id", "tenant_id"])
    op.create_index(
        "idx_quiz_tenant_scope_chat_hash",
        "quizzes",
        ["tenant_id", "scope", "chat_type", "content_hash"],
    )
    op.create_index("idx_audit_logs_tenant_created", "audit_logs", ["tenant_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_audit_logs_tenant_created", table_name="audit_logs")
    op.drop_index("idx_quiz_tenant_scope_chat_hash", table_name="quizzes")
    op.drop_index("idx_quiz_version_quiz_tenant", table_name="quiz_versions")
    op.drop_index("idx_message_quiz_tenant", table_name="messages")
    op.drop_index("idx_practice_tenant_status", table_name="practices")
    op.drop_index("idx_practice_user_tenant", table_name="practices")
    op.drop_index("idx_dept_hospital_tenant", table_name="departments")
    op.drop_index("idx_dept_tenant_active", table_name="departments")
