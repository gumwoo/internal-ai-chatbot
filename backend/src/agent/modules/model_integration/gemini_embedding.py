"""Google Gemini 임베딩 어댑터(D-27, D-32). 공급자 객체·예외는 이 파일 밖으로 내보내지 않는다.

- 한 호출이 한 시도다. SDK 재시도는 끈다(MOD-06이 재시도를 소유한다).
- 입력마다 별도 Content로 보낸다. 문자열 목록을 그대로 넘기면 SDK가 하나의 Content로 합쳐 벡터가 하나만 온다.
- 결과 벡터 수·차원은 요청과 대조한다(EmbeddingBatch가 검사). 길이를 1로 맞춰 거리 계산을 일정하게 한다.
- 검색 작업 구분은 입력 앞의 지시문으로 한다(EMBED_FORMAT). 2026-10-17 확인에서 task_type을 바꿔도 같은
  문장쌍의 유사도가 같았다(무시되는 것으로 추정, 공급자 문서로 확인하지 않음).
- 무료 티어 입력은 Google 제품 개선에 쓰이므로 가상 문서에만 쓴다(D-27).
"""

import asyncio
import logging
import math

import httpx
from google import genai
from google.genai import errors, types

from agent.modules.model_integration.ports import (
    EmbeddingBatch,
    EmbeddingConfig,
    ModelCallError,
    ModelFailure,
    Usage,
)

logger = logging.getLogger(__name__)

EMBED_FORMAT = "gemini-embedding-2-prefix-v1"
MAX_BATCH = 100  # batchEmbedContents 한 번의 입력 수 상한


def format_input(text: str, task: str, title: str | None = None) -> str:
    """작업별 입력 형식(EMBED_FORMAT). 문서는 제목과 본문, 질문은 검색 질의로 표시한다."""
    if task == "query":
        return f"task: search result | query: {text}"
    return f"title: {title or 'none'} | text: {text}"


class GeminiEmbeddingModel:
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

    async def embed_once(
        self, texts: tuple[str, ...], config: EmbeddingConfig, timeout_s: float
    ) -> EmbeddingBatch:
        if not texts or len(texts) > MAX_BATCH:
            raise ModelCallError(ModelFailure.INPUT_REJECTED)
        contents = [types.Content(parts=[types.Part(text=text)]) for text in texts]
        request = types.EmbedContentConfig(output_dimensionality=config.dimension)
        try:
            async with asyncio.timeout(timeout_s):
                response = await self._sdk().aio.models.embed_content(
                    model=config.model, contents=contents, config=request
                )
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise ModelCallError(ModelFailure.TIMEOUT) from exc
        except errors.APIError as exc:
            raise ModelCallError(_failure(exc.code)) from exc
        except (OSError, ValueError, httpx.TransportError) as exc:
            raise ModelCallError(ModelFailure.UPSTREAM_UNAVAILABLE) from exc
        vectors = tuple(_unit(tuple(e.values or ())) for e in (response.embeddings or []))
        return EmbeddingBatch(
            model_id=config.model,
            dimension=config.dimension,
            vectors=vectors,
            # 무료 티어 응답에는 사용량(metadata)이 없다. 0으로 채우지 않는다(T-19).
            usage=Usage(input_tokens=None, output_tokens=None, complete=False),
            input_count=len(texts),
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


def _unit(vector: tuple[float, ...]) -> tuple[float, ...]:
    norm = math.sqrt(sum(v * v for v in vector))
    return tuple(v / norm for v in vector) if norm else vector
