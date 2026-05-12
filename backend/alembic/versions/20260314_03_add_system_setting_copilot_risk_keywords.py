"""add copilot_risk_keywords and faq_similarity_threshold to system_settings

Revision ID: 20260314_03
Revises: 20260314_02
"""

import sqlalchemy as sa
from alembic import op

revision = "20260314_03"
down_revision = "20260314_02"
branch_labels = None
depends_on = None

DEFAULT_RISK_KEYWORDS = "费用,价格,多少钱,收费,医保,报销,疗程,疗效,副作用,禁忌,复发,手术,住院,风险,药物,孕妇,儿童,老人"


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column("copilot_risk_keywords", sa.Text(), nullable=True, server_default=DEFAULT_RISK_KEYWORDS),
    )
    op.add_column(
        "system_settings",
        sa.Column("faq_similarity_threshold", sa.Float(), nullable=False, server_default="0.35"),
    )


def downgrade() -> None:
    op.drop_column("system_settings", "faq_similarity_threshold")
    op.drop_column("system_settings", "copilot_risk_keywords")
