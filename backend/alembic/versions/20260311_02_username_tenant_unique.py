"""username: global unique -> (tenant_id, username) composite unique

Revision ID: 20260311_02
Revises: 20260311_01
"""

from alembic import op

revision = "20260311_02"
down_revision = "20260311_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("username", "users", type_="unique")
    op.create_unique_constraint("uq_user_tenant_username", "users", ["tenant_id", "username"])


def downgrade() -> None:
    op.drop_constraint("uq_user_tenant_username", "users", type_="unique")
    op.create_unique_constraint("username", "users", ["username"])
