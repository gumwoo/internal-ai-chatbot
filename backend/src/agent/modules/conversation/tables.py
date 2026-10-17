"""MOD-01 테이블(SQLAlchemy Core). 다른 모듈은 이 테이블을 직접 읽거나 쓰지 않는다."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    MetaData,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

metadata = MetaData()

conversations = Table(
    "conversations",
    metadata,
    Column("id", PG_UUID(as_uuid=True), primary_key=True),
    Column("owner_user_id", Text, nullable=False),
    Column("title", Text),
    # 대화 생성 시 서버가 고정하는 검색 전략. 직원 HTTP로 바꿀 수 없다. M1~M2는 disabled.
    Column("retrieval_strategy", Text, nullable=False),
    Column("active_run_id", PG_UUID(as_uuid=True)),
    # CT-03 schema v2 업무 상태(검증된 교육 사본·마지막 목록·선택). 완료 commit에서만 바뀐다.
    Column("business_state", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

messages = Table(
    "messages",
    metadata,
    Column("id", PG_UUID(as_uuid=True), primary_key=True),
    Column("seq", BigInteger, Identity(), nullable=False, unique=True),
    Column("conversation_id", PG_UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False),
    Column("role", Text, nullable=False),
    Column("content", Text, nullable=False),
    Column("run_id", PG_UUID(as_uuid=True)),
    Column("outcome", Text),
    # 표시용 참조(교육 id/code/title)와 접근 재검사용 의존 자원 ID.
    Column("training_refs", JSONB, nullable=False),
    Column("dependency_ids", JSONB, nullable=False),
    # 서버가 근거 원장으로 만든 인용 DTO(04-api-spec). 가린 답변에서는 내보내지 않는다.
    Column("citations", JSONB, nullable=False, server_default="[]"),
    Column("visibility", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

message_receipts = Table(
    "message_receipts",
    metadata,
    Column("actor_id", Text, primary_key=True),
    Column("conversation_id", PG_UUID(as_uuid=True), ForeignKey("conversations.id"), primary_key=True),
    Column("idempotency_key", PG_UUID(as_uuid=True), primary_key=True),
    Column("content_hash", Text, nullable=False),
    Column("user_message_id", PG_UUID(as_uuid=True), nullable=False),
    Column("run_id", PG_UUID(as_uuid=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

agent_runs = Table(
    "agent_runs",
    metadata,
    Column("id", PG_UUID(as_uuid=True), primary_key=True),
    Column("conversation_id", PG_UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False),
    Column("request_id", Text, nullable=False),
    Column("user_message_id", PG_UUID(as_uuid=True), nullable=False),
    Column("status", Text, nullable=False),
    Column("accepted_at", DateTime(timezone=True), nullable=False),
    Column("deadline_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True)),
    Column("prompt_version", Text, nullable=False),
    Column("model", Text, nullable=False),
    Column("retrieval_context", JSONB, nullable=False),
    Column("outcome", Text),
    Column("error_code", Text),
    Column("error_retryable", Boolean),
    Column("usage", JSONB),
    Column("model_ids", JSONB),
    Column("assistant_message_id", PG_UUID(as_uuid=True)),
)

tool_calls = Table(
    "tool_calls",
    metadata,
    Column("run_id", PG_UUID(as_uuid=True), ForeignKey("agent_runs.id"), primary_key=True),
    Column("ordinal", Integer, primary_key=True),
    Column("attempt", Integer, primary_key=True),
    Column("name", Text, nullable=False),
    Column("arguments_summary", JSONB, nullable=False),
    Column("ok", Boolean, nullable=False),
    Column("error_code", Text),
    Column("error_stage", Text),
    Column("duration_ms", Integer, nullable=False),
    Column("resource_ids", JSONB, nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

tool_result_receipts = Table(
    "tool_result_receipts",
    metadata,
    Column("run_id", PG_UUID(as_uuid=True), ForeignKey("agent_runs.id"), primary_key=True),
    Column("ordinal", Integer, primary_key=True),
    # [[training_id, starts_at ISO8601], ...] — MOD-04 실제 결과. CP-07 ReadTrainingEvidence가 대조한다.
    Column("training_starts", JSONB, nullable=False),
    Column("result_hash", Text, nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
