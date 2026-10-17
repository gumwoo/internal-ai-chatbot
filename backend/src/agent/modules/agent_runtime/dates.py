"""사건 날짜의 근원 검증(docs/contracts/02-business-dates.md, 04-field-origins.md).

모델은 search_documents에 사건 날짜와 함께 그 날짜를 말한 사용자 문장 인용(date_quote)을 낸다. 서버는
1. 인용이 이 대화의 본인 사용자 메시지(현재 질문 우선, 그다음 이력)에 정확히 한 번 있는지 확인하고
   Unicode code point 구간을 계산한다(같은 문장이 두 번 나오면 어느 쪽인지 몰라 거절).
2. 인용 안의 날짜 표현을 run 고정 시각 기준으로 정규화한다. 연도가 없으면 사용자 문장의 시제로 정한다
   (D-24, P-05 B: 완료 표현은 지난 가장 가까운 날, 예정 표현은 앞으로 가장 가까운 날, 모호하면 되묻기).
3. 정규화한 날짜를 쓴다. 모델이 낸 as_of_date 값은 그대로 쓰지 않는다(다르면 기록만 남긴다).
검증하지 못하면 날짜 없이 검색하게 해 MOD-11이 되묻기를 돌려준다. 오늘 날짜로 대신하지 않는다.
"""

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

_FULL = re.compile(r"(\d{4})\s*[년.\-/]\s*(\d{1,2})\s*[월.\-/]\s*(\d{1,2})\s*일?")
_MONTH_DAY = re.compile(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일")
_SLASH = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?![\d/])")
_RELATIVE = {"그저께": -2, "그제": -2, "어제": -1, "오늘": 0, "내일": 1, "모레": 2}
_COMPLETED = (
    "시작한", "시작했", "출발한", "출발했", "다녀온", "다녀왔", "돌아온", "돌아왔", "받은", "받았",
    "했던", "갔던", "갔다", "끝난", "끝났", "결재된", "결재했", "처리된", "처리했", "신청한", "신청했",
    "근무한", "근무했", "참석한", "참석했", "수료한", "수료했",
)  # fmt: skip
_PLANNED = (
    "시작하는", "시작할", "시작될", "출발하는", "출발할", "갈 ", "가는", "갈거", "갈 예정", "예정",
    "받을", "신청할", "근무할", "참석할", "참석하는", "결재할", "처리할",
)  # fmt: skip


@dataclass(frozen=True)
class DateOrigin:
    verified: bool
    value: date | None = None
    reason: str | None = None  # missing_date / ambiguous_date (검증 실패 시)
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_field_origin(self) -> dict[str, Any]:
        return {
            "verified": self.verified,
            "date": self.value.isoformat() if self.value else None,
            "reason": self.reason,
            "evidence": self.evidence,
        }


def verify_event_date(
    quote: str | None,
    model_date: date | None,
    current_message: str,
    history_user_messages: tuple[str, ...],
    today: date,
) -> DateOrigin:
    if not quote or not quote.strip():
        return DateOrigin(False, reason="missing_date", evidence={"problem": "no_quote"})
    located = _locate(quote, current_message, history_user_messages)
    if located is None:
        return DateOrigin(False, reason="missing_date", evidence={"problem": "quote_not_in_user_message"})
    message, start = located
    candidates = _dates_in(quote, today, message)
    if not candidates:
        return DateOrigin(False, reason="missing_date", evidence={"problem": "no_date_in_quote"})
    resolved = [c for c in candidates if c[0] is not None]
    if not resolved:
        return DateOrigin(False, reason="ambiguous_date", evidence={"problem": "tense_unclear"})
    # 인용에 날짜가 여럿이면 모델이 고른 날짜와 같은 것을 쓰고, 없으면 첫 날짜를 쓴다.
    chosen = next((c for c in resolved if c[0] == model_date), resolved[0])
    evidence = {
        "source": "user_message",
        "quote": quote,
        "span_start": start,
        "span_end": start + len(quote),
        "year_inferred": chosen[1],
        "normalized": chosen[0].isoformat(),
    }
    if model_date is not None and model_date != chosen[0]:
        evidence["model_date_ignored"] = model_date.isoformat()
    return DateOrigin(True, value=chosen[0], evidence=evidence)


def _locate(quote: str, current: str, history: tuple[str, ...]) -> tuple[str, int] | None:
    for message in (current, *reversed(history)):
        first = message.find(quote)
        if first < 0:
            continue
        if message.find(quote, first + 1) >= 0:
            return None  # 같은 인용이 두 번: 어느 구간인지 정할 수 없다
        return message, first  # Python 문자열 index = code point 위치
    return None


def _dates_in(quote: str, today: date, message: str) -> list[tuple[date | None, bool]]:
    """(날짜, 연도 추론 여부). 연도가 없고 시제가 불명확하면 날짜 자리에 None."""
    out: list[tuple[date | None, bool]] = []
    taken: list[tuple[int, int]] = []
    for match in _FULL.finditer(quote):
        parsed = _safe(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if parsed:
            out.append((parsed, False))
            taken.append(match.span())
    for pattern in (_MONTH_DAY, _SLASH):
        for match in pattern.finditer(quote):
            if any(a <= match.start() < b for a, b in taken):
                continue
            month, day = int(match.group(1)), int(match.group(2))
            if not any(_safe(today.year + k, month, day) for k in (-1, 0, 1)):
                continue  # 없는 달력 날짜(2월 30일 등)는 날짜로 보지 않고 보정하지 않는다
            out.append((_infer_year(month, day, today, message), True))
            taken.append(match.span())
    for word, offset in _RELATIVE.items():
        if word in quote:
            out.append((today + timedelta(days=offset), False))
    return out


def _infer_year(month: int, day: int, today: date, message: str) -> date | None:
    past = next((d for d in (_safe(today.year - k, month, day) for k in (0, 1)) if d and d <= today), None)
    future = next((d for d in (_safe(today.year + k, month, day) for k in (0, 1)) if d and d >= today), None)
    if past is not None and past == future:
        return past
    completed = any(marker in message for marker in _COMPLETED)
    planned = any(marker in message for marker in _PLANNED)
    if completed and not planned:
        return past
    if planned and not completed:
        return future
    return None


def _safe(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None
