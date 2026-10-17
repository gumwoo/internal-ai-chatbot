"""MOD-04 fixture 적재 기록(manifest): 모드·anchor·clock(docs/12-first-milestone-spec.md).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "training_fixture_loads",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("fixture_mode", sa.Text(), nullable=False),
        sa.Column("anchor_date", sa.Date(), nullable=False),
        sa.Column("clock", sa.DateTime(timezone=True), nullable=False),
        sa.Column("shift_days", sa.Integer(), nullable=False),
        sa.Column("loaded", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("fixture_mode IN ('fixed_status', 'live_clock')", name="ck_fixture_loads_mode"),
    )


def downgrade() -> None:
    op.drop_table("training_fixture_loads")
