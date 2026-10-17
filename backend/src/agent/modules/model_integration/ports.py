"""CT-07 ModelRequest / ModelResponse / EmbeddingBatch와 ModelClient 포트.

호출 한 번이 한 시도다. 재시도는 호출하는 모듈(MOD-02/06/10)이 소유한다.
"""

import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal, Protocol

from agent.shared.contracts import ToolCallProposal
from agent.shared.errors import AppError, ErrorCode

Purpose = Literal["agent_answer", "wiki_build", "eval_judge"]


@dataclass(frozen=True)
class ModelMessage:
    role: Literal["user", "assistant", "tool_result"]
    content: Any


@dataclass(frozen=True)
class ToolSpec:
    """모델에 보여 줄 도구 이름·설명·인자 스키마. 서버 전용 값(field_origins 등)은 넣지 않는다."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ModelConfig:
    model: str
    max_output_tokens: int
    config_version: str


@dataclass(frozen=True)
class ModelRequest:
    purpose: Purpose
    messages: tuple[ModelMessage, ...]
    tools: tuple[ToolSpec, ...]
    output_contract: dict[str, Any] | None
    timeout_s: float
    model_config: ModelConfig
    system: str | None = None


@dataclass(frozen=True)
class Usage:
    """모르는 값은 None. 실패 호출도 과금이 0이라고 단정하지 않는다(complete=False)."""

    input_tokens: int | None
    output_tokens: int | None
    complete: bool


@dataclass(frozen=True)
class ModelResponse:
    """도구 제안이 있으면 final_candidate가 있어도 완료 답변으로 다루지 않는다."""

    tool_proposals: tuple[ToolCallProposal, ...]
    final_candidate: dict[str, Any] | None
    model_id: str
    purpose: Purpose
    config_version: str
    usage: Usage

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_proposals)


@dataclass(frozen=True)
class EmbeddingConfig:
    model: str
    dimension: int
    task: Literal["document", "query"]


@dataclass(frozen=True)
class EmbeddingBatch:
    """vectors[i]는 texts[i]의 벡터다. 생성할 때 개수·차원·유한 수·0 벡터를 검사한다."""

    model_id: str
    dimension: int
    vectors: tuple[tuple[float, ...], ...]
    usage: Usage
    input_count: int = field(repr=False)

    def __post_init__(self) -> None:
        if len(self.vectors) != self.input_count:
            raise _invalid("벡터 수가 입력 수와 다르다")
        for vector in self.vectors:
            if len(vector) != self.dimension:
                raise _invalid("벡터 차원이 설정과 다르다")
            if not all(math.isfinite(x) for x in vector):
                raise _invalid("벡터에 유한하지 않은 값이 있다")
            if not any(vector):
                raise _invalid("0 벡터가 있다")


class ModelFailure(StrEnum):
    """MOD-07이 구분해야 하는 실패 종류. 닫힌 오류 사전의 코드로 내보낸다."""

    NOT_CONFIGURED = "not_configured"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    INPUT_REJECTED = "input_rejected"
    OUTPUT_INVALID = "output_invalid"


# 사전에 모델 시간 초과 전용 코드가 없어 TIMEOUT은 MODEL_UPSTREAM_ERROR로 내보내고 kind로 구분한다.
_FAILURE_CODE = {
    ModelFailure.NOT_CONFIGURED: (ErrorCode.MODEL_NOT_CONFIGURED, False),
    ModelFailure.RATE_LIMITED: (ErrorCode.UPSTREAM_RATE_LIMITED, True),
    ModelFailure.TIMEOUT: (ErrorCode.MODEL_UPSTREAM_ERROR, True),
    ModelFailure.UPSTREAM_UNAVAILABLE: (ErrorCode.MODEL_UPSTREAM_ERROR, True),
    ModelFailure.INPUT_REJECTED: (ErrorCode.MODEL_UPSTREAM_ERROR, False),
    ModelFailure.OUTPUT_INVALID: (ErrorCode.MODEL_OUTPUT_INVALID, False),
}


class ModelCallError(AppError):
    def __init__(
        self, kind: ModelFailure, usage: Usage | None = None, internal_cause_id: str | None = None
    ) -> None:
        code, retryable = _FAILURE_CODE[kind]
        super().__init__(code, retryable=retryable, internal_cause_id=internal_cause_id)
        self.kind = kind
        self.usage = usage or Usage(input_tokens=None, output_tokens=None, complete=False)


def _invalid(reason: str) -> ModelCallError:
    error = ModelCallError(ModelFailure.OUTPUT_INVALID)
    error.add_note(reason)
    return error


class ModelClient(Protocol):
    async def complete_once(self, request: ModelRequest) -> ModelResponse: ...

    async def embed_once(
        self, texts: tuple[str, ...], config: EmbeddingConfig, timeout_s: float
    ) -> EmbeddingBatch: ...
