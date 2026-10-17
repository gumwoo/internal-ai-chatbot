"""MOD-05/06/11 테스트 공용 fixture. 과금 없음.

- 실제 수령 PDF 일부를 읽기만 한다(원본은 바꾸지 않는다).
- manifest는 MOD-06 초안 생성기로 만든 뒤, **시험 전용으로** review_status=reviewed와 available_from(시행일
  00:00 KST)을 채운다. 이 값은 실제 검수 결과가 아니다(O-02, P-15 미정).
- 임베딩은 글자 2-gram 해시로 만든 결정적 벡터다. 글자가 겹치면 가깝다. 의미 유사도는 없다.
"""

import hashlib
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from agent.app.corpus_ops import INPUT_ROOT, REGISTER_PATH
from agent.modules.ingestion.manifest import draft_entry, kst_midnight, link_supersession, parse_register
from agent.modules.ingestion.parser import parse_pdf, sha256_of
from agent.modules.model_integration.ports import EmbeddingBatch, EmbeddingConfig, Usage

# 시험 대상: 개정 쌍(ED-030/031, GA-081/082), FAQ(GA-090), 표가 페이지를 넘는 IT-037,
# 제한 문서(HR-013, CM-093)
TEST_FILES = ("PDF-013", "PDF-030", "PDF-031", "PDF-037", "PDF-081", "PDF-082", "PDF-090", "PDF-093")

_PARSED: dict[str, Any] = {}
_PREPARED: dict[tuple, Any] = {}


async def prepared_corpus(
    reviewed: bool = True, source_file_ids: tuple[str, ...] = TEST_FILES, label: str = "test"
):
    """시험 corpus 준비 결과를 프로세스 안에서 재사용한다(파싱·검사가 느리다). 게시는 매번 새로 한다."""
    from agent.app.corpus_ops import prepare_corpus

    key = (reviewed, source_file_ids, label)
    if key not in _PREPARED:
        _PREPARED[key] = await prepare_corpus(
            make_test_manifest(source_file_ids, reviewed),
            BigramEmbedder(),
            source_file_ids=None,
            label=label,
            scope="pilot",
            cache_dir=None,
            embed_per_minute=10**9,
        )
    return _PREPARED[key]


def make_test_manifest(
    source_file_ids: tuple[str, ...] = TEST_FILES, reviewed: bool = True
) -> dict[str, Any]:
    rows = [r for r in parse_register(REGISTER_PATH) if r["source_file_id"] in source_file_ids]
    entries = []
    for row in rows:
        path = INPUT_ROOT / row["filename"]
        if row["filename"] not in _PARSED:
            _PARSED[row["filename"]] = (parse_pdf(path), sha256_of(path))
        document, sha = _PARSED[row["filename"]]
        entry = draft_entry(row, document, sha)
        if reviewed:
            # 시험 전용 값: 실제 검수 결과가 아니다.
            entry["review_status"] = "reviewed"
            start = entry["effective_from"]
            entry["available_from"] = kst_midnight(date.fromisoformat(start))
        entries.append(entry)
    link_supersession(entries)
    return {"manifest_version": 1, "status": "test", "input_root": "data/raw/pdfs", "files": entries}


@dataclass
class BigramEmbedder:
    """글자 2-gram 해시 벡터(차원 dimension). 호출 수·입력 수를 기록한다."""

    calls: int = 0
    inputs: int = 0
    fail_with: Exception | None = None

    async def embed_once(
        self, texts: tuple[str, ...], config: EmbeddingConfig, timeout_s: float
    ) -> EmbeddingBatch:
        if self.fail_with is not None:
            raise self.fail_with
        self.calls += 1
        self.inputs += len(texts)
        return EmbeddingBatch(
            model_id=config.model,
            dimension=config.dimension,
            vectors=tuple(bigram_vector(t, config.dimension) for t in texts),
            usage=Usage(input_tokens=None, output_tokens=None, complete=False),
            input_count=len(texts),
        )


def bigram_vector(text: str, dimension: int) -> tuple[float, ...]:
    # 지시문 접두어("task: ... | query:", "title: ... | text:")는 유사도에서 뺀다.
    body = text.split("| query: ", 1)[-1].split("| text: ", 1)[-1]
    vector = [0.0] * dimension
    compact = "".join(body.split())
    for i in range(len(compact) - 1):
        bucket = int.from_bytes(hashlib.blake2b(compact[i : i + 2].encode(), digest_size=4).digest(), "big")
        vector[bucket % dimension] += 1.0
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    if not any(vector):
        vector[0] = 1.0
        norm = 1.0
    return tuple(v / norm for v in vector)


def pdf_root() -> Path:
    return INPUT_ROOT
