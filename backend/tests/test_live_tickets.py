"""실제 모델 티켓 smoke(M5). 과금된다: `uv run pytest -m live_model -v`로만 돈다(D-41).

모델이 사용자 문장 인용(origin_candidates)으로 접수 초안을 만들고, 말하지 않은 값을 비워 두며,
"등록했다"고 말하지 않는지 본다. 소수 시나리오 확인이며 평가 결과가 아니다.
"""

import json
import os
import tempfile
import time
import uuid
from pathlib import Path

import pytest

from agent.app.main import create_app
from agent.modules.identity_access.service import load_demo_org
from agent.modules.it_support.service import load_support_scopes
from agent.modules.model_integration.anthropic_chat import AnthropicChatModel
from agent.modules.model_integration.fake import FakeModelClient
from agent.shared.clock import FIXTURE_NOW, FixedClock
from agent.shared.settings import Settings
from tests.conftest import api_client, make_settings
from tests.test_live_model import PRICE, RawRecordingClient
from tests.test_tickets import SALES, Switch

pytestmark = pytest.mark.live_model
ORIGIN = "http://localhost:5190"

SCENARIOS = [
    # (이름, 질문, 기대 outcome, 초안이 있어야 하는가, 비어 있어야 하는 필드)
    (
        "T1-VPN 장애 초안",
        "VPN이 안 돼요. 오늘 오전 9시 30분부터 접속이 끊겨요. 접수해 주세요",
        {"action_pending"},
        True,
        ("impact_scope", "asset_identifier"),
    ),
    (
        "T2-정보 부족",
        "노트북이 이상해요. 접수 좀 해주세요",
        {"action_pending", "needs_clarification"},
        None,
        ("occurred_at",),
    ),
    ("T3-내 티켓", "내 IT 티켓 목록 보여줘", {"answered", "no_results"}, False, ()),
]


@pytest.fixture(scope="module")
def live_settings() -> Settings:
    settings = Settings()
    if settings.anthropic_api_key is None:
        pytest.skip("ANTHROPIC_API_KEY가 없어 티켓 smoke를 건너뛴다")
    return settings


def _results_file() -> Path:
    folder = Path(os.environ.get("LIVE_RESULTS_DIR") or Path(tempfile.gettempdir()) / "live-smoke")
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "live-tickets.jsonl"


@pytest.mark.parametrize(
    ("name", "question", "outcomes", "draft", "empty"), SCENARIOS, ids=[s[0] for s in SCENARIOS]
)
async def test_live_ticket_scenario(
    seeded_engine, migrated, live_settings, name, question, outcomes, draft, empty
):
    await load_demo_org(seeded_engine, FIXTURE_NOW)
    await load_support_scopes(seeded_engine)
    raw = RawRecordingClient(live_settings.anthropic_api_key.get_secret_value())
    app = create_app(
        make_settings(database_url=migrated, allowed_origins=ORIGIN, chat_model=live_settings.chat_model),
        current_actor=Switch(SALES),
        clock=FixedClock(),
        chat_model=AnthropicChatModel(api_key=None, client=raw),
        embedding_model=FakeModelClient(),
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
    body = response.json()
    tokens_in = sum(c["usage"]["in"] for c in raw.calls)
    tokens_out = sum(c["usage"]["out"] for c in raw.calls)
    price = PRICE.get(live_settings.chat_model)
    record = {
        "scenario": name,
        "status": response.status_code,
        "outcome": body.get("outcome"),
        "error": (body.get("error") or {}).get("code"),
        "answer": body.get("answer"),
        "action_preview": body.get("action_preview"),
        "model_calls": len(raw.calls),
        "input_tokens": tokens_in,
        "output_tokens": tokens_out,
        "cost_usd": round((tokens_in * price[0] + tokens_out * price[1]) / 1e6, 6) if price else None,
        "elapsed_s": round(time.monotonic() - started, 2),
        "raw_calls": raw.calls,
    }
    with _results_file().open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    assert response.status_code == 200, body
    assert body["outcome"] in outcomes, body
    assert "등록했습니다" not in body["answer"] and "접수했습니다" not in body["answer"]
    preview = body.get("action_preview")
    if draft is True:
        assert preview is not None and preview["status"] == "draft", body
    if draft is False:
        assert preview is None
    if preview is not None:
        assert all(preview[field] is None for field in empty), preview
