"""remove legacy hongqiao hospital row

Revision ID: 20260306_05
Revises: 20260306_04
Create Date: 2026-03-06 14:40:00
"""

from __future__ import annotations

from alembic import op


revision = "20260306_05"
down_revision = "20260306_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM hospitals
        WHERE name='虹桥医院'
          AND id NOT IN (
            SELECT keep_id FROM (
              SELECT id AS keep_id FROM hospitals WHERE name='上海虹桥耳鼻咽喉科'
            ) t
          )
        """
    )


def downgrade() -> None:
    # 历史旧院区已弃用，降级不恢复该行，避免再次引入混淆
    pass
