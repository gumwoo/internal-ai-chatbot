"""MOD-01 대화·실행 테이블(docs/03-data-model.md, contracts/01-run-lifecycle.md).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB()
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("owner_user_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text()),
        sa.Column("retrieval_strategy", sa.Text(), nullable=False),
        sa.Column("active_run_id", UUID),
        sa.Column("business_state", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )
    op.create_index("ix_conversations_owner", "conversations", ["owner_user_id", "created_at"])

    op.create_table(
        "messages",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("seq", sa.BigInteger(), sa.Identity(), nullable=False, unique=True),
        sa.Column("conversation_id", UUID, sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("run_id", UUID),
        sa.Column("outcome", sa.Text()),
        sa.Column("training_refs", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("dependency_ids", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("visibility", sa.Text(), nullable=False, server_default="visible"),
        sa.Column("created_at", TS, nullable=False),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_messages_role"),
        sa.CheckConstraint("visibility IN ('visible', 'redacted')", name="ck_messages_visibility"),
    )
    op.create_index("ix_messages_conversation_seq", "messages", ["conversation_id", "seq"])

    op.create_table(
        "message_receipts",
        sa.Column("actor_id", sa.Text(), primary_key=True),
        sa.Column("conversation_id", UUID, sa.ForeignKey("conversations.id"), primary_key=True),
        sa.Column("idempotency_key", UUID, primary_key=True),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("user_message_id", UUID, nullable=False),
        sa.Column("run_id", UUID, nullable=False),
        sa.Column("created_at", TS, nullable=False),
    )

    op.create_table(
        "agent_runs",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("conversation_id", UUID, sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("user_message_id", UUID, nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("accepted_at", TS, nullable=False),
        sa.Column("deadline_at", TS, nullable=False),
        sa.Column("finished_at", TS),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("retrieval_context", JSONB, nullable=False),
        sa.Column("outcome", sa.Text()),
        sa.Column("error_code", sa.Text()),
        sa.Column("error_retryable", sa.Boolean()),
        sa.Column("usage", JSONB),
        sa.Column("model_ids", JSONB),
        sa.Column("assistant_message_id", UUID),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'expired')", name="ck_agent_runs_status"
        ),
        sa.CheckConstraint("deadline_at > accepted_at", name="ck_agent_runs_deadline"),
    )
    # 한 대화에 running run은 하나. 수락 트랜잭션의 행 잠금이 1차 방어이고, 이 인덱스가 마지막 방어다.
    op.create_index(
        "ux_agent_runs_one_running",
        "agent_runs",
        ["conversation_id"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )
    op.create_index(
        "ix_agent_runs_running_deadline",
        "agent_runs",
        ["deadline_at"],
        postgresql_where=sa.text("status = 'running'"),
    )

    op.create_table(
        "tool_calls",
        sa.Column("run_id", UUID, sa.ForeignKey("agent_runs.id"), primary_key=True),
        sa.Column("ordinal", sa.Integer(), primary_key=True),
        sa.Column("attempt", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("arguments_summary", JSONB, nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("error_code", sa.Text()),
        sa.Column("error_stage", sa.Text()),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("resource_ids", JSONB, nullable=False),
        sa.Column("recorded_at", TS, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "tool_result_receipts",
        sa.Column("run_id", UUID, sa.ForeignKey("agent_runs.id"), primary_key=True),
        sa.Column("ordinal", sa.Integer(), primary_key=True),
        sa.Column("training_starts", JSONB, nullable=False),
        sa.Column("result_hash", sa.Text(), nullable=False),
        sa.Column("recorded_at", TS, nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("tool_result_receipts")
    op.drop_table("tool_calls")
    op.drop_index("ix_agent_runs_running_deadline", table_name="agent_runs")
    op.drop_index("ux_agent_runs_one_running", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_table("message_receipts")
    op.drop_index("ix_messages_conversation_seq", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_conversations_owner", table_name="conversations")
    op.drop_table("conversations")
