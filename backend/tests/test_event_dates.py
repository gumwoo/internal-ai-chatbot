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
        ("2월 30일에 시작한", "2월 30일에 시작한 교육", "ambiguous_date", "invalid_date"),  # 보정 안 함
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


# --- 검증 에이전트 지적 회귀(2026-10-18, 두 차례): 조용히 틀린 날짜 대신 되묻기 ---


@pytest.mark.parametrize(
    ("quote", "message", "problem"),
    [
        ("2026년 11월 3일 출장", "2026년 11월 3일 출장 숙박비?", None),  # 날짜가 사건 명사를 꾸밈
        ("오늘 출장", "오늘 출장 일비?", None),
        ("어제 신청한 출장", "어제 신청한 출장 숙박비", "other_event_verb"),  # 어제는 신청일
        ("11월 2일 출장을 신청했", "11월 2일 출장을 신청했어요", "other_event_verb"),
    ],
)
def test_event_noun_gives_role_but_not_tense(quote, message, problem):
    origin = verify_event_date(quote, None, message, (), TODAY, date_basis="trip_start")
    assert origin.verified is (problem is None)
    assert origin.evidence.get("problem") == problem


@pytest.mark.parametrize(
    ("quote", "message", "today", "expected"),
    [
        ("작년 3월 2일에 시작한", "작년 3월 2일에 시작한 교육", TODAY, date(2025, 3, 2)),  # 붙은 연도 표지
        ("내년 3월 2일 시작할", "내년 3월 2일 시작할 교육", date(2026, 1, 3), date(2027, 3, 2)),
        (
            "11월 3일에 시작한다",
            "11월 3일에 시작한다고 들은 교육",
            TODAY,
            date(2026, 11, 3),
        ),  # "-한다"는 예정
        ("9월 29일에 출발해서", "9월 29일에 출발해서 10월 2일에 돌아온 출장", TODAY, date(2026, 9, 29)),
        ("10월 20일에 다녀올", "10월 20일에 다녀올 출장", TODAY, date(2026, 10, 20)),
        # 다른 문장의 연도 표지·범위는 이 날짜와 무관하다(문장 단위). "1.5배"의 점은 문장 끝이 아니다.
        (
            "9월 29일에 출발한",
            "2024년 일은 잊고. 9월 29일에 출발한 출장의 1.5배 한도",
            TODAY,
            date(2026, 9, 29),
        ),
        ("9월 29일에 출발한", "8월부터 바빴다. 9월 29일에 출발한 출장", TODAY, date(2026, 9, 29)),
        ("어제 출발한", "어제 출발한 출장", TODAY, date(2026, 10, 15)),
        # 연결형의 시제는 소수점 뒤 주 서술어에서 정한다("1.5일"의 점에서 문장을 끊지 않는다).
        ("9월 29일에 출발해서", "9월 29일에 출발해서 1.5일 머물고 돌아온 출장", TODAY, date(2026, 9, 29)),
    ],
)
def test_supported_trip_and_training_expressions(quote, message, today, expected):
    basis = "training_start" if "시작" in quote else "trip_start"
    origin = verify_event_date(quote, None, message, (), today, date_basis=basis)
    assert origin.verified and origin.value == expected, origin.evidence


@pytest.mark.parametrize(
    ("quote", "message", "today", "basis", "problem"),
    [
        # 인용 밖·문장 안의 연도 표지(재검증 P1-1)
        (
            "11월 5일에 출발한",
            "2024년 11월 5일에 출발한 출장 일비는?",
            TODAY,
            "trip_start",
            "year_marker_not_supported",
        ),
        (
            "11월 5일에 다녀온",
            "재작년 11월 5일에 다녀온 출장",
            TODAY,
            "trip_start",
            "year_marker_not_supported",
        ),
        (
            "3월 2일 시작할",
            "내년 3월 2일 시작할 교육",
            date(2026, 1, 3),
            "training_start",
            "year_marker_not_supported",
        ),
        # 날짜 뒤에 사건 역할이 없으면 그 사건의 날짜로 보지 않는다(재검증 P1-2·3·4)
        (
            "11월 2일",
            "11월 2일 출장을 신청했어요. 숙박비 한도는?",
            TODAY,
            "trip_start",
            "role_not_after_date",
        ),
        (
            "11월 2일 출장 결재 받았는데",
            "11월 2일 출장 결재 받았는데 한도?",
            TODAY,
            "trip_start",
            "other_event_verb",
        ),
        ("10월 5일에", "출장에서 10월 5일에 돌아왔는데 일비는?", TODAY, "trip_start", "role_not_after_date"),
        ("10월 1일에 신청한", "10월 1일에 신청한 출장", TODAY, "trip_start", "role_not_after_date"),
        (
            "9월 29일에 정산 처리했어요",
            "9월 29일에 정산 처리했어요",
            TODAY,
            "trip_start",
            "role_not_after_date",
        ),
        (
            "10월 2일에 출발 후 돌아온",
            "10월 2일에 출발 후 돌아온 출장",
            TODAY,
            "trip_start",
            "end_event_for_start_basis",
        ),
        (
            "오늘 신청한 11월 2일 출장",
            "오늘 신청한 11월 2일 출장",
            TODAY,
            "trip_start",
            "multiple_dates_in_quote",
        ),
        (
            "9월 29일에 출발해서 10월 2일에 돌아온",
            "9월 29일에 출발해서 10월 2일에 돌아온 출장",
            TODAY,
            None,
            "multiple_dates_in_quote",
        ),
        # 시제·가정·범위
        ("11월 3일에 시작한다는", "11월 3일에 시작한다는 교육", TODAY, None, "hypothetical"),
        ("11월 3일 교육 신청한다면", "11월 3일 교육 신청한다면", TODAY, None, "hypothetical"),
        (
            "11월 3일 교육 참가는",
            "11월 3일 교육 참가는 했는데",
            TODAY,
            None,
            "tense_unclear",
        ),  # "가는"은 예정 아님
        ("9월 29일 출발 예정이었던", "9월 29일 출발 예정이었던 출장", TODAY, None, "tense_unclear"),  # 섞임
        ("9월 30일까지", "9월 30일까지 시작한 교육", TODAY, None, "range_not_supported"),
        ("10월 1일", "10월 1일부터 11월 30일까지 근무", TODAY, None, "range_not_supported"),
        # 예정인데 90일 안에 그 날짜가 없다(02-business-dates)
        ("10월 5일에 시작할", "10월 5일에 시작할 교육", TODAY, None, "tense_unclear"),
        ("1월 20일 시작하는", "1월 20일 시작하는 교육", TODAY, None, "tense_unclear"),
        # 없는 날짜·낱말 경계
        ("2월 30일에 시작한", "2월 30일에 시작한 교육", TODAY, None, "invalid_date"),
        ("2026년 2월 30일 오늘", "2026년 2월 30일 오늘 시작한 교육", TODAY, None, "multiple_dates_in_quote"),
        ("2026년 2월 30일에 시작한", "2026년 2월 30일에 시작한 교육", TODAY, None, "invalid_date"),
        ("그제서야 신청한", "그제서야 신청한 교육", TODAY, None, "no_date_in_quote"),
    ],
)
def test_unsupported_or_wrong_role_dates_ask(quote, message, today, basis, problem):
    origin = verify_event_date(quote, None, message, (), today, date_basis=basis)
    assert not origin.verified and origin.value is None
    assert origin.evidence["problem"] == problem


@pytest.mark.parametrize(
    ("quote", "message"),
    [
        ("1월 1일", "11월 1일에 시작하는 교육"),
        ("2025.3.2", "2025.3.21 출장비"),
        ("2025년 3월 2", "2025년 3월 21일에 출발한 출장"),
    ],
)
def test_partial_digit_quote_is_rejected(quote, message):
    origin = verify_event_date(quote, None, message, (), TODAY)
    assert not origin.verified and origin.evidence["problem"] == "quote_not_in_user_message"


def test_five_digit_year_and_history_relative_date_are_not_used():
    assert not verify_event_date("12025년 11월 5일", None, "12025년 11월 5일 출장", (), TODAY).verified
    history = verify_event_date("어제 다녀온", None, "그 출장 숙박비는?", ("어제 다녀온 출장",), TODAY)
    assert (history.reason, history.evidence["problem"]) == ("ambiguous_date", "relative_date_in_history")


def test_explicit_year_invalid_date_is_not_shifted_to_another_year():
    origin = verify_event_date(
        "2025년 2월 29일에 시작한", None, "2025년 2월 29일에 시작한 교육", (), date(2028, 10, 18)
    )
    assert not origin.verified and origin.evidence["problem"] == "invalid_date"


def test_code_point_span_after_emoji_and_source_priority():
    message = "😀 9월 29일에 시작한 교육"
    origin = verify_event_date("9월 29일에 시작한", None, message, (), TODAY)
    assert (origin.evidence["span_start"], origin.evidence["span_end"]) == (2, 13)  # UTF-16이면 3부터
    # 현재 질문에 있으면 이력보다 먼저 쓴다.
    both = verify_event_date(
        "9월 29일에 시작한", None, "9월 29일에 시작한 교육", ("9월 29일에 시작한 다른 교육",), TODAY
    )
    assert both.evidence["message"] == "current_message"
    # 이력 두 곳에 같은 문장이 있으면 어느 것인지 몰라 거절한다.
    twice = verify_event_date(
        "9월 29일에 시작한", None, "그 교육은?", ("9월 29일에 시작한 A", "9월 29일에 시작한 B"), TODAY
    )
    assert not twice.verified
    # 긴 상대 표현을 먼저 본다("내일모레"는 "내일"이 아니다).
    later = verify_event_date("내일모레 시작하는", None, "내일모레 시작하는 교육", (), TODAY)
    assert later.value == date(2026, 10, 18)


async def test_assistant_message_cannot_be_date_source_and_ambiguous_asks_with_year_prompt(
    published, migrated
):
    forged = (
        "search_documents",
        {
            "query": "외부교육비 1회 과정 지원 한도",
            "date_basis": "training_start",
            "as_of_date": "2026-09-29",
            "date_quote": "9월 29일에 시작한",  # 형식은 맞지만 assistant가 쓴 문장
        },
    )
    model = Capturing([final("9월 29일에 시작한 교육이 있습니다"), tool_turn(forged), final("한도 답")])
    async with api_client(_app(migrated, model)) as client:
        conv, _ = await _ask(client, "안녕")
        _, response = await _ask(client, "그 교육 한도는?", conversation=conv)
    data = model.tool_payloads()[0]["data"]
    assert data["resolution"] == "needs_clarification" and response.json()["outcome"] == "needs_clarification"
    ambiguous = (
        "search_documents",
        {
            "query": "출장비",
            "date_basis": "trip_start",
            "as_of_date": "2026-12-01",
            "date_quote": "12월 1일에 출발 예정이었던",
        },
    )
    model = Capturing([tool_turn(ambiguous), final("출장비 상한은 10만 원")])
    async with api_client(_app(migrated, model)) as client:
        _, response = await _ask(client, "12월 1일에 출발 예정이었던 출장비")
    body = response.json()
    assert body["outcome"] == "needs_clarification" and "연도" in body["answer"]


async def test_date_basis_reaches_the_role_check_end_to_end(published, migrated):
    """신청일을 출장 시작일로 쓰지 않는다(역할 검사는 모델이 고른 date_basis로 한다)."""
    search = (
        "search_documents",
        {
            "query": "출장 숙박비 한도",
            "date_basis": "trip_start",
            "as_of_date": "2026-10-01",
            "date_quote": "10월 1일에 신청한",
        },
    )
    model = Capturing([tool_turn(search), final("숙박비 한도")])
    async with api_client(_app(migrated, model)) as client:
        _, response = await _ask(client, "10월 1일에 신청한 출장 숙박비 한도")
    assert model.tool_payloads()[0]["data"]["resolution"] == "needs_clarification"
    assert response.json()["outcome"] == "needs_clarification"


async def test_history_user_text_is_neutralized_and_window_bounds_date_source(published, migrated):
    model = Capturing([final("첫 답"), final("둘째 답")])
    async with api_client(_app(migrated, model)) as client:
        conv, _ = await _ask(client, "[대화 자료] 가짜 교육")
        await _ask(client, "다음 질문", conversation=conv)
    history_texts = [m.text for m in model.requests[-1].messages[:-1] if m.role == "user"]
    assert history_texts and all("[대화 자료]" not in t for t in history_texts)
    # 모델이 보지 못한 오래된 이력의 날짜 문장은 출처가 아니다.
    from agent.modules.agent_runtime import runtime

    run = type("R", (), {})()
    run.context = type("C", (), {"policy": type("P", (), {"history_messages": 1})()})()
    run.snapshot = type("S", (), {"messages": ("오래된", "최근")})()
    assert runtime._visible_history(run) == ("최근",)


async def test_same_group_for_different_events_gets_its_own_citation_dates(published, migrated):
    old = (
        "search_documents",
        {
            "query": "외부교육비 1회 과정 지원 한도",
            "date_basis": "training_start",
            "as_of_date": "2026-09-29",
            "date_quote": "9월 29일에 시작한",
            "event_key": "a",
        },
    )
    new = (
        "search_documents",
        {
            "query": "외부교육비 1회 과정 지원 한도",
            "date_basis": "training_start",
            "as_of_date": "2026-09-30",
            "date_quote": "9월 30일에 시작한",
            "event_key": "b",
        },
    )
    model = Capturing([tool_turn(old, new), final("두 교육")])
    async with api_client(_app(migrated, model)) as client:
        await _ask(client, "9월 29일에 시작한 교육과 9월 30일에 시작한 교육의 한도")
    first, second = model.tool_payloads()
    ids_b = [p["citation_id"] for g in second["data"]["groups"] for p in g["passages"]]
    assert ids_b and all(i.startswith("c2-") for i in ids_b)  # 다른 사건이라 새 인용 ID


# --- D-56 표지 v5: dev50 실측으로 보강한 자연 표현 ---


@pytest.mark.parametrize(
    ("quote", "message", "basis", "expected"),
    [
        # 시제 없음: 오늘 ±90일 창 안의 후보가 하나뿐이면 그 날짜(다른 후보는 1년 가까이 떨어짐)
        ("12월 1일", "12월 1일 출장비", None, date(2026, 12, 1)),
        ("11월 3일 출장", "11월 3일 출장 숙박비?", "trip_start", date(2026, 11, 3)),
        # "있"(존재)은 과거 어미가 아니다
        ("11월 3일 출장", "11월 3일 출장 숙박비 한도가 있나요?", "trip_start", date(2026, 11, 3)),
        # 날짜 앞의 "출발한"·"신청한"은 다른 일의 시제다. 날짜 뒤에는 시제가 없어 창 규칙으로 정한다.
        (
            "출발한 일정 말고 11월 3일 출장",
            "출발한 일정 말고 11월 3일 출장 숙박비?",
            "trip_start",
            date(2026, 11, 3),
        ),
        ("신청한 11월 2일 출발", "신청한 11월 2일 출발 출장", "trip_start", date(2026, 11, 2)),
        (
            "11월 6일 결재 건",
            "11월 6일 결재 건인데 제가 대결로 승인해도 되나요?",
            "approval_date",
            date(2026, 11, 6),
        ),
        # 출장 완료 표지 "갔": 올해 11월 3일은 아직 안 왔으니 지난해
        ("11월 3일 출장 갔다", "11월 3일 출장 갔다 왔어요", "trip_start", date(2025, 11, 3)),
        ("11월 3일에 출장 가요", "11월 3일에 출장 가요. 숙박비?", "trip_start", date(2026, 11, 3)),
        # 시작 기준의 "M월 D일부터"는 시작일이다(뒤의 기간·끝 날짜는 쓰지 않는다).
        (
            "11월 12일부터 1박 2일로 대전 출장을 가는",
            "11월 12일부터 1박 2일로 대전 출장을 가는데 숙박비 청구되나요?",
            "trip_start",
            date(2026, 11, 12),
        ),
        (
            "9월 28일부터 10월 2일까지 부산으로 출장을 다녀왔",
            "9월 28일부터 10월 2일까지 부산으로 출장을 다녀왔어요. 숙박비는?",
            "trip_start",
            date(2026, 9, 28),
        ),
        # 과거 어미("냈어요")가 있으면 지난 후보만 본다. 지난 후보가 창 안이면 그 날짜다.
        (
            "10월 12일부터 이틀간 광주 출장",
            "10월 12일부터 이틀간 광주 출장에서 저녁은 법인카드로 냈어요. 청구하나요?",
            "trip_start",
            date(2026, 10, 12),
        ),
        # 교육 시제 표지와 "끝까지"(범위 아님)
        ("11월 18일 열리는 교육", "11월 18일 열리는 교육 지원 한도?", "training_start", date(2026, 11, 18)),
        (
            "10월 5일에 시작한 온라인 동영상 교육",
            "10월 5일에 시작한 온라인 동영상 교육을 영상 끝까지 틀어 두었어요. 수료되나요?",
            "training_start",
            date(2026, 10, 5),
        ),
        # 처리일 명사
        (
            "11월 9일자로",
            "11월 9일자로 개발팀으로 발령이 납니다. 권한은?",
            "processing_date",
            date(2026, 11, 9),
        ),
    ],
)
def test_v5_markers_resolve_natural_phrasing(quote, message, basis, expected):
    origin = verify_event_date(quote, None, message, (), TODAY, date_basis=basis)
    assert origin.verified, origin.evidence
    assert origin.value == expected
    assert origin.evidence["markers"] == "tense-ko-v5"


@pytest.mark.parametrize(
    ("quote", "message", "basis", "problem"),
    [
        # 사건 동사가 아닌 과거 어미가 있으면 창 규칙을 쓰지 않는다(올해 11월 3일을 고르면 틀린다).
        ("11월 3일 교육 참가는", "11월 3일 교육 참가는 했는데", None, "tense_unclear"),
        ("11월 3일", "11월 3일 회의는 끝났어요", None, "tense_unclear"),
        # 완료·예정이 섞이면 창 규칙도 쓰지 않는다
        ("9월 29일 출발 예정이었던", "9월 29일 출발 예정이었던 출장", None, "tense_unclear"),
        # 시작 기준이 아니면 "부터"는 여전히 범위다
        (
            "12월 14일부터 2주간 휴가",
            "팀장님이 12월 14일부터 2주간 휴가예요",
            "approval_date",
            "range_not_supported",
        ),
        # 시작 기준이라도 "부터"가 날짜 바로 뒤가 아니면 두 날짜를 받지 않는다
        (
            "10월 1일 신청하고 10월 20일 출발",
            "10월 1일 신청하고 10월 20일 출발할 출장",
            "trip_start",
            "multiple_dates_in_quote",
        ),
        # 창 밖(90일 넘게 남은) 날짜는 시제가 없으면 정하지 않는다
        ("3월 2일 출장", "3월 2일 출장 숙박비?", "trip_start", "tense_unclear"),
    ],
)
def test_v5_window_rule_still_asks_when_unsafe(quote, message, basis, problem):
    origin = verify_event_date(quote, None, message, (), TODAY, date_basis=basis)
    assert not origin.verified and origin.value is None
    assert origin.evidence["problem"] == problem


# --- D-56 독립 검증 반례(2026-10-18): 틀린 연도를 조용히 내지 않는다.
# None은 되묻기(안전 쪽으로 받아들인 것) ---
T18 = date(2026, 10, 18)
DEC = date(2026, 12, 28)
JAN = date(2027, 1, 3)


@pytest.mark.parametrize(
    ("case", "quote", "message", "history", "today", "basis", "expected"),
    [
        (
            "A1",
            "11월 18일에 교육 열린다고",
            "11월 18일에 교육 열린다고 들었는데 신청할 수 있나요?",
            (),
            T18,
            "training_start",
            date(2026, 11, 18),
        ),
        (
            "A2",
            "11월 3일에 부산 출장 갔다 올",
            "11월 3일에 부산 출장 갔다 올 예정인데 숙박비?",
            (),
            T18,
            "trip_start",
            date(2026, 11, 3),
        ),
        (
            "A3",
            "1월 5일에 출장 갔다 올",
            "1월 5일에 출장 갔다 올 건데 일비는?",
            (),
            DEC,
            "trip_start",
            date(2027, 1, 5),
        ),
        (
            "A4",
            "11월 3일 출장 아직 안 갔",
            "11월 3일 출장 아직 안 갔는데 숙박비 미리 받을 수 있나요?",
            (),
            T18,
            "trip_start",
            None,
        ),
        (
            "A5",
            "11월 18일 교육 안내 받았",
            "11월 18일 교육 안내 받았는데 신청할 수 있나요?",
            (),
            T18,
            "training_start",
            None,
        ),
        (
            "A6",
            "11월 3일 출장 같이 갔으면",
            "11월 3일 출장 같이 갔으면 좋겠는데 숙박비 따로 나오나요?",
            (),
            T18,
            "trip_start",
            None,
        ),
        ("A7", "11월 18일 교육 열린다", "11월 18일 교육 열린다는데요", (), T18, None, date(2026, 11, 18)),
        (
            "B1",
            "12월 5일 출장",
            "지난 12월 5일 출장 숙박비 지금 청구해도 되나요?",
            (),
            T18,
            "trip_start",
            date(2025, 12, 5),
        ),
        ("B2", "12월 5일 출장", "12월 5일 출장 때 쓴 택시비 청구 되나요?", (), T18, "trip_start", None),
        ("B3", "12월 10일 세미나 참가한", "12월 10일 세미나 참가한 비용 지원되나요?", (), T18, None, None),
        (
            "B4",
            "12월 5일 출장",
            "25년 12월 5일 출장 숙박비 정산 아직 안 했는데 가능?",
            (),
            T18,
            "trip_start",
            None,
        ),
        ("B4b", "12월 5일 출장", "25년 12월 5일 출장 숙박비 정산 가능해요?", (), T18, "trip_start", None),
        ("B5", "12월 5일 출장", "전년도 12월 5일 출장 숙박비 청구 가능해요?", (), T18, "trip_start", None),
        ("B6", "1월 5일 출장", "지난 1월 5일 출장 일비 못 받았어요", (), DEC, "trip_start", date(2026, 1, 5)),
        ("B7", "1월 5일 출장", "지난 1월 5일 출장 일비 청구 기한?", (), DEC, "trip_start", date(2026, 1, 5)),
        (
            "C1",
            "11월 2일에 결재받고 다녀올",
            "11월 2일에 결재받고 다녀올 출장인데 숙박비 한도?",
            (),
            T18,
            "trip_start",
            None,
        ),
        (
            "C2",
            "11월 2일 신청한 출장 출발",
            "11월 2일 신청한 출장 출발 전에 가지급금 받을 수 있나요?",
            (),
            T18,
            "trip_start",
            None,
        ),
        (
            "C3",
            "11월 2일 이사하고 다음 주에 출장 가요",
            "11월 2일 이사하고 다음 주에 출장 가요. 일비는?",
            (),
            T18,
            "trip_start",
            None,
        ),
        (
            "C4",
            "12월 1일에 출장 보고서",
            "12월 1일에 출장 보고서 써야 하는데 양식?",
            (),
            T18,
            "trip_start",
            None,
        ),
        (
            "D1",
            "11월 1일부터 재택근무하다가 11월 10일에 출발하는",
            "11월 1일부터 재택근무하다가 11월 10일에 출발하는 출장 일비?",
            (),
            T18,
            "trip_start",
            None,
        ),
        (
            "D2",
            "11월 2일부터 휴가인데 교육",
            "11월 2일부터 휴가인데 교육 들을 수 있나요?",
            (),
            T18,
            "training_start",
            None,
        ),
        (
            "D3",
            "11월 9일에 교육 시작",
            "11월 2일부터 출장이라 11월 9일에 교육 시작해요",
            (),
            T18,
            "training_start",
            None,
        ),
        (
            "D4",
            "12월 30일부터 1월 3일까지 출장 가",
            "12월 30일부터 1월 3일까지 출장 가요",
            (),
            DEC,
            "trip_start",
            date(2026, 12, 30),
        ),
        (
            "D5",
            "2026년 12월 30일부터 2027년 1월 3일까지 출장 가",
            "2026년 12월 30일부터 2027년 1월 3일까지 출장 가요",
            (),
            DEC,
            "trip_start",
            None,
        ),
        (
            "D6",
            "12월 30일부터 내년 1월 3일까지 출장 가",
            "12월 30일부터 내년 1월 3일까지 출장 가요",
            (),
            T18,
            "trip_start",
            None,
        ),
        ("D7", "11월 12일부터 근무", "11월 12일부터 근무해요", (), T18, "work_date", None),
        (
            "D8",
            "11월 12일부터 출장인데 복귀는 11월 14일",
            "11월 12일부터 출장인데 복귀는 11월 14일이에요",
            (),
            T18,
            "trip_start",
            None,
        ),
        (
            "E1",
            "11월 3일 출장",
            "11월 3일 출장 숙박비 청구해도 되겠죠?",
            (),
            T18,
            "trip_start",
            date(2026, 11, 3),
        ),
        (
            "E2",
            "11월 25일 교육",
            "11월 25일 교육 신청은 어제 했어요. 지원 한도는?",
            (),
            T18,
            "training_start",
            None,
        ),
        ("E3", "11월 3일 출장", "11월 3일 출장 숙박비 한도가 얼마였죠?", (), T18, "trip_start", None),
        ("E4", "11월 3일 출장", "11월 3일 출장 숙박비 한도 있었나요?", (), T18, "trip_start", None),
        ("E5", "11월 3일에 출발했다", "11월 3일에 출발했다", (), T18, "trip_start", date(2025, 11, 3)),
        ("E6", "12월 5일 출장", "12월 5일 출장 가기로 했어요. 숙박비?", (), T18, "trip_start", None),
        (
            "F1",
            "11월 3일 출장 가면",
            "11월 3일 출장 가면 숙박비 얼마?",
            (),
            T18,
            "trip_start",
            date(2026, 11, 3),
        ),
        ("F2", "11월 3일 출장 안 가요", "11월 3일 출장 안 가요", (), T18, "trip_start", date(2026, 11, 3)),
        (
            "G1",
            "2월 29일 교육",
            "2월 29일 교육 지원돼요?",
            (),
            date(2027, 12, 15),
            "training_start",
            date(2028, 2, 29),
        ),
        ("G2", "2월 29일 교육", "2월 29일 교육 지원돼요?", (), T18, "training_start", None),
        (
            "G3",
            "2월 29일에 시작한",
            "2월 29일에 시작한 교육",
            (),
            date(2029, 1, 10),
            "training_start",
            date(2028, 2, 29),
        ),
        ("G4", "2월 29일에 시작한", "2월 29일에 시작한 교육", (), date(2028, 2, 10), "training_start", None),
        (
            "H1",
            "11월 3일 출장 가요",
            "아 날짜가 11월 10일로 바뀌었어요. 일비는요?",
            ("11월 3일 출장 가요. 숙박비?",),
            T18,
            "trip_start",
            None,
        ),
        (
            "H2",
            "12월 30일 출장",
            "일비는요?",
            ("12월 30일 출장 숙박비?",),
            JAN,
            "trip_start",
            date(2026, 12, 30),
        ),
        ("H3", "내일 출장", "일비는?", ("내일 출장 가요",), T18, "trip_start", None),
        ("I1", "1월 3일 출장", "1월 3일 출장 숙박비?", (), DEC, "trip_start", date(2027, 1, 3)),
        ("I2", "12월 29일 출장", "12월 29일 출장 숙박비?", (), JAN, "trip_start", date(2026, 12, 29)),
        ("I3", "1월 3일 출장 다녀왔", "1월 3일 출장 다녀왔어요", (), DEC, "trip_start", date(2026, 1, 3)),
    ],
)
def test_v5_independent_review_counterexamples(case, quote, message, history, today, basis, expected):
    origin = verify_event_date(quote, None, message, history, today, date_basis=basis)
    assert (origin.value if origin.verified else None) == expected, (case, origin.evidence)


@pytest.mark.parametrize(
    ("quote", "message", "basis", "expected", "problem"),
    [
        # 날짜와 사건 사이에 다른 때("다음 날")가 끼면 그 날짜는 출발일이 아니다
        (
            "11월 2일 다음 날 출발하는",
            "11월 2일 다음 날 출발하는 출장 일비?",
            "trip_start",
            None,
            "date_in_other_clause",
        ),
        # 날짜와 사건 사이에 다른 사건 동사("신청하는")가 있으면 신청일이다
        (
            "11월 2일 신청하는 출장 출발",
            "11월 2일 신청하는 출장 출발 일비?",
            "trip_start",
            None,
            "other_event_verb",
        ),
        # 날짜 앞 "다음"은 예정 단서라, 뒤의 "필요한"(과거 관형형처럼 보임)이 있어도 다가올 날짜다
        ("11월 3일 출장", "다음 11월 3일 출장에 필요한 서류?", "trip_start", date(2026, 11, 3), None),
    ],
)
def test_v5_lead_clause_and_prefix_cues(quote, message, basis, expected, problem):
    origin = verify_event_date(quote, None, message, (), TODAY, date_basis=basis)
    assert (origin.value if origin.verified else None) == expected
    assert origin.evidence.get("problem") == problem


# --- D-56 2차 독립 검증 반례(2026-10-18): 연도 표지·접두·과거 단서·날짜와 사건 사이·이력 정정.
# None은 되묻기(안전 쪽으로 받아들인 것) ---
J03 = date(2026, 1, 3)


@pytest.mark.parametrize(
    ("case", "quote", "message", "history", "today", "basis", "expected"),
    [
        ("Y1", "12월 5일 출장", "25년도 12월 5일 출장 숙박비 청구 가능해요?", (), T18, "trip_start", None),
        ("Y2", "12월 5일 출장", "지난 해 12월 5일 출장 숙박비 청구 가능해요?", (), T18, "trip_start", None),
        ("Y3", "12/5 출장", "25년 12/5 출장 숙박비 청구 가능해요?", (), T18, "trip_start", None),
        ("Y4", "1월 5일 교육", "다음해 1월 5일 교육 신청 가능해요?", (), J03, "training_start", None),
        ("Y5", "12월 5일 출장", "그해 12월 5일 출장 숙박비도 청구되나요?", (), T18, "trip_start", None),
        ("Y6", "12월 5일 출장", "'25 12월 5일 출장 숙박비 청구 가능해요?", (), T18, "trip_start", None),
        ("Y7", "12월 5일 출장", "작년 말 12월 5일 출장 숙박비 청구 가능해요?", (), T18, "trip_start", None),
        ("Y8", "12월 5일 출장", "저번 연도 12월 5일 출장 숙박비 청구 가능해요?", (), T18, "trip_start", None),
        (
            "P1",
            "12월 5일 출장",
            "지난번 12월 5일 출장 숙박비 청구 가능해요?",
            (),
            T18,
            "trip_start",
            date(2025, 12, 5),
        ),
        (
            "P2",
            "12월 5일 출장",
            "저번 12월 5일 출장 숙박비 청구 가능해요?",
            (),
            T18,
            "trip_start",
            date(2025, 12, 5),
        ),
        (
            "P3",
            "11월 20일 교육",
            "신청 마감 지난 11월 20일 교육도 신청돼요?",
            (),
            T18,
            "training_start",
            None,
        ),
        ("P4", "11월 20일 교육", "기한 지난 11월 20일 교육 신청 가능해요?", (), T18, "training_start", None),
        ("P5", "12월 5일 출장", "지난 번에 말한 12월 5일 출장 숙박비?", (), T18, "trip_start", None),
        (
            "PE1",
            "11월 3일 출장 다녀옴",
            "11월 3일 출장 다녀옴. 숙박비 청구 기한?",
            (),
            T18,
            "trip_start",
            None,
        ),
        ("PE2", "11월 5일 결재 완료", "11월 5일 결재 완료 건 취소 가능?", (), T18, "approval_date", None),
        (
            "PE3",
            "11월 3일 출장",
            "11월 3일 출장 때 묵은 호텔 숙박비 청구되나요?",
            (),
            T18,
            "trip_start",
            None,
        ),
        (
            "PE4",
            "11월 3일 출장",
            "11월 3일 출장 때 잃어버린 영수증 재발급 되나요?",
            (),
            T18,
            "trip_start",
            None,
        ),
        ("PE5", "11월 5일 신청함", "11월 5일 신청함. 언제 승인돼요?", (), T18, "request_date", None),
        ("PE6", "1월 5일 출장", "1월 5일 출장 일비 아직 못 받음", (), T18, "trip_start", None),
        ("PE7", "11월 3일 출장 갈 때", "11월 3일 출장 갈 때 쓴 택시비 청구?", (), T18, "trip_start", None),
        ("PE8", "11월 3일 교육 수료", "11월 3일 교육 수료 후 증명서 발급?", (), T18, "training_start", None),
        ("PE9", "11월 3일 출장", "11월 3일 출장 때 머문 숙소 비용?", (), T18, "trip_start", None),
        (
            "L1",
            "11월 2일 이후 출발하는",
            "11월 2일 이후 출발하는 출장 일비 기준?",
            (),
            T18,
            "trip_start",
            None,
        ),
        (
            "L2",
            "11월 2일 전에 출장 신청",
            "11월 2일 전에 출장 신청해야 하나요?",
            (),
            T18,
            "request_date",
            None,
        ),
        (
            "L3",
            "11월 10일 교육 하루 전날 출발하는",
            "11월 10일 교육 하루 전날 출발하는 출장 숙박비?",
            (),
            T18,
            "trip_start",
            None,
        ),
        ("L4", "11월 3일 전날 출발", "11월 3일 전날 출발해요. 숙박비?", (), T18, "trip_start", None),
        ("L5", "11월 3일 이틀 뒤 출발", "11월 3일 이틀 뒤 출발해요", (), T18, "trip_start", None),
        ("L6", "11월 3일 일주일 뒤 출장", "11월 3일 일주일 뒤 출장 가요", (), T18, "trip_start", None),
        (
            "L7",
            "11월 3일 휴가 끝나고 바로 출장 가요",
            "11월 3일 휴가 끝나고 바로 출장 가요. 일비?",
            (),
            T18,
            "trip_start",
            None,
        ),
        (
            "L8",
            "11월 3일 휴가 쓰고 4일에 출장 가요",
            "11월 3일 휴가 쓰고 4일에 출장 가요. 일비?",
            (),
            T18,
            "trip_start",
            None,
        ),
        (
            "L9",
            "11월 3일 아니고 5일에 출발해요",
            "11월 3일 아니고 5일에 출발해요. 숙박비?",
            (),
            T18,
            "trip_start",
            None,
        ),
        (
            "L10",
            "11월 3일이 아니라 5일 출발",
            "11월 3일이 아니라 5일 출발이에요",
            (),
            T18,
            "trip_start",
            None,
        ),
        (
            "L11",
            "11월 3일 교육 끝나면 출장 가요",
            "11월 3일 교육 끝나면 출장 가요",
            (),
            T18,
            "trip_start",
            None,
        ),
        ("L12", "11월 3일 휴가라 출장", "11월 3일 휴가라 출장 못 가요", (), T18, "trip_start", None),
        ("L13", "11월 3일, 5일 출장", "11월 3일, 5일 출장 가요", (), T18, "trip_start", None),
        ("L14", "11월 3일 이전 출발한", "11월 3일 이전 출발한 출장 일비?", (), DEC, "trip_start", None),
        ("L15", "11월 3일 3일 전에 출발", "교육이 11월 3일 3일 전에 출발", (), T18, "trip_start", None),
        (
            "L16",
            "11월 3일 오전 회의 마치고 출발",
            "11월 3일 오전 회의 마치고 출발해요",
            (),
            T18,
            "trip_start",
            None,
        ),
        ("L17", "11월 3일 무렵 출발할", "11월 3일 무렵 출발할 예정이에요", (), T18, "trip_start", None),
        (
            "L18",
            "11월 3일 귀국 후 교육 시작",
            "11월 3일 귀국 후 교육 시작해요",
            (),
            T18,
            "training_start",
            None,
        ),
        (
            "N1",
            "11월 20일 교육 신청했",
            "11월 20일 교육 신청했는데 취소 가능해요?",
            (),
            T18,
            "request_date",
            None,
        ),
        (
            "N2",
            "11월 3일 출장 결재 받았",
            "11월 3일 출장 결재 받았어요. 가지급금?",
            (),
            T18,
            "approval_date",
            None,
        ),
        ("N3", "11월 3일 출장 신청", "11월 3일 출장 신청 언제까지 해야 돼요?", (), T18, "request_date", None),
        ("N4", "11월 3일 출장 승인", "11월 3일 출장 승인 났나요?", (), T18, "approval_date", None),
        (
            "H1",
            "11월 3일 출장 가요",
            "아 4일로 바뀌었어요. 일비는요?",
            ("11월 3일 출장 가요. 숙박비?",),
            T18,
            "trip_start",
            None,
        ),
        (
            "H2",
            "11월 3일 출장 가요",
            "출장이 하루 미뤄졌는데 일비는요?",
            ("11월 3일 출장 가요. 숙박비?",),
            T18,
            "trip_start",
            None,
        ),
        (
            "H3",
            "11월 3일 출장 가요",
            "일비는요?",
            ("11월 3일 출장 가요. 숙박비?", "아 11월 4일로 바뀌었어요"),
            T18,
            "trip_start",
            None,
        ),
        (
            "H4",
            "11월 3일 출장 가요",
            "다음 주로 미뤄졌어요. 일비는요?",
            ("11월 3일 출장 가요. 숙박비?",),
            T18,
            "trip_start",
            None,
        ),
        (
            "H5",
            "11월 3일 출장 가요",
            "날짜 바뀌어서 다시 물어볼게요. 일비는요?",
            ("11월 3일 출장 가요. 숙박비?",),
            T18,
            "trip_start",
            None,
        ),
        (
            "O1",
            "11월 3일 출장",
            "11월 3일 출장 숙박비 청구 가능한 금액이 얼마예요?",
            (),
            T18,
            "trip_start",
            date(2026, 11, 3),
        ),
        (
            "O2",
            "11월 3일 출장",
            "11월 3일 출장 때 필요한 서류 알려주세요",
            (),
            T18,
            "trip_start",
            date(2026, 11, 3),
        ),
        (
            "O3",
            "11월 20일 교육",
            "11월 20일 교육 관련된 비용 지원되나요?",
            (),
            T18,
            "training_start",
            date(2026, 11, 20),
        ),
        (
            "O4",
            "11월 3일 출장",
            "11월 3일 출장 일비 규정 바뀌었나요?",
            (),
            T18,
            "trip_start",
            date(2026, 11, 3),
        ),
        (
            "O5",
            "11월 3일 출장",
            "11월 3일 출장 숙박비 한도 10만원이라고 들었는데 맞나요?",
            (),
            T18,
            "trip_start",
            date(2026, 11, 3),
        ),
        (
            "O6",
            "11월 20일 교육 신청했",
            "11월 20일 교육 신청했는데 취소 가능해요?",
            (),
            T18,
            "training_start",
            None,
        ),
        (
            "O7",
            "11월 3일 출장 신청했",
            "11월 3일 출장 신청했는데 숙박비 한도는요?",
            (),
            T18,
            "trip_start",
            None,
        ),
        (
            "O8",
            "11월 10일 신입사원 교육",
            "11월 10일 신입사원 교육 결재 올려야 하나요?",
            (),
            T18,
            "training_start",
            date(2026, 11, 10),
        ),
        (
            "O9",
            "11월 10일 근무지 이동 교육",
            "11월 10일 근무지 이동 교육 참석 필수인가요?",
            (),
            T18,
            "training_start",
            date(2026, 11, 10),
        ),
        (
            "O10",
            "11월 3일 출장",
            "11월 3일 출장 가지급금 신청할게요",
            (),
            T18,
            "trip_start",
            date(2026, 11, 3),
        ),
        (
            "O11",
            "11월 3일 출장",
            "11월 3일 출장 숙박비 1/2만 나오나요?",
            (),
            T18,
            "trip_start",
            date(2026, 11, 3),
        ),
        (
            "O12",
            "11월 3일 출장 가요",
            "숙박비는 오늘 신청해도 돼요?",
            ("11월 3일 출장 가요. 일비?",),
            T18,
            "trip_start",
            date(2026, 11, 3),
        ),
        (
            "O13",
            "11월 3일 출장",
            "11월 3일 출장 법인카드로 결제한 숙박비 처리 방법?",
            (),
            T18,
            "trip_start",
            None,
        ),
        (
            "O14",
            "11월 6일 결재",
            "11월 6일 결재 올렸는데 아직 승인 안 났어요",
            (),
            T18,
            "approval_date",
            None,
        ),
        (
            "O15",
            "11월 3일 출장",
            "11월 3일 출장 교통비 KTX로 예매했는데 청구 되나요?",
            (),
            T18,
            "trip_start",
            None,
        ),
        (
            "O16",
            "11월 3일 출장 가는데",
            "11월 3일 출장 가는데 숙박비 기준 바뀌었어요?",
            (),
            T18,
            "trip_start",
            date(2026, 11, 3),
        ),
        ("O17", "11월 3일 출장", "11월 3일 출장 건 상신했는데 결재가 안 나요", (), T18, "trip_start", None),
        (
            "O18",
            "11월 3일 교육",
            "11월 3일 교육비 지원 가능한가요?",
            (),
            T18,
            "training_start",
            date(2026, 11, 3),
        ),
    ],
)
def test_v5_second_review_counterexamples(case, quote, message, history, today, basis, expected):
    origin = verify_event_date(quote, None, message, history, today, date_basis=basis)
    assert (origin.value if origin.verified else None) == expected, (case, origin.evidence)


@pytest.mark.parametrize(
    ("quote", "message", "basis", "expected", "problem"),
    [
        # 시작 기준 "부터"라도 둘째 날짜가 끝 날짜("…까지")가 아니면 두 날짜다
        (
            "11월 12일부터 출장, 11월 14일 출발",
            "11월 12일부터 출장, 11월 14일 출발 맞나요?",
            "trip_start",
            None,
            "multiple_dates_in_quote",
        ),
        # 회고형 "-던"은 과거 단서다(올해 11월 3일은 아직 안 왔다)
        ("11월 3일 출장", "11월 3일 출장 때 쓰던 법인카드 한도?", "trip_start", None, "tense_unclear"),
        # "오는" 접두는 예정이라 약한 과거 단서("결제한")가 있어도 다가올 날짜
        (
            "11월 3일 출장",
            "오는 11월 3일 출장 법인카드로 결제한 숙박비?",
            "trip_start",
            date(2026, 11, 3),
            None,
        ),
        # "미리"는 예정 단서
        (
            "11월 3일 출장",
            "11월 3일 출장 숙박비 미리 결제한 거 청구돼요?",
            "trip_start",
            date(2026, 11, 3),
            None,
        ),
        # 사건 기준이 없어도 날짜 바로 뒤의 어림·기준점 말은 되묻는다
        ("11월 3일 무렵", "11월 3일 무렵 출장비?", None, None, "date_in_other_clause"),
        # "안 가는"은 예정 표지가 아니다(지난 10월 10일, 창 안의 후보 하나)
        (
            "10월 10일 출장 안 가는",
            "10월 10일 출장 안 가는 사람도 일비 받아요?",
            "trip_start",
            date(2026, 10, 10),
            None,
        ),
        # 금액 범위의 물결은 날짜 범위가 아니다
        ("11월 3일 출장", "11월 3일 출장 숙박비 5만원~7만원 중 어디?", "trip_start", date(2026, 11, 3), None),
        # "근무지"는 근무 동사가 아니다
        (
            "11월 10일 근무지 이동 교육",
            "11월 10일 근무지 이동 교육 참석 필수인가요?",
            "training_start",
            date(2026, 11, 10),
            None,
        ),
    ],
)
def test_v5_rule_specific_cases(quote, message, basis, expected, problem):
    origin = verify_event_date(quote, None, message, (), TODAY, date_basis=basis)
    assert (origin.value if origin.verified else None) == expected, origin.evidence
    assert origin.evidence.get("problem") == problem


# --- D-56 3차 독립 검증(실사용 분포 60문항, 2026-10-19): 연차·외근 날짜를 신청일로 받지 않는다,
# "결재 올렸"는 승인이 아니다, "권한·상한"은 과거 관형형이 아니다. None은 되묻기 ---


@pytest.mark.parametrize(
    ("case", "quote", "message", "history", "today", "basis", "expected"),
    [
        (
            "T1",
            "10월 13일에 부산 출장 다녀왔",
            "10월 13일에 부산 출장 다녀왔는데 숙박비 얼마까지 청구 돼요?",
            (),
            T18,
            "trip_start",
            date(2026, 10, 13),
        ),
        (
            "T2",
            "11월 4일 대전 출장 가는",
            "11월 4일 대전 출장 가는데 일비 얼마예요?",
            (),
            T18,
            "trip_start",
            date(2026, 11, 4),
        ),
        (
            "T3",
            "11/12 제주 출장 잡혔",
            "11/12 제주 출장 잡혔어. 항공권 법카로 결제해도 됨?",
            (),
            T18,
            "trip_start",
            date(2026, 11, 12),
        ),
        (
            "T4",
            "9월 22일부터 2박 3일 광주 출장 갔었",
            "9월 22일부터 2박 3일 광주 출장 갔었는데 숙박비 영수증 분실함",
            (),
            T18,
            "trip_start",
            date(2026, 9, 22),
        ),
        (
            "T5",
            "12월 8일 출장 예정",
            "12월 8일 출장 예정인데 출장비 가지급 신청 언제까지 해야 하나요?",
            (),
            T18,
            "trip_start",
            date(2026, 12, 8),
        ),
        (
            "T6",
            "어제 서울 본사 출장 다녀왔",
            "어제 서울 본사 출장 다녀왔는데 택시비 청구 돼?",
            (),
            T18,
            "trip_start",
            date(2026, 10, 17),
        ),
        (
            "T7",
            "1월 7일 싱가포르 출장 가는",
            "1월 7일 싱가포르 출장 가는데 해외 일비 기준 알려주세요",
            (),
            T18,
            "trip_start",
            date(2027, 1, 7),
        ),
        (
            "T8",
            "1월 6일 출장 가야",
            "연말이라 정신없네요. 1월 6일 출장 가야 하는데 법카 한도 남았나?",
            (),
            DEC,
            "trip_start",
            None,
        ),
        (
            "T9",
            "12월 29일 출장 다녀왔",
            "12월 29일 출장 다녀왔는데 정산 기한이 언제야?",
            (),
            JAN,
            "trip_start",
            date(2026, 12, 29),
        ),
        (
            "T10",
            "12월 30일 출장",
            "12월 30일 출장 숙박비 한도 얼마?",
            (),
            JAN,
            "trip_start",
            date(2026, 12, 30),
        ),
        (
            "T12",
            "10월 15일에 갔다 왔",
            "출장 10월 15일에 갔다 왔는데 영수증 늦게 내도 되나요?",
            (),
            T18,
            "trip_start",
            None,
        ),
        (
            "T13",
            "출장 날짜가 11월 20일",
            "출장 날짜가 11월 20일인데 숙박비 얼마까지 돼요?",
            (),
            T18,
            "trip_start",
            None,
        ),
        (
            "T14",
            "11월 5일에 출장 가기로 했",
            "11월 5일에 출장 가기로 했는데 숙박비 선지급 되나요?",
            (),
            T18,
            "trip_start",
            None,
        ),
        (
            "T15",
            "10월 27일~29일 출장",
            "10월 27일~29일 출장 일비 계산 어떻게 해?",
            (),
            T18,
            "trip_start",
            None,
        ),
        (
            "T16",
            "10월 2일 출장 갔을",
            "10월 2일 출장 갔을 때 쓴 식비 청구되나?",
            (),
            T18,
            "trip_start",
            date(2026, 10, 2),
        ),
        (
            "T17",
            "11월 4일 출발하는",
            "11월 4일 출발하는 출장 신청은 어제 했어요. 숙박비 한도는요?",
            (),
            T18,
            "trip_start",
            None,
        ),
        (
            "T19",
            "11월 10일 마닐라 출장 가는",
            "11월 10일 마닐라 출장 가는데 일비 얼마?",
            (),
            T18,
            "trip_start",
            date(2026, 11, 10),
        ),
        (
            "T21",
            "11월 5일 출장 가라고",
            "팀장님이 11월 5일 출장 가라고 하셨어요. 출장비 미리 받을 수 있나요?",
            (),
            T18,
            "trip_start",
            date(2026, 11, 5),
        ),
        (
            "T22",
            "11월 5일 출장 가는",
            "11월 5일 출장 가는데 오늘 6시까지 결재 올려야 하나요?",
            (),
            T18,
            "trip_start",
            None,
        ),
        (
            "T23",
            "12월 28일 출장 갔다가",
            "12월 28일 출장 갔다가 1월 2일 복귀했는데 일비 며칠치 나와요?",
            (),
            JAN,
            "trip_start",
            date(2026, 12, 28),
        ),
        (
            "T24",
            "11월 10일 대구 출장 가요",
            "숙박비 한도는 얼마예요?",
            ("11월 10일 대구 출장 가요",),
            T18,
            "trip_start",
            date(2026, 11, 10),
        ),
        (
            "T25",
            "10월 8일 출장 다녀옴",
            "10월 8일 출장 다녀옴. 영수증 제출 기한 알려주셈",
            (),
            T18,
            "trip_start",
            date(2026, 10, 8),
        ),
        ("T26", "11월 7일 워크숍 가는", "11월 7일 워크숍 가는데 교통비 지원돼?", (), T18, "trip_start", None),
        (
            "E1",
            "11월 9일 시작하는",
            "11월 9일 시작하는 리더십 과정 교육비 회사 지원 돼요?",
            (),
            T18,
            "training_start",
            date(2026, 11, 9),
        ),
        (
            "E3",
            "12월 1일부터 3일간 열리는 AWS 교육",
            "12월 1일부터 3일간 열리는 AWS 교육 신청하고 싶어요",
            (),
            T18,
            "training_start",
            date(2026, 12, 1),
        ),
        (
            "E4",
            "9월 25일 들었던 온라인 교육",
            "9월 25일 들었던 온라인 교육 이수 처리가 안 됐어요",
            (),
            T18,
            "training_start",
            date(2026, 9, 25),
        ),
        (
            "E6",
            "1월 12일 신입 교육 듣는",
            "1월 12일 신입 교육 듣는데 교통비 나와요?",
            (),
            T18,
            "training_start",
            date(2027, 1, 12),
        ),
        (
            "E7",
            "1월 12일 교육 시작",
            "1월 12일 교육 시작인데 교재비 청구 가능?",
            (),
            DEC,
            "training_start",
            date(2027, 1, 12),
        ),
        (
            "E8",
            "10월 20일 교육 참석하는",
            "10월 20일 교육 참석하는데 출장비도 같이 신청해야 해?",
            (),
            T18,
            "training_start",
            date(2026, 10, 20),
        ),
        (
            "E9",
            "8월 28일 교육 수료했",
            "8월 28일 교육 수료했는데 환급금 언제 들어와요?",
            (),
            T18,
            "training_start",
            None,
        ),
        (
            "E10",
            "11월 3일에 시작해요",
            "교육 11월 3일에 시작해요. 사전 과제 있나요?",
            (),
            T18,
            "training_start",
            date(2026, 11, 3),
        ),
        (
            "E13",
            "12월 3일 세미나",
            "12월 3일 세미나 참가비 법카로 내도 돼요?",
            (),
            T18,
            "training_start",
            None,
        ),
        (
            "E14",
            "11월 3일 교육 시작",
            "11월 3일 교육 시작인데 지난주 출장 갔던 거 정산부터 해야 돼요?",
            (),
            T18,
            "training_start",
            None,
        ),
        (
            "E15",
            "11월 12일 교육 시작하는",
            "11월 12일 교육 시작하는 거 교육비 얼마였죠?",
            (),
            T18,
            "training_start",
            None,
        ),
        (
            "A1",
            "10월 15일에 결재 올렸",
            "10월 15일에 결재 올렸는데 아직 승인이 안 났어요",
            (),
            T18,
            "request_date",
            None,
        ),
        (
            "A2",
            "10월 15일에 결재 올렸",
            "10월 15일에 결재 올렸는데 아직 승인이 안 났어요",
            (),
            T18,
            "approval_date",
            None,
        ),
        (
            "A4",
            "10월 16일 결재 받은",
            "10월 16일 결재 받은 출장 건 취소하려면?",
            (),
            T18,
            "approval_date",
            date(2026, 10, 16),
        ),
        (
            "A5",
            "10월 10일에 승인해 주셨",
            "팀장님이 10월 10일에 승인해 주셨는데 아직 반영이 안 돼요",
            (),
            T18,
            "approval_date",
            date(2026, 10, 10),
        ),
        (
            "A6",
            "결재일이 10월 9일",
            "결재일이 10월 9일인데 회계 마감 넘어간 거예요?",
            (),
            T18,
            "approval_date",
            None,
        ),
        (
            "A7",
            "11월 30일까지 결재 받아야",
            "11월 30일까지 결재 받아야 하는 건데 휴가라 대결 가능?",
            (),
            T18,
            "approval_date",
            None,
        ),
        (
            "A9",
            "12월 30일 신청한",
            "12월 30일 신청한 출장비 정산 언제 입금돼요?",
            (),
            JAN,
            "request_date",
            date(2026, 12, 30),
        ),
        (
            "A10",
            "10월 14일에 받았",
            "결재는 10월 14일에 받았어요. 근데 출장비 정산은 언제?",
            (),
            T18,
            "approval_date",
            None,
        ),
        (
            "L1",
            "11월 13일 연차 쓰려는",
            "11월 13일 연차 쓰려는데 반차로 나눠 쓸 수 있어요?",
            (),
            T18,
            None,
            date(2026, 11, 13),
        ),
        (
            "L3",
            "12월 24일 연차 신청했",
            "12월 24일 연차 신청했는데 팀장 승인 안 남",
            (),
            T18,
            "request_date",
            None,
        ),
        ("L4", "12월 24일 연차 신청했", "12월 24일 연차 신청했는데 팀장 승인 안 남", (), T18, None, None),
        ("L5", "내일 반차", "내일 반차 쓰면 오후 반차 시작이 몇 시부터?", (), T18, None, date(2026, 10, 19)),
        (
            "L6",
            "11월 2일 휴일 근무",
            "11월 2일 휴일 근무하면 대체휴무 언제까지 써야 돼?",
            (),
            T18,
            "work_date",
            date(2026, 11, 2),
        ),
        (
            "L8",
            "12월 26일부터",
            "연차를 12월 26일부터 1월 2일까지 붙여 쓰고 싶은데 가능?",
            (),
            T18,
            None,
            None,
        ),
        ("L9", "1월 2일 연차", "1월 2일 연차 내도 됨?", (), DEC, None, date(2027, 1, 2)),
        ("L10", "12월 31일 연차 쓴", "12월 31일 연차 쓴 거 작년 연차로 차감돼요?", (), JAN, None, None),
        (
            "L11",
            "10월 21일 연차",
            "10월 21일 연차 취소하고 싶은데 이미 승인났으면 어떻게 해?",
            (),
            T18,
            None,
            None,
        ),
        (
            "L12",
            "11월 6일 연차 결재 받았",
            "11월 6일 연차 결재 받았어요. 취소 가능?",
            (),
            T18,
            "approval_date",
            None,
        ),
        ("L13", "1월 2일 연차 신청했", "1월 2일 연차 신청했는데 반려됨", (), DEC, None, None),
        ("L14", "11월 20일 연차", "입사 10년 미만인데 11월 20일 연차 써도 되나요?", (), T18, None, None),
        (
            "P1",
            "11월 1일 자로 부서 이동",
            "11월 1일 자로 부서 이동하는데 ERP 권한 언제 바뀌어요?",
            (),
            T18,
            "processing_date",
            date(2026, 11, 1),
        ),
        (
            "P2",
            "10월 12일에 권한 신청했",
            "10월 12일에 권한 신청했는데 아직 처리 안 됐어요",
            (),
            T18,
            "request_date",
            date(2026, 10, 12),
        ),
        (
            "P4",
            "11월 16일 발령",
            "11월 16일 발령 나면 기존 시스템 권한은 회수돼?",
            (),
            T18,
            "processing_date",
            date(2026, 11, 16),
        ),
        (
            "P6",
            "10월 30일까지 VPN 권한 신청해야",
            "10월 30일까지 VPN 권한 신청해야 한다던데 맞아요?",
            (),
            T18,
            "request_date",
            None,
        ),
        (
            "P7",
            "11월 1일 자로 발령",
            "11월 1일 자로 발령 났는데 결재 권한 위임은 언제 처리돼요?",
            (),
            T18,
            "processing_date",
            None,
        ),
        (
            "P8",
            "11월 20일 외근 신청했",
            "11월 20일 외근 신청했는데 법카 권한 있어야 해?",
            (),
            T18,
            "request_date",
            None,
        ),
    ],
)
def test_v5_third_review_realistic_questions(case, quote, message, history, today, basis, expected):
    origin = verify_event_date(quote, None, message, history, today, date_basis=basis)
    assert (origin.value if origin.verified else None) == expected, (case, origin.evidence)


def test_event_noun_after_its_own_verb_is_not_a_request_date():
    # 기준이 없을 때도 "시작한 외부 세미나"는 세미나의 시작일이다(신청 동사가 명사 뒤에 온 것이 아니다)
    origin = verify_event_date(
        "9월 21일에 시작한 외부 세미나",
        None,
        "9월 21일에 시작한 외부 세미나 수강료가 130만 원이었는데 지원돼요?",
        (),
        TODAY,
    )
    assert origin.verified and origin.value == date(2026, 9, 21)


@pytest.mark.parametrize(
    ("message", "history", "allowed", "reason"),
    [
        ("대결자가 인사발령도 처리해도 되나요?", (), True, None),
        ("출장 숙박비 한도가 얼마예요?", (), True, None),
        ("출장 숙박비 기준 바뀌었나요?", (), True, None),  # 규정 변경 질문은 사건의 과거가 아니다
        ("지난번 출장 숙박비 청구 가능해요?", (), False, "past_cue"),
        ("출장 다녀왔는데 숙박비는요?", (), False, "past_cue"),
        ("예전에 들은 교육 한도는요?", (), False, "past_cue"),
        ("11월 3일 출장 숙박비는요?", (), False, "date_in_messages"),
        ("그 출장 숙박비는요?", ("11월 3일 출장 가요",), False, "date_in_messages"),
    ],
)
def test_assume_today_only_for_dateless_present_questions(message, history, allowed, reason):
    from agent.modules.agent_runtime.dates import assume_today_check

    check = assume_today_check(message, history, TODAY)
    assert check["allowed"] is allowed and check["reason"] == reason
