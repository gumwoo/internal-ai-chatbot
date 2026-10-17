"""여러 모듈이 주고받는 공급자 중립 값. MOD-01·02·03·07이 같은 타입을 쓴다.

CT-02 ExecutionContext, CT-06 ToolCallProposal/ToolResult/ToolExecutionInput, CT-11 ExecutionObserver,
그리고 모델에 보여 줄 도구 명세(ToolSpec). 특정 모듈 구현에 의존하지 않는다.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from agent.shared.actor import ActorContext
from agent.shared.errors import AppError


@dataclass(frozen=True)
class ToolCallProposal:
    """모델의 도구 제안. call_ordinal은 서버(MOD-02)가 붙이고 모델 값은 쓰지 않는다."""

    name: str
    arguments: dict[str, Any]
    provider_call_id: str
    # prepare 계열의 비신뢰 출처 제안. 업무 arguments와 분리해 둔다.
    origin_candidates: dict[str, Any] | None = field(default=None)


@dataclass(frozen=True)
class ToolSpec:
    """모델에 보여 줄 도구 이름·설명·인자 스키마. 서버 전용 값(field_origins·observer)은 넣지 않는다."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    """CT-06. 성공이면 error=None, 실패면 data=None. 빈 목록은 성공이다."""

    ok: bool
    data: dict[str, Any] | None
    error: AppError | None
    resource_ids: tuple[str, ...] = ()

    @classmethod
    def success(cls, data: dict[str, Any], resource_ids: tuple[str, ...] = ()) -> "ToolResult":
        return cls(ok=True, data=data, error=None, resource_ids=resource_ids)

    @classmethod
    def failure(cls, error: AppError) -> "ToolResult":
        return cls(ok=False, data=None, error=error)


@dataclass(frozen=True)
class ExecutionPolicy:
    """05-agent-execution.md 실행 상한의 초기값."""

    run_timeout_s: float = 60.0
    max_model_attempts: int = 6
    max_tool_proposals: int = 4
    max_retries_per_call: int = 1
    model_timeout_s: float = 20.0
    tool_timeout_s: float = 10.0
    history_messages: int = 12
    training_cache_size: int = 20


@dataclass(frozen=True)
class RetrievalContext:
    """CT-13의 M1/M2 형태. 문서 미게시 구간이라 knowledge_enabled=false로 고정한다."""

    knowledge_enabled: bool = False
    corpus_snapshot_id: str | None = None


@dataclass(frozen=True)
class ExecutionContext:
    """CT-02. 수락 시 서버가 고정한다. deadline은 같은 프로세스의 단조 시계 기준이다."""

    request_id: str
    conversation_id: str
    run_id: str
    actor: ActorContext
    current_time: datetime
    deadline_monotonic: float
    policy: ExecutionPolicy = field(default_factory=ExecutionPolicy)
    retrieval_context: RetrievalContext = field(default_factory=RetrievalContext)
    timezone: str = "Asia/Seoul"


@dataclass(frozen=True)
class ToolCallRecord:
    """CT-11 RecordToolCall. 허용된 인자 요약만 남기고 원문 비밀·내부 예외는 넣지 않는다."""

    run_id: str
    ordinal: int
    name: str
    attempt: int
    arguments_summary: dict[str, Any]
    duration_ms: int
    ok: bool
    error_code: str | None
    error_stage: str | None
    resource_ids: tuple[str, ...]


@dataclass(frozen=True)
class TrainingResultReceipt:
    """CT-11 RecordTrainingResult. MOD-04 실제 결과의 run/ordinal/교육 ID/시작 시각/hash."""

    run_id: str
    ordinal: int
    training_starts: tuple[tuple[str, str], ...]  # (training_id, starts_at ISO8601)
    result_hash: str


class RequiredRecordError(Exception):
    """필수 기록 저장 실패. 추가 모델·도구 호출을 멈추고 실행을 실패로 끝내야 한다(CT-11)."""


class ExecutionObserver(Protocol):
    """MOD-02가 요구하고 MOD-01 어댑터가 구현한다. M1은 메모리 구현을 쓴다. (run_id, ordinal) 멱등."""

    async def record_tool_call(self, record: ToolCallRecord) -> None: ...

    async def record_training_result(self, receipt: TrainingResultReceipt) -> None: ...


@dataclass(frozen=True)
class ToolExecutionInput:
    """MOD-02→03 서버 실행 입력. field_origins/observer는 모델이 보는 스키마에 없다."""

    proposal: ToolCallProposal
    call_ordinal: int
    observer: ExecutionObserver
    field_origins: dict[str, Any] | None = None
