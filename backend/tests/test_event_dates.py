# ruff: noqa: F811  (pytest fixture를 다른 시험 모듈에서 가져와 인자로 쓴다)
"""사건 날짜의 근원 검증(T-15 근원 위조, docs/contracts/02-business-dates.md, D-24 시제). 과금 없음."""

from datetime import date

import pytest

from agent.modules.agent_runtime.dates import verify_event_date
from tests.conftest import api_client
from tests.test_document_agent import Capturing, _app, _ask, final, published, tool_turn  # noqa: F401

TODAY = date(2026, 10, 16)


@pytest.mark.parametrize(
    ("quote", "message", "expected", "inferred"),
    [
        ("9월 29일에 시작한", "9월 29일에 시작한 외부교육 한도", date(2026, 9, 29), True),  # 완료 → 지난 날
        ("11월 2일에 시작하는", "11월 2일에 시작하는 교육 한도", date(2026, 11, 2), True),  # 예정 → 다가올 날
        ("10월 2일에 돌아온", "9월 29일에 출발해서 10월 2일에 돌아온 출장", date(2026, 10, 2), True),
        ("2025년 3월 2일", "2025년 3월 2일에 출발한 출장비", date(2025, 3, 2), False),
        ("2025.03.02", "2025.03.02 출장비", date(2025, 3, 2), False),
        ("어제 시작한", "어제 시작한 교육 한도", date(2026, 10, 15), False),
        ("10/20에 시작하는", "10/20에 시작하는 교육", date(2026, 10, 20), True),
        ("10월 16일", "10월 16일 출장비", date(2026, 10, 16), True),  # 오늘과 같은 날짜는 시제 없이도 하나
    ],
)
def test_quote_is_normalized_by_server(quote, message, expected, inferred):
    origin = verify_event_date(quote, None, message, (), TODAY)
    assert origin.verified and origin.value == expected
    assert origin.evidence["year_inferred"] is inferred
    start = origin.evidence["span_start"]
    assert message[start : origin.evidence["span_end"]] == quote


@pytest.mark.parametrize(
    ("quote", "message", "reason", "problem"),
    [
        (None, "외부교육 한도", "missing_date", "no_quote"),
        ("10월 16일", "외부교육 한도", "missing_date", "quote_not_in_user_message"),  # 모델이 오늘을 지어냄
        ("교육", "교육 한도 교육", "missing_date", "quote_not_in_user_message"),  # 두 번 나와 구간을 못 정함
        ("시작한", "시작한 교육 한도", "missing_date", "no_date_in_quote"),
        ("12월 1일", "12월 1일 출장비", "ambiguous_date", "tense_unclear"),  # 지난해 12/1인지 올해 12/1인지
        (
            "2월 30일에 시작한",
            "2월 30일에 시작한 교육",
            "missing_date",
            "no_date_in_quote",
        ),  # 없는 날짜는 보정 안 함
    ],
)
def test_unverifiable_dates_are_not_used(quote, message, reason, problem):
    origin = verify_event_date(quote, date(2026, 10, 16), message, (), TODAY)
    assert not origin.verified and origin.value is None
    assert (origin.reason, origin.evidence.get("problem")) == (reason, problem)


def test_model_date_is_ignored_and_history_message_can_be_the_source():
    origin = verify_event_date(
        "9월 29일에 시작한", date(2026, 10, 16), "그 교육 한도는?", ("9월 29일에 시작한 교육이 있어",), TODAY
    )
    assert origin.verified and origin.value == date(2026, 9, 29)
    assert origin.evidence["model_date_ignored"] == "2026-10-16"


async def test_forged_today_date_without_user_origin_asks_instead(published, migrated):
    """모델이 사용자가 말하지 않은 오늘 날짜를 넣어도 그 날짜로 검색하지 않고 되묻는다."""
    forged = (
        "search_documents",
        {
            "query": "외부교육비 1회 과정 지원 한도",
            "date_basis": "training_start",
            "as_of_date": "2026-10-16",
        },
    )
    model = Capturing([tool_turn(forged), final("한도는 150만 원", citations=["c1-1"])])
    async with api_client(_app(migrated, model)) as client:
        _, response = await _ask(client, "외부교육 한도가 얼마야?")
    data = model.tool_payloads()[0]["data"]
    assert data["resolution"] == "needs_clarification" and data["groups"] == []
    assert response.status_code == 502  # 원장에 없는 인용(c1-1)은 거절


async def test_citation_carries_server_normalized_date_and_year_flag(published, migrated):
    search = (
        "search_documents",
        {
            "query": "외부교육비 1회 과정 지원 한도",
            "date_basis": "training_start",
            "as_of_date": "2026-10-16",  # 모델이 틀린 날짜를 냈다
            "date_quote": "9월 29일에 시작한",
        },
    )
    model = Capturing([tool_turn(search), final("종전 기준", citations=["c1-1"])])
    async with api_client(_app(migrated, model)) as client:
        _, response = await _ask(client, "9월 29일에 시작한 외부교육 한도")
    citation = response.json()["citations"][0]
    assert citation["as_of_date"] == "2026-09-29" and citation["year_inferred"] is True
    assert citation["source_file_id"] == "PDF-031"
    assert model.tool_payloads()[0]["data"]["year_inferred"] is True
