"""D-69(P-27 B): 영업일 기한 계산(T-15 기한 예시, 과금·DB 없음)."""

from datetime import date, timedelta

import pytest

from agent.modules.tool_execution.business_days import (
    CALENDAR_END,
    CALENDAR_START,
    HOLIDAYS,
    BeyondMonth,
    OutOfCalendar,
    deadline,
    is_business_day,
)


def test_old_trip_settlement_deadline_skips_substitute_holiday_and_hangul_day():
    """외부 검토 R-010: 10/1 복귀 + 10영업일(종전 출장 정산). 10/5 개천절 대체공휴일·10/9 한글날을 뺀다."""
    result = deadline(date(2026, 10, 1), 10, "after")
    assert result.deadline == date(2026, 10, 19)
    assert [d for d, _ in result.skipped_holidays] == [date(2026, 10, 5), date(2026, 10, 9)]
    data = result.as_result()
    assert data["deadline_weekday"] == "월" and "다음 영업일을 1로" in data["counting_rule"]
    assert "회사 자체 휴무일은 반영하지 않았다" in data["calendar_note"]


@pytest.mark.parametrize(
    ("base", "days", "direction", "expected"),
    [
        (date(2026, 10, 1), 7, "after", date(2026, 10, 14)),  # 현행 출장 정산 7영업일
        (date(2026, 9, 23), 2, "after", date(2026, 9, 29)),  # 추석 연휴(9/24~26) 건너뜀
        (date(2026, 10, 3), 1, "after", date(2026, 10, 6)),  # 기준일이 휴일이어도 다음 영업일부터
        (date(2026, 12, 28), 3, "after", date(2026, 12, 31)),
        (date(2026, 12, 31), 1, "after", date(2027, 1, 4)),  # 해 넘김: 1/1 신정·주말
        (date(2026, 11, 16), 5, "before", date(2026, 11, 9)),  # 교육 시작 5영업일 전까지
        (date(2026, 10, 12), 3, "before", date(2026, 10, 6)),  # 거꾸로 셀 때도 10/9·10/5 제외
        (date(2026, 9, 15), 3, "nth_of_next_month", date(2026, 10, 6)),  # 다음 달 3영업일(10/5 대체공휴일)
        (date(2026, 12, 10), 1, "nth_of_next_month", date(2027, 1, 4)),  # 12월 → 다음 해 1월
        (date(2026, 1, 31), 1, "nth_of_next_month", date(2026, 2, 2)),
    ],
)
def test_deadline_rules(base, days, direction, expected):
    assert deadline(base, days, direction).deadline == expected


def test_holidays_on_weekends_are_not_reported_as_skipped():
    """주말과 겹친 공휴일(2026-10-03 토 개천절)은 따로 알리지 않는다(주말이라 원래 세지 않는다)."""
    skipped = deadline(date(2026, 10, 1), 2, "after").skipped_holidays
    assert skipped == ((date(2026, 10, 5), "개천절 대체공휴일"),)


def test_calendar_facts():
    # 2026: 제헌절 복원(금), 지방선거일(수), 대체공휴일 4회(3/2·5/25·8/17·10/5)
    assert not is_business_day(date(2026, 7, 17)) and not is_business_day(date(2026, 6, 3))
    subs = sorted(d for d, name in HOLIDAYS.items() if d.year == 2026 and "대체" in name)
    assert subs == [date(2026, 3, 2), date(2026, 5, 25), date(2026, 8, 17), date(2026, 10, 5)]
    assert is_business_day(date(2026, 6, 8))  # 현충일(토)은 대체공휴일 대상이 아니다
    assert is_business_day(date(2026, 9, 28))  # 추석 연휴의 토요일은 대체공휴일을 만들지 않는다
    assert not is_business_day(date(2026, 10, 17))  # 토요일


def test_out_of_calendar_and_invalid_count():
    with pytest.raises(OutOfCalendar):
        deadline(CALENDAR_START - timedelta(days=1), 1, "after")
    with pytest.raises(OutOfCalendar):
        deadline(CALENDAR_END, 1, "after")  # 계산이 표 밖(2028)으로 넘어간다
    with pytest.raises(ValueError):
        deadline(date(2026, 10, 1), 0, "after")


def test_calendar_facts_found_by_independent_review():
    """독립 검증(2026-10-20, 천문연 월력·관공서 공휴일 규정 개정 보도 대조)에서 고친 날짜."""
    assert not is_business_day(date(2026, 5, 1))  # 노동절(2026년부터 공휴일)
    assert not is_business_day(date(2025, 5, 1))  # 근로자의 날(민간 유급휴일)
    assert is_business_day(date(2027, 2, 5))  # 2027 설날은 2/7, 연휴 2/6~8
    assert not is_business_day(date(2027, 2, 9))  # 설날 대체공휴일
    assert not is_business_day(date(2027, 5, 3))  # 노동절(토) 대체공휴일
    assert not is_business_day(date(2027, 7, 19))  # 제헌절(토) 대체공휴일
    assert deadline(date(2026, 4, 17), 10, "after").deadline == date(2026, 5, 4)


def test_counting_past_the_calendar_or_the_next_month_is_an_error_on_the_right_field():
    with pytest.raises(OutOfCalendar) as base_out:
        deadline(date(2029, 1, 2), 1, "after")
    assert base_out.value.field == "base_date"
    with pytest.raises(OutOfCalendar) as count_out:
        deadline(date(2027, 12, 30), 2, "after")  # 기준일은 표 안, 셈이 2028년으로 넘어간다
    assert count_out.value.field == "business_days"
    with pytest.raises(BeyondMonth):
        deadline(date(2026, 9, 15), 25, "nth_of_next_month")  # 10월에 25번째 영업일은 없다
