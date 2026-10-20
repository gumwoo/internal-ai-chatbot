"""D-69(P-27 B): 영업일 기한 계산. DB·외부 호출 없는 순수 함수.

영업일은 토·일과 아래 공휴일표를 뺀 날이다(IT-038 "평일(공휴일 제외)"). 회사 자체 휴무일은 코퍼스에 없어
넣지 않는다. 공휴일표는 관공서의 공휴일에 관한 규정(대체공휴일 포함)과 정부가 지정한 임시공휴일·선거일을
공개 자료로 옮긴 것이다. 2026-10-20 확인: 공휴일법 개정과 관공서 공휴일 규정 개정(2026-04-28 국무회의)으로
2026년부터 노동절(5/1)·제헌절(7/17)이 공휴일이고 둘 다 대체공휴일 대상이다. 2027년은 한국천문연구원 월력
(설날 2/6~8·대체 2/9, 노동절 대체 5/3, 제헌절 대체 7/19)과 대조했다. 2025-05-01 근로자의 날은 관공서
공휴일은 아니지만 민간 근로자의 법정 유급휴일이라 회사 영업일에서 뺀다.
공식 공고(인사혁신처·관보)와 다르면 이 표를 고치고 CALENDAR_VERSION을 올린다.

계산 규칙:
- after: "기준일부터 N영업일 이내" — 기준일은 세지 않고(민법 제157조 초일 불산입) 다음 영업일을 1로 센다.
- before: "기준일 N영업일 전까지" — 기준일 전날부터 거꾸로 센 N번째 영업일(그날까지).
- nth_of_next_month: "다음 달 N영업일까지" — 기준일이 속한 달의 다음 달 N번째 영업일.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

CALENDAR_VERSION = "kr-public-2025-2027-v2"
CALENDAR_START = date(2025, 1, 1)
CALENDAR_END = date(2027, 12, 31)  # 이 날까지(포함)

Direction = Literal["after", "before", "nth_of_next_month"]

HOLIDAYS: dict[date, str] = {
    # 2025
    date(2025, 1, 1): "신정",
    date(2025, 1, 27): "임시공휴일",
    date(2025, 1, 28): "설날 연휴",
    date(2025, 1, 29): "설날",
    date(2025, 1, 30): "설날 연휴",
    date(2025, 3, 1): "삼일절",
    date(2025, 3, 3): "삼일절 대체공휴일",
    date(2025, 5, 1): "근로자의 날(민간 유급휴일)",
    date(2025, 5, 5): "어린이날·부처님오신날",
    date(2025, 5, 6): "대체공휴일",
    date(2025, 6, 3): "대통령 선거일",
    date(2025, 6, 6): "현충일",
    date(2025, 8, 15): "광복절",
    date(2025, 10, 3): "개천절",
    date(2025, 10, 5): "추석 연휴",
    date(2025, 10, 6): "추석",
    date(2025, 10, 7): "추석 연휴",
    date(2025, 10, 8): "추석 대체공휴일",
    date(2025, 10, 9): "한글날",
    date(2025, 12, 25): "기독탄신일",
    # 2026
    date(2026, 1, 1): "신정",
    date(2026, 2, 16): "설날 연휴",
    date(2026, 2, 17): "설날",
    date(2026, 2, 18): "설날 연휴",
    date(2026, 3, 1): "삼일절",
    date(2026, 3, 2): "삼일절 대체공휴일",
    date(2026, 5, 1): "노동절",
    date(2026, 5, 5): "어린이날",
    date(2026, 5, 24): "부처님오신날",
    date(2026, 5, 25): "부처님오신날 대체공휴일",
    date(2026, 6, 3): "전국동시지방선거일",
    date(2026, 6, 6): "현충일",
    date(2026, 7, 17): "제헌절",
    date(2026, 8, 15): "광복절",
    date(2026, 8, 17): "광복절 대체공휴일",
    date(2026, 9, 24): "추석 연휴",
    date(2026, 9, 25): "추석",
    date(2026, 9, 26): "추석 연휴",
    date(2026, 10, 3): "개천절",
    date(2026, 10, 5): "개천절 대체공휴일",
    date(2026, 10, 9): "한글날",
    date(2026, 12, 25): "기독탄신일",
    # 2027
    date(2027, 1, 1): "신정",
    date(2027, 2, 6): "설날 연휴",
    date(2027, 2, 7): "설날",
    date(2027, 2, 8): "설날 연휴",
    date(2027, 2, 9): "설날 대체공휴일",
    date(2027, 3, 1): "삼일절",
    date(2027, 5, 1): "노동절",
    date(2027, 5, 3): "노동절 대체공휴일",
    date(2027, 5, 5): "어린이날",
    date(2027, 5, 13): "부처님오신날",
    date(2027, 6, 6): "현충일",
    date(2027, 7, 17): "제헌절",
    date(2027, 7, 19): "제헌절 대체공휴일",
    date(2027, 8, 15): "광복절",
    date(2027, 8, 16): "광복절 대체공휴일",
    date(2027, 9, 14): "추석 연휴",
    date(2027, 9, 15): "추석",
    date(2027, 9, 16): "추석 연휴",
    date(2027, 10, 3): "개천절",
    date(2027, 10, 4): "개천절 대체공휴일",
    date(2027, 10, 9): "한글날",
    date(2027, 10, 11): "한글날 대체공휴일",
    date(2027, 12, 25): "기독탄신일",
    date(2027, 12, 27): "기독탄신일 대체공휴일",
}

_RULES = {
    "after": "기준일은 세지 않고 다음 영업일을 1로 센 날(서버 계산 방식, 사내 규정에 적힌 셈 방법 아님)",
    "before": "기준일 전날부터 거꾸로 센 영업일(그날까지)",
    "nth_of_next_month": "기준일이 속한 달의 다음 달 영업일을 1일부터 센 날",
}
_WEEKDAYS = "월화수목금토일"


class OutOfCalendar(ValueError):
    """공휴일표 범위 밖이라 계산하지 않는다. field는 원인이 된 인자(기준일 자체가 밖이면 base_date)."""

    def __init__(self, day: date, field: str) -> None:
        super().__init__(day.isoformat())
        self.field = field


class BeyondMonth(ValueError):
    """다음 달에 그만큼의 영업일이 없다(nth_of_next_month)."""


@dataclass(frozen=True)
class Deadline:
    base_date: date
    business_days: int
    direction: Direction
    deadline: date
    skipped_holidays: tuple[tuple[date, str], ...]  # 센 구간 안에서 건너뛴 공휴일(주말 제외)

    def as_result(self) -> dict:
        return {
            "base_date": self.base_date.isoformat(),
            "business_days": self.business_days,
            "direction": self.direction,
            "deadline": self.deadline.isoformat(),
            "deadline_weekday": _WEEKDAYS[self.deadline.weekday()],
            "counting_rule": _RULES[self.direction],
            "skipped_holidays": [{"date": d.isoformat(), "name": n} for d, n in self.skipped_holidays],
            "calendar_version": CALENDAR_VERSION,
            "calendar_note": (
                "토·일과 법정 공휴일(대체·임시공휴일 포함)을 뺀 영업일 기준이며 "
                "회사 자체 휴무일은 반영하지 않았다"
            ),
        }


def is_business_day(day: date) -> bool:
    _check(day, "base_date")
    return day.weekday() < 5 and day not in HOLIDAYS


def deadline(base: date, business_days: int, direction: Direction) -> Deadline:
    if business_days < 1:
        raise ValueError("business_days must be >= 1")
    _check(base, "base_date")
    if direction == "nth_of_next_month":
        first = date(base.year + (base.month == 12), base.month % 12 + 1, 1)
        day, step = first - timedelta(days=1), 1
    else:
        day, step = base, 1 if direction == "after" else -1
    counted, skipped = 0, []
    while counted < business_days:
        day += timedelta(days=step)
        _check(day, "business_days")  # 기준일은 표 안이지만 셈이 표 밖으로 넘어간다
        if is_business_day(day):
            counted += 1
        elif day.weekday() < 5:  # 평일인데 영업일이 아니다 = 공휴일(주말과 겹친 공휴일은 따로 알리지 않는다)
            skipped.append((day, HOLIDAYS[day]))
    if direction == "nth_of_next_month" and day.month != first.month:
        raise BeyondMonth(day.isoformat())
    return Deadline(base, business_days, direction, day, tuple(sorted(skipped)))


def _check(day: date, field: str) -> None:
    if not CALENDAR_START <= day <= CALENDAR_END:
        raise OutOfCalendar(day, field)
