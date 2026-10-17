"""테스트용 결정적 모델(ChatModel·EmbeddingModel). 실제 SDK 어댑터와 같은 포트로 교체한다."""

import hashlib
import struct
from collections import deque
from collections.abc import Iterable

from agent.modules.model_integration.ports import (
    EmbeddingBatch,
    EmbeddingConfig,
    ModelCallError,
    ModelRequest,
    ModelResponse,
    Usage,
)


class FakeModelClient:
    """미리 넣은 응답·오류를 순서대로 돌려주고 받은 요청을 기록한다."""

    def __init__(self, script: Iterable[ModelResponse | ModelCallError] = ()) -> None:
        self._script: deque[ModelResponse | ModelCallError] = deque(script)
        self.requests: list[ModelRequest] = []
        self.embed_calls: list[tuple[str, ...]] = []

    async def complete_once(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if not self._script:
            raise AssertionError("FakeModelClient에 남은 응답이 없다")
        item = self._script.popleft()
        if isinstance(item, ModelCallError):
            raise item
        return item

    async def embed_once(
        self, texts: tuple[str, ...], config: EmbeddingConfig, timeout_s: float
    ) -> EmbeddingBatch:
        self.embed_calls.append(texts)
        return EmbeddingBatch(
            model_id=f"fake:{config.model}",
            dimension=config.dimension,
            vectors=tuple(_vector(text, config.dimension) for text in texts),
            usage=Usage(input_tokens=None, output_tokens=None, complete=True),
            input_count=len(texts),
        )


def _vector(text: str, dimension: int) -> tuple[float, ...]:
    """텍스트 해시로 만든 결정적 벡터. 의미 유사도는 없다."""
    out: list[float] = []
    counter = 0
    while len(out) < dimension:
        digest = hashlib.sha256(f"{counter}:{text}".encode()).digest()
        out.extend((v / 2**31) - 1.0 for v in struct.unpack(">8I", digest))
        counter += 1
    vector = out[:dimension]
    if not any(vector):
        vector[0] = 1.0
    return tuple(vector)
