"""임베딩 준비(MOD-06 소유: 재시도·속도 조절·재사용). 저장 commit은 MOD-05가 한다.

- 같은 (모델, 차원, 입력 형식, 입력 텍스트)의 벡터는 준비 산출물 캐시(JSONL)에서 재사용한다. 무료 티어 한도
  (2026-10-17 확인: 분당 100건, 묶음 안 입력 하나가 1건)에서 다시 돌려도 같은 입력을 다시 보내지 않는다.
- 요청 속도는 분당 입력 수로 제한한다. 한도 초과(429)는 기다렸다 다시 시도하고, 횟수를 넘기면 중단한다.
  중단해도 그때까지 받은 벡터는 캐시에 남아 다음 실행에서 이어 간다.
- 일부만 성공한 준비를 전량 성공으로 보고하지 않는다(CT-09). 모두 받지 못하면 EmbeddingIncomplete.
"""

import asyncio
import hashlib
import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from agent.modules.model_integration.ports import (
    EmbeddingConfig,
    EmbeddingModel,
    ModelCallError,
    ModelFailure,
)


class EmbeddingIncomplete(Exception):
    """일부 입력의 벡터를 받지 못했다. done/total을 보고한다."""

    def __init__(self, done: int, total: int, reason: str) -> None:
        super().__init__(f"임베딩 미완료 {done}/{total}: {reason}")
        self.done, self.total, self.reason = done, total, reason


@dataclass
class EmbedReport:
    total: int = 0
    cached: int = 0
    requested: int = 0
    requests: int = 0
    rate_limited: int = 0
    seconds: float = 0.0


@dataclass
class EmbeddingCache:
    path: Path
    _vectors: dict[str, tuple[float, ...]] = field(default_factory=dict)

    @classmethod
    def open(cls, directory: Path, config: EmbeddingConfig, input_format: str) -> "EmbeddingCache":
        directory.mkdir(parents=True, exist_ok=True)
        cache = cls(directory / f"{config.model}-{config.dimension}-{input_format}.jsonl")
        if cache.path.exists():
            for line in cache.path.read_text(encoding="utf-8").splitlines():
                try:
                    record = json.loads(line)
                    vector = tuple(float(v) for v in record["vector"])
                except (ValueError, KeyError, TypeError):
                    continue  # 중단으로 깨진 줄은 버리고 다시 받는다
                if len(vector) == config.dimension and all(math.isfinite(v) for v in vector) and any(vector):
                    cache._vectors[record["key"]] = vector
        return cache

    def get(self, text: str) -> tuple[float, ...] | None:
        return self._vectors.get(_key(text))

    def put_many(self, texts: list[str], vectors: tuple[tuple[float, ...], ...]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            for text, vector in zip(texts, vectors, strict=True):
                key = _key(text)
                self._vectors[key] = vector
                handle.write(json.dumps({"key": key, "vector": list(vector)}) + "\n")


def _key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def embed_texts(
    model: EmbeddingModel,
    texts: list[str],
    config: EmbeddingConfig,
    cache: EmbeddingCache | None,
    *,
    batch_size: int = 100,
    per_minute: int = 100,
    max_rate_limit_waits: int = 3,
    timeout_s: float = 60.0,
    sleep: Callable[[float], object] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[list[tuple[float, ...]], EmbedReport]:
    report = EmbedReport(total=len(texts))
    started = clock()
    vectors: list[tuple[float, ...] | None] = [cache.get(t) if cache else None for t in texts]
    report.cached = sum(v is not None for v in vectors)
    batch_size = max(1, min(batch_size, per_minute))
    # 같은 텍스트는 한 번만 보낸다.
    first_index: dict[str, int] = {}
    missing = []
    for i, v in enumerate(vectors):
        if v is None and texts[i] not in first_index:
            first_index[texts[i]] = i
            missing.append(i)
    window_start, window_count = clock(), 0
    position = 0
    waits = 0
    while position < len(missing):
        indexes = missing[position : position + batch_size]
        if window_count + len(indexes) > per_minute:
            await sleep(max(0.0, 61.0 - (clock() - window_start)))
            window_start, window_count = clock(), 0
        batch = [texts[i] for i in indexes]
        try:
            result = await model.embed_once(tuple(batch), config, timeout_s)
        except ModelCallError as error:
            if error.kind is ModelFailure.RATE_LIMITED and waits < max_rate_limit_waits:
                waits += 1
                report.rate_limited += 1
                await sleep(61.0)
                window_start, window_count = clock(), 0
                continue
            done = sum(v is not None for v in vectors)
            raise EmbeddingIncomplete(done, len(texts), error.kind.value) from error
        waits = 0  # 연속 실패만 센다
        report.requests += 1
        report.requested += len(batch)
        window_count += len(batch)
        if cache is not None:
            cache.put_many(batch, result.vectors)
        for i, vector in zip(indexes, result.vectors, strict=True):
            vectors[i] = vector
        position += len(indexes)
    for i, text in enumerate(texts):
        if vectors[i] is None:
            vectors[i] = vectors[first_index[text]]
    report.seconds = round(clock() - started, 1)
    return [v for v in vectors if v is not None], report
