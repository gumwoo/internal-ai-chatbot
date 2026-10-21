"""답변 피드백(D-77). 사용자가 자기 대화의 답에 남긴 평가와 사유·의견을 답·사용자마다 하나 둔다.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "message_feedback",
        sa.Column("message_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("messages.id"), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("rating", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("comment", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("message_id", "user_id"),
        sa.CheckConstraint("rating IN ('helpful', 'not_helpful')", name="ck_message_feedback_rating"),
        sa.CheckConstraint(
            "reason IS NULL OR reason IN ('wrong_source', 'missing_source', 'wrong_answer', 'other')",
            name="ck_message_feedback_reason",
        ),
    )


def downgrade() -> None:
    op.drop_table("message_feedback")
