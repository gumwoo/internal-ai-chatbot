"""T-19 MOD-07 Anthropic 어댑터: SDK 변환·usage·숨은 재시도·오류 구분. 네트워크·과금 없음."""

import anthropic
import httpx2
import pytest
from anthropic.types import Message

from agent.modules.model_integration.anthropic_chat import (
    AnthropicChatModel,
    provider_schema,
    to_provider_messages,
)
from agent.modules.model_integration.ports import (
    ModelCallError,
    ModelConfig,
    ModelFailure,
    ModelMessage,
    ModelRequest,
    ToolResultContent,
    ToolSpec,
)
from agent.shared.contracts import ToolCallProposal

CONTRACT = {
    "type": "object",
    "properties": {"answer": {"type": "string", "minLength": 1}},
    "required": ["answer"],
}
TOOL = ToolSpec(
    name="list_trainings",
    description="교육 목록",
    input_schema={
        "type": "object",
        "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 10}},
    },
)


def _request(**overrides) -> ModelRequest:
    values = {
        "purpose": "agent_answer",
        "messages": (ModelMessage(role="user", text="다음 주 교육"),),
        "tools": (TOOL,),
        "output_contract": CONTRACT,
        "timeout_s": 20,
        "model_config": ModelConfig(model="claude-haiku-5-5", max_output_tokens=1024, config_version="v1"),
        "system": "시스템",
    }
    values.update(overrides)
    return ModelRequest(**values)


def _message(content, stop_reason="end_turn", usage=None):
    return Message.model_validate(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-haiku-5-5",
            "content": content,
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": usage or {"input_tokens": 100, "output_tokens": 20},
        }
    )


class _FakeMessages:
    def __init__(self, result):
        self.result = result
        self.calls: list[dict] = []

    async def create(self, **params):
        self.calls.append(params)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class _FakeClient:
    def __init__(self, result):
        self.messages = _FakeMessages(result)


def _model(result) -> tuple[AnthropicChatModel, _FakeClient]:
    client = _FakeClient(result)
    return AnthropicChatModel(api_key=None, client=client), client


_REQ = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def _status_error(cls, status: int):
    return cls("err", response=httpx2.Response(status, request=_REQ), body=None)


def test_real_client_disables_sdk_retries():
    model = AnthropicChatModel(api_key="sk-test-not-real")
    assert model._client.max_retries == 0


def test_provider_schema_strips_unsupported_and_closes_objects():
    schema = provider_schema(TOOL.input_schema)
    assert schema == {
        "type": "object",
        "properties": {"limit": {"type": "integer"}},
        "additionalProperties": False,
    }


def test_messages_put_tool_results_in_user_turn_and_merge_roles():
    call = ToolCallProposal(name="list_trainings", arguments={"limit": 5}, provider_call_id="toolu_1")
    messages = (
        ModelMessage(role="user", text="질문"),
        ModelMessage(role="assistant", text="조회할게요", tool_calls=(call,)),
        ModelMessage(role="tool_result", tool_results=(ToolResultContent("toolu_1", '{"items": []}'),)),
        ModelMessage(role="user", text="추가 질문"),
    )
    converted = to_provider_messages(messages)
    assert [m["role"] for m in converted] == ["user", "assistant", "user"]
    assert converted[1]["content"][1] == {
        "type": "tool_use",
        "id": "toolu_1",
        "name": "list_trainings",
        "input": {"limit": 5},
    }
    assert [b["type"] for b in converted[2]["content"]] == ["tool_result", "text"]


async def test_request_params_thinking_off_strict_tools_and_output_schema():
    model, client = _model(_message([{"type": "text", "text": '{"answer": "ok"}'}]))
    await model.complete_once(_request())
    params = client.messages.calls[0]
    assert params["thinking"] == {"type": "disabled"}
    assert params["tools"][0]["strict"] is True
    assert params["output_config"]["format"]["type"] == "json_schema"
    assert "minLength" not in str(params["output_config"])
    assert params["timeout"] == 20
    assert "tool_choice" not in params


async def test_tool_turn_with_text_is_not_final():
    model, _ = _model(
        _message(
            [
                {"type": "text", "text": "목록을 볼게요"},
                {"type": "tool_use", "id": "toolu_9", "name": "list_trainings", "input": {"limit": 3}},
            ],
            stop_reason="tool_use",
        )
    )
    response = await model.complete_once(_request())
    assert response.wants_tools
    assert response.final_candidate is None
    assert response.tool_proposals[0] == ToolCallProposal("list_trainings", {"limit": 3}, "toolu_9")
    assert response.as_assistant_message().tool_calls == response.tool_proposals


async def test_final_json_and_usage_includes_cache_tokens():
    usage = {
        "input_tokens": 100,
        "output_tokens": 30,
        "cache_creation_input_tokens": 10,
        "cache_read_input_tokens": 5,
    }
    model, _ = _model(_message([{"type": "text", "text": '{"answer": "두 건입니다"}'}], usage=usage))
    response = await model.complete_once(_request())
    assert response.final_candidate == {"answer": "두 건입니다"}
    assert (response.usage.input_tokens, response.usage.output_tokens, response.usage.complete) == (
        115,
        30,
        True,
    )
    assert response.model_id == "claude-haiku-5-5"


@pytest.mark.parametrize(
    ("content", "stop_reason", "kind"),
    [
        ([{"type": "text", "text": "JSON 아님"}], "end_turn", ModelFailure.OUTPUT_INVALID),
        ([{"type": "text", "text": "[1, 2]"}], "end_turn", ModelFailure.OUTPUT_INVALID),
        (
            [{"type": "tool_use", "id": "t", "name": "list_trainings", "input": {}}],
            "max_tokens",
            ModelFailure.OUTPUT_INVALID,
        ),
        ([{"type": "text", "text": "..."}], "refusal", ModelFailure.INPUT_REJECTED),
        ([{"type": "text", "text": "..."}], "pause_turn", ModelFailure.OUTPUT_INVALID),
    ],
)
async def test_invalid_outputs_are_errors_not_answers(content, stop_reason, kind):
    model, _ = _model(_message(content, stop_reason=stop_reason))
    with pytest.raises(ModelCallError) as info:
        await model.complete_once(_request())
    assert info.value.kind is kind
    assert info.value.internal_cause_id
    assert info.value.usage.complete is True  # 실패해도 실제 사용량은 보존한다


F = ModelFailure


# kind → 오류 코드·retryable 대응은 test_model_ports.py가 검사한다. 여기서는 SDK 예외 → kind만 본다.
@pytest.mark.parametrize(
    ("error", "kind", "retryable"),
    [
        (lambda: _status_error(anthropic.RateLimitError, 429), F.RATE_LIMITED, True),
        (lambda: anthropic.APITimeoutError(request=_REQ), F.TIMEOUT, True),
        (lambda: anthropic.APIConnectionError(request=_REQ), F.UPSTREAM_UNAVAILABLE, True),
        (lambda: _status_error(anthropic.InternalServerError, 529), F.UPSTREAM_UNAVAILABLE, True),
        (lambda: _status_error(anthropic.AuthenticationError, 401), F.NOT_CONFIGURED, False),
        (lambda: _status_error(anthropic.BadRequestError, 400), F.INPUT_REJECTED, False),
    ],
)
async def test_sdk_errors_are_classified(error, kind, retryable):
    model, _ = _model(error())
    with pytest.raises(ModelCallError) as info:
        await model.complete_once(_request())
    assert (info.value.kind, info.value.retryable) == (kind, retryable)
    assert info.value.usage.complete is False
    assert "err" not in info.value.safe_message


async def test_missing_key_is_not_configured_without_network():
    with pytest.raises(ModelCallError) as info:
        await AnthropicChatModel(api_key=None).complete_once(_request())
    assert info.value.kind is ModelFailure.NOT_CONFIGURED


async def test_failure_carries_internal_note_and_client_closes():
    closed = []

    class ClosingClient(_FakeClient):
        async def close(self):
            closed.append(True)

    client = ClosingClient(_message([{"type": "text", "text": "JSON 아님"}]))
    model = AnthropicChatModel(api_key=None, client=client)
    with pytest.raises(ModelCallError) as info:
        await model.complete_once(_request())
    assert info.value.__notes__ == ["final json"]
    await model.aclose()
    assert closed == [True]
