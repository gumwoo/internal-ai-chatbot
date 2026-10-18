"""실제 모델 문서 smoke(💰 Anthropic 과금 + Gemini 무료 티어). `-m live_model`일 때만 돈다.

- 시험 DB에 시험 corpus(8개 PDF)를 실제 Gemini 임베딩으로 게시한다. LIVE_CORPUS=full이면 검수 manifest 100개.
  8개일 때 review_status·available_from은 시험 전용
  값이다(P-15 미정, 실제 검수 아님). 임베딩은 data/staging 캐시를 재사용한다.
- 문구는 보지 않는다. outcome·인용한 원본 파일·핵심 숫자 포함 여부만 확인하고, 호출별 원래 응답을 남긴다.
"""

import json
import os
import tempfile
import time
import uuid
from pathlib import Path

import pytest

from agent.app.corpus_ops import MANIFEST_PATH, STAGING, prepare_corpus
from agent.app.main import create_app
from agent.modules.identity_access.service import IdentityService, load_demo_org
from agent.modules.ingestion.manifest import load_manifest
from agent.modules.knowledge.service import KnowledgeService
from agent.modules.model_integration.anthropic_chat import AnthropicChatModel
from agent.modules.model_integration.gemini_embedding import GeminiEmbeddingModel
from agent.shared.actor import ActorContext
from agent.shared.clock import FIXTURE_NOW, FixedClock
from agent.shared.settings import Settings
from tests.conftest import api_client, make_settings
from tests.knowledge_fixtures import make_test_manifest
from tests.test_live_model import PRICE, RawRecordingClient

pytestmark = pytest.mark.live_model

ORIGIN = "http://localhost:5190"
EMPLOYEE = ActorContext(
    "emp-sales",
    ("dept-sales",),
    ("employee",),
    frozenset({"training.read", "knowledge.search", "ticket.read_own"}),
    1,
    "test_stub",
)

SCENARIOS = [
    # (이름, 질문, 기대 outcome 집합, 인용에 있어야 할 파일, 답에 있어야 할 문자열 중 하나)
    (
        "D1-종전 교육비",
        "9월 29일에 시작한 외부교육의 1회 과정 지원 한도는 얼마야?",
        {"answered"},
        "PDF-031",
        ("100만", "1,000,000"),
    ),
    (
        "D2-현행 교육비",
        "10월 5일에 시작한 외부교육의 1회 과정 지원 한도는 얼마야?",
        {"answered"},
        "PDF-030",
        ("150만", "1,500,000"),
    ),
    ("D3-날짜 없음", "외부교육비 1회 과정 지원 한도가 얼마야?", {"needs_clarification"}, None, ()),
    (
        "D4-종전 출장",
        "9월 29일에 출발해서 10월 2일에 돌아온 출장의 숙박비 한도는?",
        {"answered"},
        "PDF-082",
        (),
    ),
    ("D5-IT 접수", "IT 헬프데스크 티켓을 접수할 때 꼭 적어야 하는 항목이 뭐야?", {"answered"}, "PDF-037", ()),
    (
        "D6-제한 문서",
        "부서 이동할 때 인사 발령 절차가 어떻게 돼?",
        {"answered", "insufficient_evidence"},
        None,
        (),
    ),
]


class FixedActor:
    async def resolve(self, request) -> ActorContext:
        return EMPLOYEE


@pytest.fixture(scope="module")
def live_settings() -> Settings:
    settings = Settings()
    if settings.anthropic_api_key is None or settings.gemini_api_key is None:
        pytest.skip("ANTHROPIC_API_KEY 또는 GEMINI_API_KEY가 없어 문서 smoke를 건너뛴다")
    return settings


@pytest.fixture
async def live_corpus(seeded_engine, live_settings):
    await load_demo_org(seeded_engine, FIXTURE_NOW)
    operator = await IdentityService(seeded_engine, FixedClock()).resolve_operator_actor("ops-admin")
    embedder = GeminiEmbeddingModel(live_settings.gemini_api_key.get_secret_value())
    try:
        # LIVE_CORPUS=full: 검수 manifest 100개(release)로 같은 시나리오를 돌린다(전체 문서 smoke).
        full = os.environ.get("LIVE_CORPUS") == "full"
        corpus, report = await prepare_corpus(
            load_manifest(MANIFEST_PATH) if full else make_test_manifest(),
            embedder,
            source_file_ids=None,
            label="live-full" if full else "live",
            scope="release" if full else "pilot",
            cache_dir=STAGING / "embeddings",
        )
    finally:
        await embedder.aclose()
    await KnowledgeService(seeded_engine, FixedClock()).publish(operator, corpus)
    return report


def _results_file() -> Path:
    folder = Path(os.environ.get("LIVE_RESULTS_DIR") or Path(tempfile.gettempdir()) / "live-smoke")
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "live-documents.jsonl"


@pytest.mark.parametrize(
    ("name", "question", "outcomes", "source", "needles"), SCENARIOS, ids=[s[0] for s in SCENARIOS]
)
async def test_live_document_scenario(
    live_corpus, migrated, live_settings, name, question, outcomes, source, needles
):
    raw = RawRecordingClient(live_settings.anthropic_api_key.get_secret_value())
    embedder = GeminiEmbeddingModel(live_settings.gemini_api_key.get_secret_value())
    app = create_app(
        make_settings(database_url=migrated, allowed_origins=ORIGIN, chat_model=live_settings.chat_model),
        current_actor=FixedActor(),
        clock=FixedClock(),
        chat_model=AnthropicChatModel(api_key=None, client=raw),
        embedding_model=embedder,
    )
    started = time.monotonic()
    try:
        async with api_client(app) as client:
            conv = (await client.post("/api/v1/conversations", json={}, headers={"Origin": ORIGIN})).json()[
                "id"
            ]
            response = await client.post(
                f"/api/v1/conversations/{conv}/messages",
                json={"content": question},
                headers={"Origin": ORIGIN, "Idempotency-Key": str(uuid.uuid4())},
            )
    finally:
        await raw.close()
        await embedder.aclose()
    body = response.json()
    tokens_in = sum(c["usage"]["in"] for c in raw.calls)
    tokens_out = sum(c["usage"]["out"] for c in raw.calls)
    price = PRICE.get(live_settings.chat_model)
    record = {
        "scenario": name,
        "status": response.status_code,
        "outcome": body.get("outcome"),
        "error": (body.get("error") or {}).get("code"),
        "cited_files": sorted({c["source_file_id"] for c in body.get("citations") or []}),
        "answer": body.get("answer"),
        "model_calls": len(raw.calls),
        "input_tokens": tokens_in,
        "output_tokens": tokens_out,
        "cost_usd": round((tokens_in * price[0] + tokens_out * price[1]) / 1e6, 6) if price else None,
        "elapsed_s": round(time.monotonic() - started, 2),
        "raw_calls": raw.calls,
        "embedding_report": live_corpus["embedding"],
    }
    with _results_file().open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    assert response.status_code == 200, body
    assert body["outcome"] in outcomes, body
    if source:
        assert source in record["cited_files"], record["cited_files"]
    if needles:
        assert any(n in body["answer"] for n in needles), body["answer"]
    # 일반 직원 답에는 제한 문서(HR-013·CM-093)가 인용되지 않는다(T-16).
    assert not {"PDF-013", "PDF-093"} & set(record["cited_files"])
