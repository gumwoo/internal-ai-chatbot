"""MOD-02의 입력(CT-03 일부)·최종 출력 후보·결과(CT-10).

M1은 교육 범위만 다룬다. 문서 인용·티켓·action 필드는 해당 단계에서 붙인다.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent.shared.contracts import ToolCallRecord
from agent.shared.errors import AppError


class Outcome(StrEnum):
    ANSWERED = "answered"
    NEEDS_CLARIFICATION = "needs_clarification"
    NO_RESULTS = "no_results"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    ACTION_PENDING = "action_pending"


class FinalCandidate(BaseModel):
    """모델이 내는 최종 구조. 서버가 실제 결과 원장과 대조한 뒤에만 사용자 결과가 된다."""

    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1, max_length=4000)
    outcome: Outcome
    # 답에서 언급한 교육의 ID. 이번 실행의 도구 결과 또는 검증된 대화 사본에 있던 ID만 허용한다.
    training_ids: list[str] = Field(max_length=20)
    # 후속 질문의 "그 교육"이 가리킬 단일 교육. 하나로 정해지지 않으면 null.
    selected_training_id: str | None


# output_config에 넣을 JSON 스키마. 모든 필드를 required로 둬 생략과 null을 구분한다.
FINAL_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "outcome": {"type": "string", "enum": [o.value for o in Outcome]},
        "training_ids": {"type": "array", "items": {"type": "string"}},
        "selected_training_id": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    },
    "required": ["answer", "outcome", "training_ids", "selected_training_id"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class HistoryMessage:
    role: Literal["user", "assistant"]
    text: str


@dataclass(frozen=True)
class ConversationSnapshot:
    """CT-03 중 M1이 쓰는 부분. MOD-01이 소유권·가시성 검사를 마친 사본만 넘긴다(M2)."""

    messages: tuple[HistoryMessage, ...] = ()
    # 같은 대화에서 이미 검증된 교육 사본(id → TrainingSummary JSON). 최대 20건.
    training_cache: dict[str, dict[str, Any]] = field(default_factory=dict)
    last_training_ids: tuple[str, ...] = ()
    selected_training_id: str | None = None
    schema_version: int = 2


@dataclass(frozen=True)
class RunUsage:
    """모든 모델 시도의 합. 하나라도 사용량을 모르면 complete=False(실패 호출도 0원으로 단정하지 않는다)."""

    input_tokens: int
    output_tokens: int
    complete: bool
    model_attempts: int


@dataclass(frozen=True)
class ExecutionResult:
    """CT-10. status는 MOD-02 결과 후보이며 영속 run 상태(MOD-01)와 다르다."""

    status: Literal["completed", "failed"]
    outcome: Outcome | None
    answer: str | None
    training_refs: tuple[dict[str, Any], ...]
    context_candidate: dict[str, Any] | None
    usage: RunUsage
    tool_summary: tuple[ToolCallRecord, ...]
    error: AppError | None
    model_ids: tuple[str, ...] = ()
    ticket_refs: tuple[dict[str, Any], ...] = ()
    citations: tuple[dict[str, Any], ...] = ()
    action_preview: dict[str, Any] | None = None
