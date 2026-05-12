"""add system_settings table

Revision ID: 20260310_01
Revises: 20260309_05
Create Date: 2026-03-10 14:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260310_01"
down_revision = "20260309_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "system_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("site_name", sa.String(length=120), nullable=False),
        sa.Column("site_subtitle", sa.String(length=120), nullable=False),
        sa.Column("logo_url", sa.String(length=500), nullable=True),
        sa.Column("brand_accent", sa.String(length=20), nullable=False),
        sa.Column("enable_ai_scoring", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("enable_export_center", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("enable_audit_enhanced", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_system_settings_updated_at", "system_settings", ["updated_at"], unique=False)

    op.execute(
        sa.text(
            """
            INSERT INTO system_settings
            (site_name, site_subtitle, logo_url, brand_accent, enable_ai_scoring, enable_export_center, enable_audit_enhanced)
            VALUES
            (:site_name, :site_subtitle, :logo_url, :brand_accent, :enable_ai_scoring, :enable_export_center, :enable_audit_enhanced)
            """
        ).bindparams(
            site_name="咨询话术模拟训练系统",
            site_subtitle="运营管理中台",
            logo_url=None,
            brand_accent="#07c160",
            enable_ai_scoring=False,
            enable_export_center=True,
            enable_audit_enhanced=True,
        )
    )


def downgrade() -> None:
    op.drop_index("idx_system_settings_updated_at", table_name="system_settings")
    op.drop_table("system_settings")
