"""MOD-12 IT 지원 테이블(SQLAlchemy Core). action·head·ticket·멱등·감사·지원 범위의 단일 쓰기 소유자.

다른 모듈은 이 테이블을 직접 읽거나 쓰지 않는다(MOD-01은 CP-05 공개 작업으로 티켓 가시성만 묻는다).
"""

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Identity, Integer, MetaData, Table, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

metadata = MetaData()
TS = DateTime(timezone=True)
UUID = PG_UUID(as_uuid=True)

support_scopes = Table(
    "support_scopes",
    metadata,
    Column("user_id", Text, primary_key=True),
    Column("department_ids", JSONB, nullable=False),
)

ticket_actions = Table(
    "ticket_actions",
    metadata,
    Column("id", UUID, primary_key=True),
    Column("actor_id", Text, nullable=False),
    Column("conversation_id", UUID, nullable=False),
    Column("initiating_run_id", UUID, nullable=False),
    Column("origin", Text, nullable=False),  # agent_prepare / ui_revise
    Column("status", Text, nullable=False),  # draft/pending/superseded/confirmed/cancelled/expired
    Column("version", Integer, nullable=False),  # 불변 payload라 항상 1
    Column("payload", JSONB, nullable=False),
    Column("payload_hash", Text, nullable=False),
    Column("missing_fields", JSONB, nullable=False),
    Column("field_origins", JSONB, nullable=False),
    Column("expected_head_id", UUID),
    Column("expected_head_revision", Integer, nullable=False),
    Column("root_action_id", UUID, nullable=False),
    Column("prepared_from_action_id", UUID),
    Column("displaced_head_id", UUID),
    Column("superseded_by_action_id", UUID),
    Column("ticket_id", UUID),
    Column("expires_at", TS, nullable=False),
    Column("created_at", TS, nullable=False),
    Column("updated_at", TS, nullable=False),
)

ticket_action_heads = Table(
    "ticket_action_heads",
    metadata,
    Column("conversation_id", UUID, primary_key=True),
    Column("actor_id", Text, nullable=False),
    Column("head_action_id", UUID),
    Column("head_revision", Integer, nullable=False),
)

ticket_prepare_receipts = Table(
    "ticket_prepare_receipts",
    metadata,
    Column("run_id", UUID, primary_key=True),
    Column("ordinal", Integer, primary_key=True),
    Column("payload_hash", Text, nullable=False),
    Column("draft_id", UUID, nullable=False),
)

tickets = Table(
    "tickets",
    metadata,
    Column("id", UUID, primary_key=True),
    Column("action_id", UUID, nullable=False, unique=True),
    Column("requester_id", Text, nullable=False),
    Column("requester_department_ids", JSONB, nullable=False),
    Column("subject", Text, nullable=False),
    Column("description", Text, nullable=False),
    Column("request_type", Text, nullable=False),
    Column("category", Text, nullable=False),
    Column("target_service", Text, nullable=False),
    Column("occurred_at", TS),
    Column("impact_scope", Text),
    Column("urgent_work", Boolean, nullable=False),
    Column("urgency_reason", Text),
    Column("asset_identifier", Text),
    Column("reply_channel", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("created_at", TS, nullable=False),
)

idempotency_records = Table(
    "idempotency_records",
    metadata,
    Column("actor_id", Text, primary_key=True),
    Column("key", UUID, primary_key=True),
    Column("operation", Text, nullable=False),
    Column("target_action_id", UUID, nullable=False),
    Column("request_hash", Text, nullable=False),
    Column("result_action_id", UUID, nullable=False),
    Column("status_code", Integer, nullable=False),
    Column("created_at", TS, nullable=False),
)

ticket_audit = Table(
    "ticket_audit",
    metadata,
    Column("id", BigInteger, Identity(), primary_key=True),
    Column("action_id", UUID, nullable=False),
    Column("actor_id", Text, nullable=False),
    Column("event", Text, nullable=False),
    Column("details", JSONB, nullable=False),
    Column("created_at", TS, nullable=False),
)
