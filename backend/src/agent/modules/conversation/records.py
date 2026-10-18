"""CT-11 영속 observer와 CP-07 ReadTrainingEvidence(최소형).

- 도구 기록·교육 결과 receipt는 (run, ordinal[, attempt]) 멱등이다. 저장 실패는 RequiredRecordError다.
- 늦게 도착한 기록은 진단으로만 남는다. run 상태·메시지·활성 소유권을 바꾸지 않는다.
- 다음 턴에 넘길 교육 사본은 이 대화의 완료된 run이 남긴 실제 교육 receipt와 대조한 것만 쓴다.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from agent.modules.conversation.progress import RunProgress
from agent.modules.conversation.tables import (
    agent_runs,
    conversations,
    messages,
    tool_calls,
    tool_result_receipts,
)
from agent.shared.clock import Clock
from agent.shared.contracts import (
    ProgressStage,
    RequiredRecordError,
    ToolCallRecord,
    TrainingResultReceipt,
)


class DbExecutionObserver:
    def __init__(self, engine: AsyncEngine, progress: RunProgress | None = None) -> None:
        self._engine = engine
        self._progress = progress

    async def record_tool_call(self, record: ToolCallRecord) -> None:
        values = {
            "run_id": UUID(record.run_id),
            "ordinal": record.ordinal,
            "attempt": record.attempt,
            "name": record.name,
            "arguments_summary": record.arguments_summary,
            "ok": record.ok,
            "error_code": record.error_code,
            "error_stage": record.error_stage,
            "duration_ms": record.duration_ms,
            "resource_ids": list(record.resource_ids),
            "retrieval_trace": record.retrieval_trace,
        }
        await self._insert(insert(tool_calls).values(values).on_conflict_do_nothing())

    async def record_training_result(self, receipt: TrainingResultReceipt) -> None:
        values = {
            "run_id": UUID(receipt.run_id),
            "ordinal": receipt.ordinal,
            "training_starts": [list(pair) for pair in receipt.training_starts],
            "result_hash": receipt.result_hash,
        }
        await self._insert(insert(tool_result_receipts).values(values).on_conflict_do_nothing())

    async def record_stage(self, run_id: str, stage: ProgressStage) -> None:
        # 진행 단계는 저장하지 않는다. 같은 프로세스의 SSE 채널에만 넘긴다(채널이 없으면 버림).
        if self._progress is not None:
            self._progress.publish(run_id, stage)

    async def _insert(self, statement: Any) -> None:
        try:
            async with self._engine.begin() as conn:
                await conn.execute(statement)
        except (SQLAlchemyError, OSError) as exc:
            raise RequiredRecordError("실행 기록 저장 실패") from exc


class DbConversationEvidence:
    """CP-07 ConversationEvidenceReader의 MOD-01 구현(앱이 MOD-02·MOD-12에 주입, P-12 B)."""

    def __init__(self, engine: AsyncEngine, history_messages: int = 12) -> None:
        self._engine = engine
        self._history = history_messages

    async def read_user_messages(
        self, actor_id: str, conversation_id: str, run_id: str, message_ids: set[str]
    ) -> dict[str, str]:
        """ReadUserEvidence: 본인 대화의 그 run 문맥 user 원문만(수락한 질문 + 모델에 보낸 이력 창).

        assistant·다른 대화·창 밖 메시지·모르는 ID는 돌려주지 않는다(04-field-origins).
        """
        try:
            ids = {UUID(m) for m in message_ids}
            conversation, run = UUID(conversation_id), UUID(run_id)
        except ValueError:
            return {}
        async with self._engine.connect() as conn:
            owner = await conn.scalar(
                select(conversations.c.owner_user_id).where(conversations.c.id == conversation)
            )
            run_row = (
                await conn.execute(
                    select(agent_runs.c.user_message_id).where(
                        agent_runs.c.id == run, agent_runs.c.conversation_id == conversation
                    )
                )
            ).first()
            if owner != actor_id or run_row is None:
                return {}
            current_seq = await conn.scalar(
                select(messages.c.seq).where(messages.c.id == run_row.user_message_id)
            )
            window = (
                await conn.execute(
                    select(messages.c.id, messages.c.role, messages.c.content)
                    .where(messages.c.conversation_id == conversation, messages.c.seq <= current_seq)
                    .order_by(messages.c.seq.desc())
                    .limit(self._history + 1)
                )
            ).all()
        return {str(r.id): r.content for r in window if r.role == "user" and r.id in ids}

    async def verified_training_pairs(self, conversation_id: str) -> set[tuple[str, str]]:
        async with self._engine.connect() as conn:
            return await verified_training_pairs(conn, UUID(conversation_id))


async def verified_training_pairs(conn: AsyncConnection, conversation_id: UUID) -> set[tuple[str, str]]:
    """이 대화의 완료된 run이 실제로 받은 (교육 ID, 시작 시각) 쌍. 실패·만료 run의 결과는 쓰지 않는다."""
    rows = await conn.execute(
        select(tool_result_receipts.c.training_starts)
        .join(agent_runs, agent_runs.c.id == tool_result_receipts.c.run_id)
        .where(agent_runs.c.conversation_id == conversation_id, agent_runs.c.status == "completed")
    )
    return {(str(pair[0]), str(pair[1])) for (starts,) in rows for pair in starts}


def verified_cache(state: dict[str, Any], pairs: set[tuple[str, str]]) -> dict[str, dict[str, Any]]:
    """저장된 업무 상태의 교육 사본 중 receipt와 ID·시작 시각이 맞는 것만 남긴다."""
    cache = state.get("training_cache") or {}
    return {
        training_id: summary
        for training_id, summary in cache.items()
        if (training_id, str(summary.get("starts_at"))) in pairs
    }


class DbRunEligibility:
    """CP-06 RunEligibility의 MOD-01 구현(앱이 MOD-12에 주입). run 자격만 답한다."""

    def __init__(self, engine: AsyncEngine, clock: Clock) -> None:
        self._engine = engine
        self._clock = clock

    async def _run(self, conn: AsyncConnection, actor_id: str, conversation_id: str, run_id: str) -> Any:
        try:
            conversation, run = UUID(conversation_id), UUID(run_id)
        except ValueError:
            return None
        row = (
            await conn.execute(
                select(agent_runs, conversations.c.owner_user_id)
                .join(conversations, conversations.c.id == agent_runs.c.conversation_id)
                .where(agent_runs.c.id == run, agent_runs.c.conversation_id == conversation)
            )
        ).first()
        return row if row is not None and row.owner_user_id == actor_id else None

    async def check_prepare(self, actor_id: str, conversation_id: str, run_id: str) -> bool:
        """CheckPrepare: 아직 실행 중이고 deadline 전인 본인 run(실패·만료 run은 준비할 수 없다)."""
        async with self._engine.connect() as conn:
            row = await self._run(conn, actor_id, conversation_id, run_id)
        return row is not None and row.status == "running" and row.deadline_at > self._clock.now()

    async def adopted(self, actor_id: str, conversation_id: str, run_id: str, action_id: str) -> bool:
        """원본 run이 completed이고 그 답이 이 root draft를 채택했는가(MOD-01이 결과에 채택한 뒤에만 공개)."""
        async with self._engine.connect() as conn:
            row = await self._run(conn, actor_id, conversation_id, run_id)
            if row is None or row.status != "completed" or row.assistant_message_id is None:
                return False
            preview = await conn.scalar(
                select(messages.c.action_preview).where(messages.c.id == row.assistant_message_id)
            )
        return bool(preview) and preview.get("action_id") == action_id
