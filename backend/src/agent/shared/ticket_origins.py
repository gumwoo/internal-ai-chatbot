"""티켓 준비 입력의 출처 규칙(docs/contracts/04-field-origins.md). MOD-02가 계산하고 MOD-12가 다시 검증한다.

- 자유문장 필드는 본인 user 메시지의 원문 구간(user_quote) 또는 서버 고정 템플릿만 쓴다.
- 구간은 Unicode code point 기준 [시작, 끝)이다. quote가 그 메시지에 정확히 한 번 있어야 한다.
- 정규화 닫힌 값: identity/trim(자유문장), iso_kst_datetime(발생 시각), canonical_category(분류 enum),
  user_boolean(긴급 여부). 변환은 아래 함수만 쓴다(모델이 낸 값과 서버가 원문에서 만든 값이 같아야 한다).
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from agent.shared.clock import KST

TEMPLATES = {"ticket.subject.generic.v1": ("subject", "IT 지원 요청")}
FREE_TEXT_FIELDS = (
    "subject",
    "description",
    "target_service",
    "impact_scope",
    "urgency_reason",
    "asset_identifier",
)
NORMALIZATIONS = frozenset({"identity", "trim", "iso_kst_datetime", "canonical_category", "user_boolean"})
# 분류 enum은 사용자 원문 구간과 서버 허용 목록의 짝으로만 받는다(모델의 자유 분류 문장은 받지 않음).
CATEGORY_WORDS = {
    "category": {
        "account": ("계정", "로그인", "비밀번호", "잠금", "권한"),
        "network": ("vpn", "네트워크", "인터넷", "와이파이", "wi-fi", "접속"),
        "device": ("노트북", "pc", "컴퓨터", "모니터", "프린터", "기기", "장비", "마우스", "키보드"),
        "software": ("프로그램", "소프트웨어", "설치", "업데이트", "오피스", "메일", "앱"),
        "other": (),
    },
    "request_type": {
        "incident": ("안 돼", "안돼", "안 됩", "안됩", "오류", "에러", "장애", "멈", "끊", "고장", "실패"),
        "service_request": ("신청", "요청", "발급", "설치해", "만들어", "추가해"),
        "inquiry": ("문의", "궁금", "알려", "어떻게"),
    },
}
_TRUE = re.compile(r"긴급|급해|급합|급한|급하게|빨리|당장")
# 부정이 먼저다("안 급해요", "긴급하지는 않아요", "당장은 아니에요", "빨리 안 해도 돼요").
_FALSE = re.compile(
    r"안\s*급|급하지|급하진|긴급하지|긴급하진|긴급\s*아님|급한\s*건\s*아니|당장은?\s*아니|빨리\s*안\s*해도|천천히|여유"
)
_DATE_FULL = re.compile(r"(?<!\d)(\d{4})\s*[년.\-/]\s*(\d{1,2})\s*[월.\-/]\s*(\d{1,2})\s*일?")
_DATE_MD = re.compile(r"(?<!\d)(\d{1,2})\s*월\s*(\d{1,2})\s*일")
_DATE_REL = {"오늘": 0, "어제": -1, "그제": -2, "그저께": -2}
_TIME_HM = re.compile(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)")
_TIME_KO = re.compile(r"(오전|오후|아침|저녁|밤)?\s*(\d{1,2})\s*시(?!간)(?:\s*(\d{1,2})\s*분)?(?:\s*(반))?")


@dataclass(frozen=True)
class FieldOrigin:
    """정규 field_origin. kind=user_quote이면 source_message_id·구간, template이면 template_id."""

    field: str
    kind: str  # user_quote / template / user_input
    normalization: str
    source_message_id: str | None = None
    span_start: int | None = None
    span_end: int | None = None
    template_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


def locate(text: str, quote: str) -> int | None:
    """quote가 text에 정확히 한 번 있으면 code point 시작 위치. 없거나 여러 번이면 None."""
    if not quote:
        return None
    first = text.find(quote)
    if first < 0 or text.find(quote, first + 1) >= 0:
        return None
    return first


def normalize(field: str, normalization: str, quote: str, today: date) -> Any:
    """원문 구간 → 필드 값. 정규화할 수 없으면 ValueError(추정하지 않는다)."""
    if normalization == "identity":
        return quote
    if normalization == "trim":
        return quote.strip()
    if normalization == "iso_kst_datetime":
        return occurred_at(quote, today).isoformat()
    if normalization == "user_boolean":
        if _FALSE.search(quote):
            return False
        if _TRUE.search(quote):
            return True
        raise ValueError("긴급 여부를 원문에서 알 수 없다")
    if normalization == "canonical_category":
        lowered = quote.lower()
        matches = [
            value for value, words in CATEGORY_WORDS[field].items() if any(w in lowered for w in words)
        ]
        if len(matches) != 1:
            raise ValueError("분류를 원문에서 하나로 정할 수 없다")
        return matches[0]
    raise ValueError(f"허용되지 않은 정규화: {normalization}")


def allowed_normalizations(field: str) -> frozenset[str]:
    if field in FREE_TEXT_FIELDS:
        return frozenset({"identity", "trim"})
    if field == "occurred_at":
        return frozenset({"iso_kst_datetime"})
    if field in ("category", "request_type"):
        return frozenset({"canonical_category"})
    if field == "urgent_work":
        return frozenset({"user_boolean"})
    return frozenset()


def occurred_at(quote: str, today: date) -> datetime:
    """ "오늘 오전 9시 30분", "10월 17일 14:10"처럼 날짜와 시각이 함께 있어야 한다. 발생 시각은 과거다.

    연도가 없으면 오늘 이전의 가장 가까운 날, 시각만 있으면 거절(날짜 추정 금지). 모호하면 ValueError.
    """
    day = None
    if (full := _DATE_FULL.search(quote)) is not None:
        day = date(int(full.group(1)), int(full.group(2)), int(full.group(3)))
    elif (md := _DATE_MD.search(quote)) is not None:
        month, dom = int(md.group(1)), int(md.group(2))
        for year in (today.year, today.year - 1):
            try:
                candidate = date(year, month, dom)
            except ValueError:
                continue
            if candidate <= today:
                day = candidate
                break
    else:
        words = [w for w in _DATE_REL if w in quote]
        if len(words) == 1:
            day = today + timedelta(days=_DATE_REL[words[0]])
    if day is None:
        raise ValueError("발생 날짜를 원문에서 알 수 없다")
    if day > today:
        raise ValueError("발생 날짜가 미래다")
    clock = _clock(quote)
    if clock is None:
        raise ValueError("발생 시각을 원문에서 알 수 없다")
    moment = datetime.combine(day, clock, tzinfo=KST)
    return moment


def _clock(quote: str) -> time | None:
    if (hm := _TIME_HM.search(quote)) is not None:
        return time(int(hm.group(1)), int(hm.group(2)))
    if (ko := _TIME_KO.search(quote)) is None:
        return None
    period, hour, minute, half = ko.group(1), int(ko.group(2)), ko.group(3), ko.group(4)
    if hour > 12 and period:
        return None
    if period == "밤" and hour == 12:
        return None  # 자정은 어느 날의 끝인지 모호하다
    if period in ("오후", "저녁", "밤") and hour < 12:
        hour += 12
    elif period is None and 1 <= hour <= 6:
        return None  # "3시"가 오전인지 오후인지 모른다
    if period in ("오전", "아침") and hour == 12:
        hour = 0
    if hour > 23:
        return None
    return time(hour, 30 if half else int(minute or 0))
