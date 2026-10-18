"""MOD-12 IT 지원 티켓 테이블(docs/14-ticket-workflow.md)과 회신 수단·메시지 action 컬럼(M5).

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB()
UUID = postgresql.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    # MOD-09 프로필의 사내 회신 수단(서버 값). 없으면 티켓 준비 오류다.
    op.add_column("users", sa.Column("reply_channel", sa.Text()))
    # MOD-01: 채택한 root draft 미리보기와 티켓 참조. 이력·재전송에서 현재 권한으로 다시 판정한다.
    op.add_column("messages", sa.Column("action_preview", JSONB))
    op.add_column(
        "messages", sa.Column("ticket_refs", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb"))
    )
    op.create_table(
        "support_scopes",
        sa.Column("user_id", sa.Text(), primary_key=True),
        sa.Column("department_ids", JSONB, nullable=False),
    )
    op.create_table(
        "ticket_actions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("actor_id", sa.Text(), nullable=False),
        sa.Column("conversation_id", UUID, nullable=False),
        sa.Column("initiating_run_id", UUID, nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),  # agent_prepare / ui_revise
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("payload_hash", sa.Text(), nullable=False),
        sa.Column("missing_fields", JSONB, nullable=False),
        sa.Column("field_origins", JSONB, nullable=False),
        sa.Column("expected_head_id", UUID),
        sa.Column("expected_head_revision", sa.Integer(), nullable=False),
        sa.Column("root_action_id", UUID, nullable=False),
        sa.Column("prepared_from_action_id", UUID),
        sa.Column("displaced_head_id", UUID),
        sa.Column("superseded_by_action_id", UUID),
        sa.Column("ticket_id", UUID),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )
    op.create_index("ix_ticket_actions_conversation", "ticket_actions", ["conversation_id"])
    op.create_table(
        "ticket_action_heads",
        sa.Column("conversation_id", UUID, primary_key=True),
        sa.Column("actor_id", sa.Text(), nullable=False),
        sa.Column("head_action_id", UUID),
        sa.Column("head_revision", sa.Integer(), nullable=False),
    )
    op.create_table(
        "ticket_prepare_receipts",
        sa.Column("run_id", UUID, primary_key=True),
        sa.Column("ordinal", sa.Integer(), primary_key=True),
        sa.Column("payload_hash", sa.Text(), nullable=False),
        sa.Column("draft_id", UUID, nullable=False),
    )
    op.create_table(
        "tickets",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("action_id", UUID, nullable=False, unique=True),
        sa.Column("requester_id", sa.Text(), nullable=False),
        sa.Column("requester_department_ids", JSONB, nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("request_type", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("target_service", sa.Text(), nullable=False),
        sa.Column("occurred_at", TS),
        sa.Column("impact_scope", sa.Text()),
        sa.Column("urgent_work", sa.Boolean(), nullable=False),
        sa.Column("urgency_reason", sa.Text()),
        sa.Column("asset_identifier", sa.Text()),
        sa.Column("reply_channel", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_index("ix_tickets_requester", "tickets", ["requester_id", "created_at"])
    op.create_table(
        "idempotency_records",
        sa.Column("actor_id", sa.Text(), primary_key=True),
        sa.Column("key", UUID, primary_key=True),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("target_action_id", UUID, nullable=False),
        sa.Column("request_hash", sa.Text(), nullable=False),
        sa.Column("result_action_id", UUID, nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_table(
        "ticket_audit",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("action_id", UUID, nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=False),
        sa.Column("event", sa.Text(), nullable=False),
        sa.Column("details", JSONB, nullable=False),
        sa.Column("created_at", TS, nullable=False),
    )


def downgrade() -> None:
    for table in (
        "ticket_audit",
        "idempotency_records",
        "tickets",
        "ticket_prepare_receipts",
        "ticket_action_heads",
        "ticket_actions",
        "support_scopes",
    ):
        op.drop_table(table)
    op.drop_column("messages", "ticket_refs")
    op.drop_column("messages", "action_preview")
    op.drop_column("users", "reply_channel")
