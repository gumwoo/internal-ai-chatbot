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
