"""Anthropic Messages API 어댑터(D-25). 공급자 객체·예외는 이 파일 밖으로 내보내지 않는다.

- 한 호출이 한 시도다. SDK 자동 재시도는 끈다(max_retries=0). 재시도는 MOD-02가 소유한다.
- 도구는 strict 스키마, 최종 답변은 output_config의 JSON 스키마로 받는다.
- 도구 제안과 텍스트가 함께 오면 도구 턴으로 본다. 완료 답변으로 다루지 않는다(CT-07).
"""

import json
import logging
import uuid
from typing import Any

import anthropic

from agent.modules.model_integration.ports import (
    ModelCallError,
    ModelFailure,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    Usage,
)
from agent.shared.contracts import ToolCallProposal

logger = logging.getLogger(__name__)

# strict 스키마가 지원하지 않는 키. 값 검증은 서버(MOD-03)의 Pydantic 모델이 그대로 한다.
_UNSUPPORTED_SCHEMA_KEYS = frozenset(
    {
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minItems",
        "maxItems",
        "uniqueItems",
        "default",
        "title",
    }
)


# 값이 "이름 → 스키마" 사전인 키워드. 이 안의 키는 속성·정의 이름이라 지우면 안 된다.
_NAME_MAP_KEYS = frozenset({"properties", "$defs", "definitions", "patternProperties"})


def provider_schema(schema: Any) -> Any:
    """공급자에 보낼 스키마: 지원하지 않는 제약을 빼고 모든 object에 additionalProperties=false를 둔다.

    `title`·`default` 같은 이름의 속성은 그대로 둔다(키워드 위치에서만 지운다).
    """
    if isinstance(schema, list):
        return [provider_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    cleaned: dict[str, Any] = {}
    for key, value in schema.items():
        if key in _NAME_MAP_KEYS and isinstance(value, dict):
            cleaned[key] = {name: provider_schema(sub) for name, sub in value.items()}
        elif key not in _UNSUPPORTED_SCHEMA_KEYS:
            cleaned[key] = provider_schema(value)
    if cleaned.get("type") == "object" or "properties" in cleaned:
        cleaned["additionalProperties"] = False
    return cleaned


def _content(message: ModelMessage) -> list[dict[str, Any]]:
    if message.role == "user":
        return [{"type": "text", "text": message.text or ""}]
    if message.role == "assistant":
        blocks: list[dict[str, Any]] = []
        if message.text:
            blocks.append({"type": "text", "text": message.text})
        blocks.extend(
            {"type": "tool_use", "id": call.provider_call_id, "name": call.name, "input": call.arguments}
            for call in message.tool_calls
        )
        return blocks
    return [
        {
            "type": "tool_result",
            "tool_use_id": result.provider_call_id,
            "content": result.content,
            "is_error": result.is_error,
        }
        for result in message.tool_results
    ]


def to_provider_messages(messages: tuple[ModelMessage, ...]) -> list[dict[str, Any]]:
    """tool_result는 user 역할로 보낸다. 같은 역할이 이어지면 한 메시지로 합친다.

    내용이 없는 항목(빈 텍스트, 빈 assistant 턴)은 보내지 않는다. API가 빈 블록을 거절할 수 있다.
    """
    out: list[dict[str, Any]] = []
    for message in messages:
        role = "assistant" if message.role == "assistant" else "user"
        blocks = [b for b in _content(message) if not (b["type"] == "text" and not b["text"])]
        if not blocks:
            continue
        if out and out[-1]["role"] == role:
            out[-1]["content"].extend(blocks)
        else:
            out.append({"role": role, "content": blocks})
    return out


def _usage(raw: Any) -> Usage:
    if raw is None:
        return Usage(input_tokens=None, output_tokens=None, complete=False)
    cached = (raw.cache_creation_input_tokens or 0) + (raw.cache_read_input_tokens or 0)
    return Usage(input_tokens=raw.input_tokens + cached, output_tokens=raw.output_tokens, complete=True)


def _failure(kind: ModelFailure, exc: BaseException | None, detail: str, usage: Usage | None = None):
    """내부 원인은 로그에만 남기고 상관관계 ID만 오류에 붙인다. 키·본문은 남기지 않는다."""
    cause_id = str(uuid.uuid4())
    logger.warning(
        "모델 호출 실패 cause_id=%s kind=%s detail=%s error=%s",
        cause_id,
        kind.value,
        detail,
        type(exc).__name__ if exc else None,
    )
    error = ModelCallError(kind, usage=usage, internal_cause_id=cause_id)
    error.add_note(detail)  # 내부 진단용. HTTP 응답(envelope)에는 들어가지 않는다.
    return error


def _classify(exc: anthropic.APIError) -> ModelFailure:
    # APITimeoutError는 APIConnectionError의 하위 클래스라 먼저 본다.
    if isinstance(exc, anthropic.APITimeoutError):
        return ModelFailure.TIMEOUT
    if isinstance(exc, anthropic.APIConnectionError):
        return ModelFailure.UPSTREAM_UNAVAILABLE
    # 응답은 왔지만 SDK가 형식을 해석하지 못함: 공급자 출력 무효.
    if isinstance(exc, anthropic.APIResponseValidationError):
        return ModelFailure.OUTPUT_INVALID
    if isinstance(exc, anthropic.RateLimitError):
        return ModelFailure.RATE_LIMITED
    # 키 오류·권한 부족·모델 ID 오류(404)는 재시도로 낫지 않는 설정 문제다.
    if isinstance(
        exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError, anthropic.NotFoundError)
    ):
        return ModelFailure.NOT_CONFIGURED
    if isinstance(exc, anthropic.APIStatusError):
        # SDK 기본 정책이 재시도하는 408·409는 일시 오류로 본다.
        if exc.status_code == 408:
            return ModelFailure.TIMEOUT
        if exc.status_code == 409 or exc.status_code >= 500:
            return ModelFailure.UPSTREAM_UNAVAILABLE
    return ModelFailure.INPUT_REJECTED


class AnthropicChatModel:
    """client는 테스트에서 가짜 messages.create를 넣을 때만 넘긴다."""

    def __init__(self, api_key: str | None, client: Any | None = None) -> None:
        if client is None and api_key:
            client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=0)
        self._client = client

    async def aclose(self) -> None:
        """SDK 연결을 닫는다. 이벤트 루프가 끝나기 전에 호출한다."""
        close = getattr(self._client, "close", None)
        if close is not None:
            await close()

    async def complete_once(self, request: ModelRequest) -> ModelResponse:
        if self._client is None:
            raise _failure(ModelFailure.NOT_CONFIGURED, None, "api key missing")
        try:
            raw = await self._client.messages.create(**self.build_params(request))
        except anthropic.APIError as exc:
            raise _failure(_classify(exc), exc, "api error") from exc
        return self._parse(raw, request)

    @staticmethod
    def build_params(request: ModelRequest) -> dict[str, Any]:
        config = request.model_config
        params: dict[str, Any] = {
            "model": config.model,
            "max_tokens": config.max_output_tokens,
            "messages": to_provider_messages(request.messages),
            "thinking": {"type": config.thinking},
            "timeout": request.timeout_s,
        }
        if request.system:
            params["system"] = request.system
        if request.tools:
            params["tools"] = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": provider_schema(tool.input_schema),
                    "strict": True,
                }
                for tool in request.tools
            ]
        if request.tools and request.tool_choice == "any":
            # 도구 호출을 강제하는 요청은 최종 JSON을 받지 않는다(응답이 tool_use뿐이다).
            params["tool_choice"] = {"type": "any"}
        elif request.output_contract is not None:
            params["output_config"] = {
                "format": {"type": "json_schema", "schema": provider_schema(request.output_contract)}
            }
        return params

    def _parse(self, raw: Any, request: ModelRequest) -> ModelResponse:
        usage = _usage(getattr(raw, "usage", None))
        stop = raw.stop_reason
        if stop == "refusal":
            raise _failure(ModelFailure.INPUT_REJECTED, None, "refusal", usage)
        if stop == "max_tokens":
            # 잘린 도구 인자는 그럴듯한 부분 객체로 보일 수 있어 도구 턴이어도 실행하지 않는다.
            raise _failure(ModelFailure.OUTPUT_INVALID, None, "max_tokens", usage)
        text = "".join(block.text for block in raw.content if block.type == "text") or None
        proposals = tuple(
            ToolCallProposal(name=block.name, arguments=dict(block.input), provider_call_id=block.id)
            for block in raw.content
            if block.type == "tool_use"
        )
        common: dict[str, Any] = {
            "model_id": raw.model,
            "purpose": request.purpose,
            "config_version": request.model_config.config_version,
            "usage": usage,
            "text": text,
        }
        if proposals:
            return ModelResponse(tool_proposals=proposals, final_candidate=None, **common)
        if stop not in ("end_turn", "stop_sequence"):
            raise _failure(ModelFailure.OUTPUT_INVALID, None, f"stop_reason={stop}", usage)
        final: dict[str, Any] | None = None
        if request.output_contract is not None:
            try:
                parsed = json.loads(text or "")
            except json.JSONDecodeError as exc:
                raise _failure(ModelFailure.OUTPUT_INVALID, exc, "final json", usage) from exc
            if not isinstance(parsed, dict):
                raise _failure(ModelFailure.OUTPUT_INVALID, None, "final not object", usage)
            final = parsed
        return ModelResponse(tool_proposals=(), final_candidate=final, **common)
