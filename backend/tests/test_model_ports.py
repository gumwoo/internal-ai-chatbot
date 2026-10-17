import math

import pytest

from agent.modules.model_integration.fake import FakeModelClient
from agent.modules.model_integration.ports import (
    EmbeddingBatch,
    EmbeddingConfig,
    ModelCallError,
    ModelConfig,
    ModelFailure,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    Usage,
)
from agent.shared.contracts import ToolCallProposal
from agent.shared.errors import ErrorCode

CONFIG = EmbeddingConfig(model="gemini-embedding-2", dimension=8, task="query")
UNKNOWN_USAGE = Usage(input_tokens=None, output_tokens=None, complete=False)


def _batch(vectors, input_count=None):
    return EmbeddingBatch(
        model_id="m",
        dimension=2,
        vectors=vectors,
        usage=UNKNOWN_USAGE,
        input_count=len(vectors) if input_count is None else input_count,
    )


def _request() -> ModelRequest:
    return ModelRequest(
        purpose="agent_answer",
        messages=(ModelMessage(role="user", text="다음 주 교육 알려줘"),),
        tools=(),
        output_contract=None,
        timeout_s=20,
        model_config=ModelConfig(model="claude-haiku-5-5", max_output_tokens=1024, config_version="v1"),
    )


@pytest.mark.parametrize(
    ("vectors", "input_count"),
    [
        (((1.0, 0.0),), 2),  # 개수 불일치
        (((1.0, 0.0, 0.0),), None),  # 차원 불일치
        (((math.nan, 1.0),), None),  # 유한하지 않은 값
        (((math.inf, 1.0),), None),
        (((0.0, 0.0),), None),  # 0 벡터
    ],
)
def test_embedding_batch_rejects_invalid_vectors(vectors, input_count):
    with pytest.raises(ModelCallError) as info:
        _batch(vectors, input_count)
    assert info.value.code is ErrorCode.MODEL_OUTPUT_INVALID


def test_embedding_batch_accepts_valid_vectors():
    batch = _batch(((1.0, 0.0), (0.0, -2.5)))
    assert len(batch.vectors) == 2


@pytest.mark.parametrize(
    ("kind", "code", "retryable"),
    [
        (ModelFailure.NOT_CONFIGURED, ErrorCode.MODEL_NOT_CONFIGURED, False),
        (ModelFailure.RATE_LIMITED, ErrorCode.UPSTREAM_RATE_LIMITED, True),
        (ModelFailure.TIMEOUT, ErrorCode.MODEL_UPSTREAM_ERROR, True),
        (ModelFailure.UPSTREAM_UNAVAILABLE, ErrorCode.MODEL_UPSTREAM_ERROR, True),
        (ModelFailure.INPUT_REJECTED, ErrorCode.MODEL_UPSTREAM_ERROR, False),
        (ModelFailure.OUTPUT_INVALID, ErrorCode.MODEL_OUTPUT_INVALID, False),
    ],
)
def test_model_failures_map_to_closed_codes(kind, code, retryable):
    error = ModelCallError(kind)
    assert (error.code, error.retryable, error.kind) == (code, retryable, kind)
    assert error.usage.complete is False


async def test_fake_embeddings_are_deterministic_and_ordered():
    client = FakeModelClient()
    first = await client.embed_once(("가", "나"), CONFIG, timeout_s=5)
    second = await client.embed_once(("나", "가"), CONFIG, timeout_s=5)
    assert first.vectors[0] == second.vectors[1]
    assert first.vectors[1] == second.vectors[0]
    assert first.vectors[0] != first.vectors[1]
    assert first.dimension == 8


async def test_fake_complete_replays_script_and_records_requests():
    tool_turn = ModelResponse(
        tool_proposals=(ToolCallProposal(name="list_trainings", arguments={}, provider_call_id="p1"),),
        final_candidate=None,
        model_id="fake",
        purpose="agent_answer",
        config_version="v1",
        usage=UNKNOWN_USAGE,
    )
    client = FakeModelClient([tool_turn, ModelCallError(ModelFailure.RATE_LIMITED)])
    response = await client.complete_once(_request())
    assert response.wants_tools
    with pytest.raises(ModelCallError) as info:
        await client.complete_once(_request())
    assert info.value.code is ErrorCode.UPSTREAM_RATE_LIMITED
    assert len(client.requests) == 2
