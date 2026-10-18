"""사건 날짜의 근원 검증(docs/contracts/02-business-dates.md, 04-field-origins.md).

모델은 search_documents에 사건 날짜와 함께 그 날짜를 말한 사용자 문장 인용(date_quote)을 낸다. 서버는
1. 인용이 이 대화의 본인 사용자 메시지에 정확히 한 번 있는지 확인하고(현재 질문 우선, 없으면 모델이 본 이력
   창에서 한 곳) Unicode code point 구간을 계산한다. 인용 앞뒤가 숫자·날짜 구분자로 이어지면(숫자 일부만
   인용) 거절한다.
2. 인용 안의 날짜 표현은 정확히 하나여야 한다. 사건 역할과 시제는 **날짜 뒤에 붙은 말**에서만 본다(한국어는
   서술어가 뒤에 온다). "11월 2일 출장을 신청했어요"의 "신청했"은 출장일이 아니라 신청의 시제다.
3. 연도가 없으면 그 시제로 정한다(D-24, P-05 B): 완료 → 오늘 이전의 가장 가까운 날, 예정 → 오늘부터 90일
   안의 가장 가까운 날. "작년·내년 M월 D일"처럼 붙은 연도 표지는 run 고정 시각으로 정한다.
4. 정규화한 날짜를 쓴다. 모델이 낸 as_of_date 값은 쓰지 않는다(다르면 증거에 남긴다).
시제·역할 표지 목록은 O-13 확정 전 임시 목록이다(TENSE_MARKERS_VERSION). 조용히 틀린 날짜보다 되묻기가
낫다. 아래는 모두 되묻는다(검증 실패):
- 문장 안의 떨어진 연도 표지("2024년 … 11월 5일", "재작년 … "), 범위("부터·까지·~"), 가정("-다면")
- 인용 안 날짜가 둘 이상, 없는 달력 날짜, 이력 메시지의 상대 날짜(그 메시지를 보낸 날을 모른다)
- 사건 기준의 역할 표지가 날짜 뒤에 없거나(출장 시작일인데 "출발" 없음), 끝 역할("돌아온·정산")인 경우
- 시제가 없거나 섞인 연도 생략 날짜, 예정인데 90일 안에 그 날짜가 없는 경우
"""

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

TENSE_MARKERS_VERSION = "tense-ko-provisional-v4"  # O-13 확정 전 임시
PLANNED_HORIZON_DAYS = 90  # 02-business-dates: 예정 표현은 이후 90일 이내

_FULL = re.compile(r"(?<!\d)(\d{4})\s*[년.\-/]\s*(\d{1,2})\s*[월.\-/]\s*(\d{1,2})\s*일?")
_YEAR_WORDS = {
    "재작년": -2,
    "작년": -1,
    "지난해": -1,
    "올해": 0,
    "금년": 0,
    "내년": 1,
    "다음 해": 1,
    "후년": 2,
}
_YEAR_MD = re.compile(r"(재작년|작년|지난해|올해|금년|내년|다음 해|후년)\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")
_MONTH_DAY = re.compile(r"(?<!\d)(\d{1,2})\s*월\s*(\d{1,2})\s*일")
_SLASH = re.compile(r"(?<![\d/.])(\d{1,2})/(\d{1,2})(?![\d/.])")
_RELATIVE_DAYS = {"내일모레": 2, "그저께": -2, "그제": -2, "어제": -1, "오늘": 0, "내일": 1, "모레": 2}
# 긴 표현을 먼저 둔다("내일모레"가 "내일"로 읽히지 않게).
# 앞뒤가 다른 낱말로 이어지면("그제서야") 날짜가 아니다.
# 뒤에 붙는 조사 한 글자(은·는·이·가·에·의·도·만)까지만 허용한다.
_RELATIVE = re.compile(
    r"(?<![가-힣])(내일모레|그저께|그제|어제|오늘|내일|모레)(?=$|[^가-힣]|[은는이가에의도만](?![가-힣]))"
)
_YEAR_MARKERS = re.compile(r"재작년|작년|지난해|올해|금년|내년|다음 해|후년|\d{4}\s*년")
_RANGE = re.compile(r"부터|까지|~|∼")
_HYPOTHETICAL = re.compile(r"다면|라면|한다는|는다는")
_STEMS = "시작|출발|신청|상신|처리|결재|승인|근무|출근|참석|수료|종료|접수|제출|요청|개강"
# 완료·예정 표지. "시작한다"는 완료가 아니라 예정이다.
_COMPLETED = re.compile(
    rf"({_STEMS})(한|했|된|됐)(?!다)|다녀온|다녀왔|떠난|떠났|돌아온|돌아왔|받은|받았|갔던|갔다|끝난|끝났|었던|였던"
)
_PLANNED = re.compile(rf"({_STEMS})(하는|할|될|한다|된다)|다녀올|떠날|떠나는|예정|받을")
# "9월 29일에 출발해서 10월 2일에 돌아온"처럼 연결형이면 시제는 문장 뒤쪽 서술어에서 본다.
_DEFERRED = re.compile(rf"(({_STEMS})(해서|하고|하여)|다녀와서|떠나서)\s*$")


@dataclass(frozen=True)
class _Role:
    """사건 기준별 역할. 날짜 뒤에 그 사건의 동사나 명사가 있어야 하고, 시제는 그 사건의 동사에서만 본다."""

    verb: re.Pattern[str]  # 사건 동사 어간("출발")
    noun: re.Pattern[str] | None  # 날짜가 꾸미는 사건 명사("11월 3일 출장")
    completed: re.Pattern[str]
    planned: re.Pattern[str]


def _role(verbs: str, nouns: str | None, completed_extra: str = "", planned_extra: str = "") -> _Role:
    """verbs는 정규 어간("출발|떠나|다녀"), 시제는 어간 + 어미와 따로 준 불규칙 형태로 본다."""
    regular = verbs.split("|")[0] if "떠나" in verbs else verbs  # 떠나·다녀는 불규칙이라 extra로만
    completed = "|".join(filter(None, [rf"({regular})(한|했|된|됐)(?!다)", "었던|였던", completed_extra]))
    planned = "|".join(
        filter(None, [rf"({regular})(하는|할|될|한다|된다)", rf"({regular}) ?예정", planned_extra])
    )
    return _Role(
        re.compile(verbs), re.compile(nouns) if nouns else None, re.compile(completed), re.compile(planned)
    )


_ROLES = {
    "trip_start": _role(
        "출발|떠나|떠난|떠날|떠났|다녀", "출장", "떠난|떠났|다녀온|다녀왔", "떠날|떠나는|다녀올|출장 ?예정"
    ),
    "training_start": _role("시작|개강", "교육|과정|연수", "", "교육 ?예정"),
    "request_date": _role("신청|상신|요청|접수|제출", None),  # 상신 → 신청일(D-40)
    "approval_date": _role("결재|승인", None, "결재 ?받은|결재 ?받았", "결재 ?받을"),
    "processing_date": _role("처리", None),
    "work_date": _role("근무|출근", None),
}
# 다른 사건의 동사. 날짜 뒤에 이것만 있으면("어제 신청한 출장") 그 날짜는 이 사건의 날짜가 아니다.
_ANY_EVENT_VERB = re.compile(
    r"출발|떠나|떠난|떠날|떠났|다녀|시작|개강|신청|상신|요청|접수|제출|결재|승인|처리|근무|출근"
)
_END_ROLE = re.compile(r"돌아온|돌아왔|복귀|귀국|정산|끝난|끝났|마친|종료|마감")
_START_BASES = frozenset({"trip_start", "training_start"})
_SENTENCE_END = re.compile(r"[?!\n]|\.(?!\s*\d)")  # "2026.9.29", "1.5배"의 점은 문장 끝이 아니다


@dataclass(frozen=True)
class DateOrigin:
    verified: bool
    value: date | None = None
    reason: str | None = None  # missing_date / ambiguous_date / basis_mismatch
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_field_origin(self) -> dict[str, Any]:
        return {
            "verified": self.verified,
            "date": self.value.isoformat() if self.value else None,
            "reason": self.reason,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class _Found:
    start: int
    end: int
    kind: str  # full / year_md / month_day / relative
    value: date | None  # 연도가 정해진 날짜(full·year_md·relative). 없는 날짜면 None
    month: int = 0
    day: int = 0


def _fail(reason: str, problem: str) -> DateOrigin:
    return DateOrigin(False, reason=reason, evidence={"problem": problem, "markers": TENSE_MARKERS_VERSION})


def verify_event_date(
    quote: str | None,
    model_date: date | None,
    current_message: str,
    history_user_messages: tuple[str, ...],
    today: date,
    date_basis: str | None = None,
) -> DateOrigin:
    if not quote or not quote.strip():
        return _fail("missing_date", "no_quote")
    located = _locate(quote, current_message, history_user_messages)
    if located is None:
        return _fail("missing_date", "quote_not_in_user_message")
    message, start, source = located
    left, right = _sentence_bounds(message, start, len(quote))
    sentence = message[left:right]
    after = message[start + len(quote) : right]  # 같은 문장에서 인용 뒤
    found = _find_dates(quote, today)
    if not found:
        return _fail("missing_date", "no_date_in_quote")
    if len(found) > 1:
        return _fail("basis_mismatch", "multiple_dates_in_quote")
    item = found[0]
    if item.kind != "month_day" and item.value is None:
        return _fail("ambiguous_date", "invalid_date")
    if item.kind == "relative" and source != "current_message":
        # 이력 메시지의 "어제"는 그 메시지를 보낸 날 기준인데 그 시각을 모른다.
        return _fail("ambiguous_date", "relative_date_in_history")
    if _RANGE.search(sentence):
        return _fail("ambiguous_date", "range_not_supported")
    if item.kind in ("month_day", "relative") and _YEAR_MARKERS.search(sentence):
        return _fail("ambiguous_date", "year_marker_not_supported")
    if item.kind in ("full", "year_md") and len(_YEAR_MARKERS.findall(sentence)) > 1:
        return _fail("ambiguous_date", "year_marker_not_supported")
    tail = quote[item.end :]  # 날짜 뒤에 붙은 말: 역할·시제는 여기서만 본다
    if _HYPOTHETICAL.search(tail + after):
        return _fail("ambiguous_date", "hypothetical")
    role = _ROLES.get(date_basis or "")
    if role is not None:
        own_verb = role.verb.search(tail)
        if not own_verb and not (role.noun and role.noun.search(tail)):
            return _fail("basis_mismatch", "role_not_after_date")
        if not own_verb and _ANY_EVENT_VERB.search(tail):
            return _fail("basis_mismatch", "other_event_verb")
    if date_basis in _START_BASES and _END_ROLE.search(tail):
        return _fail("basis_mismatch", "end_event_for_start_basis")
    if item.kind == "month_day":
        if not any(_safe(year, item.month, item.day) for year in range(today.year - 1, today.year + 4)):
            return _fail("ambiguous_date", "invalid_date")
        completed, planned = (role.completed, role.planned) if role else (_COMPLETED, _PLANNED)
        value = _infer_year(item.month, item.day, today, *_tense(tail, after, completed, planned))
        if value is None:
            return _fail("ambiguous_date", "tense_unclear")
    else:
        value = item.value
    evidence = {
        "source": "user_message",
        "message": source,
        "quote": quote,
        "span_start": start,
        "span_end": start + len(quote),
        "year_inferred": item.kind == "month_day",
        "normalized": value.isoformat(),
        "markers": TENSE_MARKERS_VERSION,
    }
    if model_date is not None and model_date != value:
        evidence["model_date_ignored"] = model_date.isoformat()
    return DateOrigin(True, value=value, evidence=evidence)


def _locate(quote: str, current: str, history: tuple[str, ...]) -> tuple[str, int, str] | None:
    """현재 질문에서 정확히 한 번 → 그 구간. 없으면 이력 전체에서 정확히 한 곳."""
    hits = _occurrences(current, quote)
    if len(hits) == 1 and hits[0] >= 0:
        return current, hits[0], "current_message"
    if hits:
        return None
    found = [
        (message, i, index) for index, message in enumerate(history) for i in _occurrences(message, quote)
    ]
    if len(found) != 1 or found[0][1] < 0:
        return None
    message, start, index = found[0]
    return message, start, f"history[{index}]"


def _occurrences(message: str, quote: str) -> list[int]:
    out, at = [], message.find(quote)
    while at >= 0:
        if not _bounded(message, at, at + len(quote)):
            return [-1, -1]  # 숫자 일부만 인용한 경우는 위치를 정할 수 없는 것으로 본다
        out.append(at)
        at = message.find(quote, at + 1)
    return out


def _bounded(message: str, start: int, end: int) -> bool:
    before = message[start - 1] if start > 0 else ""
    after = message[end] if end < len(message) else ""
    joins = {".", "/", "-"}  # 빈 문자열(메시지 끝)은 이어진 것이 아니다
    if message[start].isdigit() and (before.isdigit() or before in joins):
        return False
    last = message[end - 1]
    return not (last.isdigit() and (after.isdigit() or after in joins or after == "일"))


def _sentence_bounds(message: str, start: int, length: int) -> tuple[int, int]:
    """인용이 들어 있는 문장의 [시작, 끝). 연도 표지·범위·시제는 이 범위에서만 본다."""
    left = 0
    for match in _SENTENCE_END.finditer(message, 0, start):
        left = match.end()
    following = _SENTENCE_END.search(message, start + length)
    return left, following.start() if following else len(message)


def _find_dates(quote: str, today: date) -> list[_Found]:
    out: list[_Found] = []
    taken: list[tuple[int, int]] = []

    def free(span: tuple[int, int]) -> bool:
        return not any(a < span[1] and span[0] < b for a, b in taken)

    for match in _FULL.finditer(quote):
        taken.append(match.span())  # 없는 날짜라도 그 구간을 다시 월·일로 읽어 보정하지 않는다
        out.append(_Found(*match.span(), "full", _safe(*(int(g) for g in match.groups()))))
    for match in _YEAR_MD.finditer(quote):
        if free(match.span()):
            taken.append(match.span())
            year = today.year + _YEAR_WORDS[match.group(1)]
            out.append(
                _Found(*match.span(), "year_md", _safe(year, int(match.group(2)), int(match.group(3))))
            )
    for pattern in (_MONTH_DAY, _SLASH):
        for match in pattern.finditer(quote):
            if free(match.span()):
                taken.append(match.span())
                out.append(_Found(*match.span(), "month_day", None, int(match.group(1)), int(match.group(2))))
    for match in _RELATIVE.finditer(quote):
        if free(match.span()):
            taken.append(match.span())
            out.append(
                _Found(*match.span(), "relative", today + timedelta(days=_RELATIVE_DAYS[match.group(1)]))
            )
    return sorted(out, key=lambda f: f.start)


def _tense(tail: str, after: str, completed: re.Pattern[str], planned: re.Pattern[str]) -> tuple[bool, bool]:
    """(완료, 예정). 날짜 뒤 말에서 그 사건 동사의 시제를 본다. 시제 없이 연결형("출발해서")이면 같은 문장
    뒤쪽의 주 서술어("…돌아온")를 일반 표지로 본다."""
    found = (bool(completed.search(tail)), bool(planned.search(tail)))
    if not any(found) and _DEFERRED.search(tail):
        return bool(_COMPLETED.search(after)), bool(_PLANNED.search(after))
    return found


def _infer_year(month: int, day: int, today: date, completed: bool, planned: bool) -> date | None:
    past = next((d for d in (_safe(today.year - k, month, day) for k in (0, 1)) if d and d <= today), None)
    future = next((d for d in (_safe(today.year + k, month, day) for k in (0, 1)) if d and d >= today), None)
    if future is not None and future > today + timedelta(days=PLANNED_HORIZON_DAYS):
        future = None
    if past is None and future is None:
        return None  # 없는 달력 날짜(2월 30일 등)
    if past is not None and past == future:
        return past
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
