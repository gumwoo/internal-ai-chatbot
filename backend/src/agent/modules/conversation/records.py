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
from agent.modules.conversation.tables import agent_runs, tool_calls, tool_result_receipts
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
