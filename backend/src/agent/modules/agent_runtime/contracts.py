"""MOD-02의 입력(CT-03 일부)·최종 출력 후보·결과(CT-10).

M3에서 문서 인용(citation_ids)을 붙였다. 티켓·action 필드는 M5에서 붙인다.
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
    # 답에 쓴 원문 근거의 citation_id. 이번 실행에서 모델 문맥에 실제로 들어간 근거만 허용한다(T-07).
    citation_ids: list[str] = Field(default_factory=list, max_length=30)
    # M5: 답에서 언급한 티켓 ID(이번 실행의 조회 결과에 있던 것만)와 사용자에게 확인을 요청할 draft action ID.
    ticket_ids: list[str] = Field(default_factory=list, max_length=20)
    action_id: str | None = None


# output_config에 넣을 JSON 스키마. 모든 필드를 required로 둬 생략과 null을 구분한다.
FINAL_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        # action_pending은 M5에서 연다. 서버가 이번 실행에서 실제로 준비한 draft인지 대조한다.
        "outcome": {"type": "string", "enum": [o.value for o in Outcome]},
        "training_ids": {"type": "array", "items": {"type": "string"}},
        "selected_training_id": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "citation_ids": {"type": "array", "items": {"type": "string"}},
        "ticket_ids": {"type": "array", "items": {"type": "string"}},
        "action_id": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    },
    "required": [
        "answer",
        "outcome",
        "training_ids",
        "selected_training_id",
        "citation_ids",
        "ticket_ids",
        "action_id",
    ],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class HistoryMessage:
    role: Literal["user", "assistant"]
    text: str
    # MOD-01 메시지 ID. 티켓 준비의 user_quote 출처(source_message_id)로 쓴다(04-field-origins).
    message_id: str | None = None


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
    # D-37: 첫 응답이 도구 없이 빈 답이라 서버가 다시 부른 횟수(0 또는 1). run 기록에 남긴다.
    empty_answer_retries: int = 0


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
    # answer를 누가 썼는가. server_fallback이면 모델이 되묻기 질문을 비워 서버의 일반 문구로 채웠다.
    # server_mapping이면 검색 결과(되묻기·미지원·예산 초과)에 맞춰 서버가 결론과 문구를 바꿨다.
    answer_source: Literal["model", "server_fallback", "server_mapping"] = "model"
    # 모델 문맥에 들어간 원문 문서 키(인용 여부와 무관). 이력·최종 응답 가림의 기준이다(CT-03).
    document_keys: tuple[str, ...] = ()
    # 모델 문맥에 들어간 티켓 ID(답에서 언급했는지와 무관). 권한이 바뀌면 이 답도 가린다(CP-05).
    ticket_dependency_ids: tuple[str, ...] = ()
    # 근거 예산 안에 실제로 들어간 passage와 예산 때문에 뺀 그룹(평가 Recall@budget용, 모델에 보이지 않음).
    evidence_trace: dict[str, Any] | None = None
