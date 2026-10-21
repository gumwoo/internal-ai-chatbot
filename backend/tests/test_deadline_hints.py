"""D-71(P-28 B): 영업일 기한 문장 찾기·기준일 후보·계산표(T-15, 과금·DB 없음).

기한 문장은 코퍼스(data/staging/eval-sources)의 실제 문형이다.
"""

from datetime import date

import pytest

from agent.modules.agent_runtime.dates import deadline_bases
from agent.modules.agent_runtime.deadlines import MAX_RULES, deadline_hints, find_rules

TODAY = date(2026, 10, 16)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("출장자는 복귀일부터 7영업일 이내에 승인번호, 실제 기간을 경비 시스템에 제출한다.", [(7, "after")]),
        ("교육 종료일로부터 10영업일 이내에 수료증·참가확인서를 제출한다.", [(10, "after")]),
        ("확인하고 사실과 다른 경우 통지 후 3영업일 이내 이의를 신청할 수 있다.", [(3, "after")]),
        ("이용자가 복구를 확인하거나 안내 후 2영업일 동안 이의가 없으면", [(2, "after")]),
        (
            "동일 증상과 원인으로 종결 후 5영업일 내 재발하면 기존 티켓 재오픈을 요청할 수 있다.",
            [(5, "after")],
        ),
        ("선택·직무교육의 일반 취소는 교육 시작 2영업일 전까지 교육포털에서 신청한다.", [(2, "before")]),
        ("원칙적으로 출발 2영업일 전 전자결재 승인을 받는다.", [(2, "before")]),
        ("08:00 | 17:00 | 8시간 | 적용 3영업일 전", [(3, "before")]),
        (
            "월별 카드 거래는 사용월 다음 달 3영업일까지 지출목적과 증빙을 소명한다.",
            [(3, "nth_of_next_month")],
        ),
        ("익월 3영업일 | 월별 사용내역 소명", [(3, "nth_of_next_month")]),
        ("그 사실을 안 다음 영업일 종료 전까지 정정 요청을 제출한다.", [(1, "after")]),
        ("일반 교육 취소는 교육 시작 전 영업일까지 담당자에게 요청할 수 있다.", [(1, "before")]),
        ("정산기한 | 복귀 후 10영업일 | 현행 복귀 후 7영업일", [(10, "after"), (7, "after")]),
        ("교육 시작일로부터 5영업일 전까지 신청한다.", [(5, "before")]),  # "부터 … 전"은 거꾸로 세기만
        ("입사일부터 첫 3영업일 동안 교육을 배정한다.", []),  # 기준일을 1일로 세는 표현
        ("결과는 오후 3영업일 안에 알려 준다.", []),  # "오후"는 기준이 아니다
        ("마감일이 휴일이면 다음 영업일까지로 한다.", []),  # 마감 이월 규칙은 기한이 아니다
        ("3영\n업일 전까지 신청한다.", [(3, "before")]),  # PDF 줄바꿈으로 잘린 낱말
        ("복귀일부터\n7영업일 이내에 제출한다.", [(7, "after")]),
    ],
)
def test_business_deadline_rules_in_corpus_sentences(text, expected):
    assert [(n, d) for _, n, d in find_rules(text)] == expected


@pytest.mark.parametrize(
    "text",
    [
        "P1은 접수 확인 후 15분 이내, P2는 1시간 이내, P3는 1영업일 이내에 최초 응답한다.",  # 기준 없는 목표
        "첫 3영업일 | 인사팀 교육담당 | 교육 회차 배정·일정 안내",  # 기준일을 1일로 센다
        "차이가 있는 경우 3영업일 이내 변경 사유를 보고한다.",  # 기준이 없다
        "제7조(시각 및 영업일)",
        "사전 승인(3영업일 → 5영업일), 정산기한(15영업일 → 10영",  # 개정 비교 요약(기준 없음)
    ],
)
def test_rules_without_a_base_are_not_turned_into_dates(text):
    assert find_rules(text) == []


def _days(bases):
    return [d for d, _ in bases]


def test_each_deadline_in_one_sentence_gets_its_own_piece():
    """한 문장에 기한이 둘이면 기한마다 조각을 따로 주고, 앞 조각에 뒤 기한을 섞지 않는다."""
    first, second = find_rules(
        "현행 GA-081은 출장 복귀일부터 7영업일, 현행 ED-030은 교육 종료일부터 10영업일이다."
    )
    assert (first[1], second[1]) == (7, 10)
    assert "ED-030" not in first[0] and "복귀일부터 7영업일" in first[0]


def test_deadline_bases_take_user_dates_in_order_and_skip_ambiguous_years():
    bases = deadline_bases(
        "10월 1일에 돌아왔고 오늘 정산해요", ("11월 3일 교육이 있어요", "어제 말했죠"), TODAY
    )
    assert _days(bases) == [date(2026, 10, 1), TODAY, date(2026, 11, 3)]  # 이력의 "어제"는 기준을 모른다
    assert bases[0][1].startswith("10월 1일에 돌아왔고")  # 모델이 복귀일인지 알 수 있게 문구를 함께 준다
    assert deadline_bases("3월 2일 건이요", (), TODAY) == []  # 오늘 ±90일 창 밖이라 연도를 정하지 못한다
    assert _days(deadline_bases("2025년 3월 2일 건이요", (), TODAY)) == [date(2025, 3, 2)]
    assert len(deadline_bases("10/1, 10/2, 10/5, 10/6, 10/7", (), TODAY)) == 4  # 상한


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        # 독립 검증(2026-10-20)이 재현한 연도·범위·분수 문제
        (
            "1월 5일에 복귀했어요",
            [],
        ),  # 완료인데 지난 1월 5일은 90일 창 밖: 정하지 않는다(2027년으로 읽지 않음)
        ("12월 20일에 다녀왔는데요", [date(2025, 12, 20)]),  # 완료 표지 → 지난 날
        ("11월 3일에 출발할 예정이에요", [date(2026, 11, 3)]),  # 예정 표지 → 다가올 날
        ("10월 1일부터 3일까지 출장 다녀왔어요", [date(2026, 10, 1), date(2026, 10, 3)]),  # 범위 끝도 후보
        ("교육비 1/2 지원되나요? 10/1 출발했어요", [date(2026, 10, 1)]),  # 분수는 날짜가 아니다
    ],
)
def test_deadline_bases_follow_tense_ranges_and_skip_fractions(message, expected):
    assert _days(deadline_bases(message, (), TODAY)) == expected


def test_deadline_hints_compute_each_rule_for_each_base_and_dedupe():
    passages = [
        {
            "citation_id": "c1-1",
            "text": "출장자는 복귀일부터 7영업일 이내에 제출한다. 출발 2영업일 전 결재한다.",
        },
        {
            "citation_id": "c1-2",
            "text": "출장자는 복귀일부터  7영업일 이내에 제출한다.",
        },  # 공백만 다른 같은 문장
    ]
    hints = deadline_hints(
        passages, [(date(2026, 10, 1), "10월 1일 복귀"), (date(2026, 10, 22), "22일 출발")]
    )
    assert [(r["citation_id"], r["business_days"], r["direction"]) for r in hints["rules"]] == [
        ("c1-1", 7, "after"),
        ("c1-1", 2, "before"),
    ]
    after7 = {c["base_date"]: c["deadline"] for c in hints["rules"][0]["computed"]}
    assert after7 == {"2026-10-01": "2026-10-14", "2026-10-22": "2026-11-02"}
    before2 = {c["base_date"]: c["deadline"] for c in hints["rules"][1]["computed"]}
    assert before2 == {"2026-10-01": "2026-09-29", "2026-10-22": "2026-10-20"}
    assert hints["rules"][0]["computed"][0]["base_quote"] == "10월 1일 복귀"
    assert hints["calendar_version"] == "kr-public-2025-2027-v2"


def test_deadline_hints_need_both_a_rule_and_a_base_and_stay_small():
    rule = [{"citation_id": "c1-1", "text": "복귀일부터 7영업일 이내에 제출한다."}]
    assert deadline_hints(rule, []) is None
    assert deadline_hints([{"citation_id": "c1-1", "text": "한도는 15만 원이다."}], [TODAY]) is None
    # 공휴일표 밖 기준일은 계산하지 않는다(그 기준일만 빠지고, 남은 계산이 없으면 그 기한도 빠진다)
    assert deadline_hints(rule, [(date(2029, 1, 2), "2029년 1월 2일")]) is None
    many = [{"citation_id": f"c1-{i}", "text": f"통지 후 {i}영업일 이내 제출한다."} for i in range(1, 12)]
    assert len(deadline_hints(many, [(TODAY, "오늘")])["rules"]) == MAX_RULES


# --- D-83: 기준 사건 짝 맞추기 ---


@pytest.mark.parametrize(
    ("sentence", "event"),
    [
        ("교육운영담당은 교육 종료 후 5영업일 이내에 수료 여부를 확정한다", "end"),
        ("교육 시작 5영업일 전까지 신청한다", "start"),
        ("출장은 출발 2영업일 전까지 전자결재 승인을 받는다", "start"),
        ("사용월 다음 달 3영업일까지 소명한다", "use"),
        ("결과 통지를 받은 날부터 10영업일 이내에 요청할 수 있다", "notice"),
        ("일반 보완 요청의 회신 목표는 요청일부터 5영업일이다", "request"),
    ],
)
def test_rule_event_reads_the_words_right_before_the_number(sentence, event):
    from agent.modules.agent_runtime.deadlines import rule_event

    [(piece, n, direction)] = find_rules(sentence)
    assert rule_event(piece, n, direction) == event


def test_matching_base_is_marked_and_first_and_duration_end_is_added():
    # holdout5 실패 재현: "부터 이틀 동안"의 끝나는 날(13일)이 기준인데 모델이 시작일(12일)로 셌다.
    message = "10월 12일 월요일부터 이틀 동안 사내 집합교육을 듣고 끝났어요. 수료 확정은 며칠까지예요?"
    bases = deadline_bases(message, (), date(2026, 10, 16))
    passage = {"citation_id": "c1-1", "text": "교육 종료 후 5영업일 이내에 확정한다.", "version": "v2"}
    rule = deadline_hints([passage], bases)["rules"][0]
    assert rule["base_event"] == "끝나는 날"
    assert [(c["base_date"], c["deadline"], c["matches_rule"]) for c in rule["computed"]] == [
        ("2026-10-13", "2026-10-20", True),
        ("2026-10-12", "2026-10-19", False),
    ]
    assert "2일째 끝나는 날" in rule["computed"][0]["base_quote"]


def test_no_mark_when_the_user_date_says_no_event():
    bases = deadline_bases("10월 19일 기준으로 알려 주세요", (), date(2026, 10, 16))
    passage = {"citation_id": "c1-1", "text": "교육 종료 후 5영업일 이내에 제출한다.", "version": "v2"}
    rule = deadline_hints([passage], bases)["rules"][0]
    assert all("matches_rule" not in c for c in rule["computed"])  # 판정할 근거가 없으면 모델이 고른다


def test_deadline_date_in_answer_is_matched_without_catching_a_longer_month():
    """D-86: 답에서 계산표 마감일을 찾는 표기. 11월 6일은 1월 6일이 아니다."""
    from agent.modules.agent_runtime.runtime import _date_pattern

    pattern = _date_pattern("2027-01-06")
    assert pattern.search("기한은 2027-01-06입니다")
    assert pattern.search("2027년 1월 6일(수)까지")
    assert pattern.search("1월  6일까지")
    assert not pattern.search("11월 6일까지") and not pattern.search("1월 16일까지")
