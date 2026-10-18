"""Google Gemini 구조화 생성 어댑터(평가 judge 전용, D-25/D-27). 공급자 객체·예외는 밖으로 내보내지 않는다.

- purpose=eval_judge만 받는다(답변 생성·Wiki 빌드는 Anthropic). 도구는 쓰지 않는다.
- 한 호출이 한 시도다. SDK 재시도는 끈다(재시도는 평가 실행기가 소유한다).
- 출력은 response_schema의 JSON으로 받는다. 사용량은 응답 metadata가 있을 때만 채운다(없으면 미확인).
- 무료 티어 입력은 Google 제품 개선에 쓰일 수 있으므로 가상 문서·평가 문항에만 쓴다(D-27).
"""

import asyncio
import json

import httpx
from google import genai
from google.genai import errors, types

from agent.modules.model_integration.ports import (
    ModelCallError,
    ModelFailure,
    ModelRequest,
    ModelResponse,
    Usage,
)


class GeminiJudgeModel:
    def __init__(self, api_key: str | None, client: object | None = None) -> None:
        self._api_key = api_key
        self._client = client

    def _sdk(self):
        if self._client is None:
            if not self._api_key:
                raise ModelCallError(ModelFailure.NOT_CONFIGURED)
            options = types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1))
            self._client = genai.Client(api_key=self._api_key, http_options=options)
        return self._client

    async def complete_once(self, request: ModelRequest) -> ModelResponse:
        if request.purpose != "eval_judge" or request.tools or request.output_contract is None:
            raise ModelCallError(ModelFailure.INPUT_REJECTED)
        contents = [
            types.Content(role="user", parts=[types.Part(text=m.text or "")]) for m in request.messages
        ]
        config = types.GenerateContentConfig(
            system_instruction=request.system,
            response_mime_type="application/json",
            response_json_schema=request.output_contract,
            max_output_tokens=request.model_config.max_output_tokens,
            temperature=0.0,
        )
        try:
            async with asyncio.timeout(request.timeout_s):
                response = await self._sdk().aio.models.generate_content(
                    model=request.model_config.model, contents=contents, config=config
                )
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise ModelCallError(ModelFailure.TIMEOUT) from exc
        except errors.APIError as exc:
            raise ModelCallError(_failure(exc.code)) from exc
        except (OSError, ValueError, httpx.TransportError) as exc:
            raise ModelCallError(ModelFailure.UPSTREAM_UNAVAILABLE) from exc
        meta = getattr(response, "usage_metadata", None)
        usage = Usage(
            input_tokens=getattr(meta, "prompt_token_count", None),
            output_tokens=getattr(meta, "candidates_token_count", None),
            complete=meta is not None,
        )
        try:
            parsed = json.loads(response.text or "")
        except (json.JSONDecodeError, ValueError) as exc:
            raise ModelCallError(ModelFailure.OUTPUT_INVALID, usage) from exc
        if not isinstance(parsed, dict):
            raise ModelCallError(ModelFailure.OUTPUT_INVALID, usage)
        return ModelResponse(
            tool_proposals=(),
            final_candidate=parsed,
            model_id=getattr(response, "model_version", None) or request.model_config.model,
            purpose="eval_judge",
            config_version=request.model_config.config_version,
            usage=usage,
        )

    async def aclose(self) -> None:
        client = self._client
        if client is not None and hasattr(client, "aio"):
            await client.aio.aclose()


def _failure(status: int | None) -> ModelFailure:
    if status == 429:
        return ModelFailure.RATE_LIMITED
    if status in (400, 404, 413, 422):
        return ModelFailure.INPUT_REJECTED
    if status in (401, 403):
        return ModelFailure.NOT_CONFIGURED
    return ModelFailure.UPSTREAM_UNAVAILABLE
