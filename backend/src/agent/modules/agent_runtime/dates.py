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

TENSE_MARKERS_VERSION = "tense-ko-v5"  # D-56: dev50 실측으로 보강(시작 기준 "부터", 시제 표지, 90일 창)
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
_YEAR_MARKERS = re.compile(
    r"재작년|작년|지난\s*해|올해|금년|내년|다음\s*해|후년|전년|이듬해|그\s*해|저번\s*연도|\d{4}\s*년"
)
# 두 자리 연도("25년 12월 5일", "25년도", "'25"). 인용이 "12월 5일"만이어도 걸리게 문장 전체에서 본다.
# "10년 근속"처럼 기간을 뜻하는 말은 뺀다.
_SHORT_YEAR = re.compile(r"(?<![\d'])'\d{2}(?!\d)|(?<!\d)\d{2}\s*년(?!\s*(차|근속|째|간|동안|이상|이하|만))")
# 날짜·시각 바로 뒤의 "부터·까지"와 "~"만 범위로 본다("영상 끝까지"는 범위가 아니다, D-56).
_RANGE = re.compile(
    r"(\d\s*(일|시|분)?\s*(부터|까지))|(\d|일|월)\s*[~∼]|(오늘|내일|모레|어제|그제)\s*(부터|까지)"
)
_HYPOTHETICAL = re.compile(r"다면|라면|한다는|는다는")
_STEMS = "시작|출발|신청|상신|처리|결재|승인|근무|출근|참석|수료|종료|접수|제출|요청|개강"
# 완료·예정 표지. "시작한다"는 완료가 아니라 예정이다.
_COMPLETED = re.compile(
    rf"({_STEMS})(한|했|된|됐)(?!다)|다녀온|다녀왔|떠난|떠났|돌아온|돌아왔|받은|받았|갔던"
    r"|갔다(?! ?(올|오))|끝난|끝났|었던|였던"
)
_PLANNED = re.compile(rf"({_STEMS})(하는|할|될|한다|된다)|다녀올|떠날|떠나는|예정|받을")
# "9월 29일에 출발해서 10월 2일에 돌아온"처럼 연결형이면 시제는 문장 뒤쪽 서술어에서 본다.
# 사건 동사가 아니어도 과거 어미("참가는 했는데", "끝났어요")가 있으면 90일 창 규칙으로 정하지 않는다(D-56).
# 강한 과거 단서: 받침 ㅆ 음절("있"·"겠" 제외), 목록의 과거 관형형("쓴 택시비", "묵은 호텔"),
# 회고형 "-던", 음슴체("다녀옴", "신청함"), "완료". 예정 표지와 함께 나오면 섞인 것으로 보고 되묻는다.
_PAST_STRONG = re.compile(
    "["
    + "".join(chr(c) for c in range(0xAC00, 0xD7A4) if (c - 0xAC00) % 28 == 20 and chr(c) not in "있겠")
    + "]"
    + r"|(?<![가-힣])(쓴|낸|탄|산|본|온|간|준|받은|들은|먹은|올린|다녀온|묵은|머문|잃어버린|놓친|잡은)"
    + r"(?![가-힣])|[가-힣]던(?![가-힣])|(다녀옴|받음|[가-힣](?<!포)함|[가-힣]됨)(?![가-힣])|완료"
)
# 과거 단서를 볼 때 빼는 말: 전해 들은 말("시작한다고 들은", "열린다고 들었는데")의 "들은·들었"과
# 예정 관용 "갔다 올·갔다 오는"의 "갔", 규정이 바뀌었는지 묻는 말("기준 바뀌었어요?")은
# 이 사건의 과거가 아니다.
_NOT_PAST = re.compile(
    r"[가-힣]*(다|라|냐)고\s*\S+|갔다 ?(올|오)|(규정|기준|한도|금액|제도|지침)\S*\s*(바뀌었|변경됐|달라졌)\S*"
    r"|잡혔|정해졌|확정됐"  # 일정이 잡혔다는 말은 사건의 과거가 아니다
)
# 약한 과거 단서: "-한·-된" 관형형("참가한 비용").
# "지정한 과정"처럼 사건과 무관한 경우가 많아 창 규칙에서만 쓴다.
# 흔한 형용사("가능한", "필요한", "관련된")는 뺀다.
_PAST_WEAK = re.compile(r"([가-힣]+)(한|된)(?![가-힣])")
_ADJECTIVES = frozenset(
    "가능 필요 관련 해당 중요 간단 동일 적절 유효 충분 정확 다양 일정 특정 상당 별도 무관".split()
)
_HAN_NOUNS = frozenset("권 상 하 제 기 시 연 무".split())  # "권한·상한·하한·제한·기한·시한·연한·무한"은 명사
# 날짜 앞의 "지난·지난번·저번"은 완료, "다음·오는"은 예정 단서다("지난 12월 5일 출장").
# "마감 지난 11월 20일"처럼 "지난"이 앞말에 붙은 동사면 어느 쪽인지 모른다.
_PAST_PREFIX = re.compile(r"(?<![가-힣])(지난\s*번에?|저번에?|지난)\s*$")
_PAST_PREFIX_VERB = re.compile(r"[가-힣]\s+지난\s*$")
_NEXT_PREFIX = re.compile(r"(?<![가-힣])(다음|오는)\s*$")
_EARLIER_IN_SENTENCE = re.compile(r"(?<![가-힣])(지난\s*번|저번)")
_PLANNED_HINT = re.compile(r"미리|앞으로")
# 날짜와 그 사건 사이에 절이 끊기거나 다른 때가 끼면 날짜는 그 사건의 날짜가 아니다
# ("11월 2일 이사하고 다음 주에 출장", "11월 2일부터 휴가인데 교육").
# 연결어미로 끝나는 말(-고·-면·-서·-며·-다가·-데·-니까·-지만, "에서"는 조사라 뺀다), "아니고·말고".
_CLAUSE_BREAK = re.compile(
    r"([가-힣](고|면|며|다가|데|니까|지만|라서|해서)|(휴가|외근|재택|연차|출장|교육|회의)(이)?라"
    r"|(?:(?!에)[가-힣])서)(?=[\s,]|$)|아니|말고|대로(?![가-힣])"
)
# 기준점·어림·다른 때("이후", "전날", "무렵", "다음 주", "이틀 뒤"), 일만 있는 날짜("5일에", "1박 2일"은 뺀다)
_OTHER_TIME = re.compile(
    r"이후|이전|전에|전날|전후|무렵|즈음|(?<![가-힣])(쯤|경|후|뒤|전)(?![가-힣])|다음 ?주|다음 ?달|이번 ?주"
    r"|이번 ?달|주말|다음 ?날|이튿날|며칠|일주일|(이틀|사흘|나흘) ?(뒤|후|전)|\d+ ?일 ?(뒤|후|전)"
    r"|(?<!박 )(?<!박)(?<!월 )(?<!월)(?<![\d.])\d{1,2}\s*일(?!\s*(간|동안))"
    r"|[월화수목금토일]요일|그 ?주|다음 ?[월화수목금토일](?![가-힣])|대신"  # D-63 검증: 요일·"대신"
)
# 날짜와 사건 사이의 규정 변경 말("9월 1일부터 바뀐 출장 규정"): 날짜는 사건일이 아니라 시행일이다(D-63 검증).
_REGULATION_CHANGE = re.compile(
    r"바뀐|바뀌는|바뀔|시행된|시행되는|시행될|개정된|개정되는|적용된|적용되는|변경된"
)
# 다른 사람의 사건("팀장님 출장 가시는데"): 높임 주어·어미가 날짜와 사건 사이나 사건 뒤에 있다.
_OTHER_ACTOR = re.compile(
    r"[가-힣]님(이|은|께서|도)?(?![가-힣])|(가|하|오|다녀오)시(는|ㄹ|면|고|니|던)|가셨|하셨|셨"
)
# 신청·결재 기준에서 날짜 뒤가 다른 사건 명사면("11월 20일 교육 신청") 날짜는 그 사건의 날짜다
_EVENT_NOUN = re.compile(r"출장|교육|과정|연수|휴가|연차|반차|외근|재택|휴직|워크숍|세미나|행사")
# 사건 명사 뒤에 신청·결재 동사("12월 24일 연차 신청했")가 오면 그 시제는 신청의 것이다
_NOUN_THEN_REQUEST = re.compile(
    rf"({_EVENT_NOUN.pattern})[^\s]*\s*.{{0,6}}?(신청|상신|요청|접수|제출|결재|승인)"
)
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
    completed = "|".join(
        filter(None, [rf"({regular})(한(?!다)|했|된(?!다)|됐)", "었던|였던", completed_extra])
    )
    planned = "|".join(
        filter(None, [rf"({regular})(하는|할|될|한다|된다)", rf"({regular}) ?예정", planned_extra])
    )
    return _Role(
        re.compile(verbs), re.compile(nouns) if nouns else None, re.compile(completed), re.compile(planned)
    )


_ROLES = {
    "trip_start": _role(
        "출발|떠나|떠난|떠날|떠났|다녀",
        "출장",
        # "안 갔"(아직 안 감)·"갔으면"(바람)·"갔다 올"(예정 관용)은 완료가 아니다
        "떠난|떠났|다녀온|다녀왔|(?<!안 )(?<!못 )갔(?!다 ?(올|오)|으면)|(?<!안 )(?<!못 )간 출장",
        "떠날|떠나는|다녀올|출장 ?예정|(?<!안 )(?<!못 )(가는|가요|갑니다|갈|가려)|갔다 ?(올|오)",
    ),
    "training_start": _role(
        "시작|개강",
        "교육|과정|연수",
        # "교육 들었·받았"만 완료다("열린다고 들었는데"·"안내 받았는데"는 다른 행위의 시제)
        "(교육|강의|수업|과정|연수)(을|를)? ?(들었|받았)|열린(?!다)|열렸",
        "교육 ?예정|열리는|열릴|열린다|듣는|들을|받을",
    ),
    "request_date": _role("신청|상신|요청|접수|제출", None),  # 상신 → 신청일(D-40)
    "approval_date": _role("결재(?! ?(올|상신|요청))|승인", None, "결재 ?받은|결재 ?받았", "결재 ?받을"),
    "processing_date": _role("처리", "발령|부서 ?이동|퇴사|입사|자로"),
    "work_date": _role("근무(?!지|처)|출근", None),
}
# 다른 사건의 동사. 날짜 뒤에 이것만 있으면("어제 신청한 출장") 그 날짜는 이 사건의 날짜가 아니다.
_ANY_EVENT_VERB = re.compile(
    r"출발|떠나|떠난|떠날|떠났|다녀|시작|개강|신청|상신|요청|접수|제출|결재|승인|처리|근무(?!지|처)|출근"
)
_END_ROLE = re.compile(r"돌아온|돌아왔|복귀|귀국|정산|보고|수료|끝난|끝났|마친|종료|마감")
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
    if source != "current_message" and _later_correction(message, current_message, history_user_messages):
        return _fail("ambiguous_date", "date_in_current_message")
    left, right = _sentence_bounds(message, start, len(quote))
    sentence = message[left:right]
    after = message[start + len(quote) : right]  # 같은 문장에서 인용 뒤
    found = _find_dates(quote, today)
    if not found:
        return _fail("missing_date", "no_date_in_quote")
    # D-56: 시작 기준(출장·교육 시작일)에서 "M월 D일부터"는 그 날짜가 시작일이다.
    # 뒤의 기간·끝 날짜는 쓰지 않는다.
    start_range = date_basis in _START_BASES and quote[found[0].end :].lstrip().startswith("부터")
    if len(found) > 1 and not (
        start_range and all(quote[f.end :].lstrip().startswith("까지") for f in found[1:])
    ):
        return _fail("basis_mismatch", "multiple_dates_in_quote")
    item = found[0]
    if item.kind != "month_day" and item.value is None:
        return _fail("ambiguous_date", "invalid_date")
    if item.kind == "relative" and source != "current_message":
        # 이력 메시지의 "어제"는 그 메시지를 보낸 날 기준인데 그 시각을 모른다.
        return _fail("ambiguous_date", "relative_date_in_history")
    if _RANGE.search(sentence) and not start_range:
        return _fail("ambiguous_date", "range_not_supported")
    if item.kind in ("month_day", "relative") and (
        _YEAR_MARKERS.search(sentence.replace(quote, "", 1) + quote) or _SHORT_YEAR.search(sentence)
    ):
        return _fail("ambiguous_date", "year_marker_not_supported")
    if item.kind in ("full", "year_md") and len(_YEAR_MARKERS.findall(sentence)) > 1:
        return _fail("ambiguous_date", "year_marker_not_supported")
    tail = quote[item.end :]  # 날짜 뒤에 붙은 말: 역할·시제는 여기서만 본다
    if _ONLY_PARTICLE.fullmatch(tail):
        # 모델이 인용을 날짜·조사까지만 잘랐다("11월 12일부터"). 같은 문장의 인용 뒤 말에서 역할·시제를 본다.
        # 날짜와 사건 사이 검사(다른 사건·절 끊김·다른 때)는 그대로 적용된다(D-63).
        # 이어 보는 범위는 첫 쉼표·"그리고·근데" 앞까지다(다른 절의 시제를 가져오지 않게).
        extension = re.split(r"[,，]|그리고|그런데|근데", after, maxsplit=1)[0]
        others = _find_dates(extension, today)
        # 시작 기준 "M월 D일부터 … M월 D일까지"의 끝 날짜만 허용한다(D-56과 같은 규칙).
        range_end = start_range or (date_basis in _START_BASES and tail.strip() == "부터")
        if others and not (range_end and all(extension[f.end :].lstrip().startswith("까지") for f in others)):
            return _fail("basis_mismatch", "multiple_dates_in_sentence")
        if _OTHER_ACTOR.search(extension):
            return _fail("basis_mismatch", "other_actor")
        tail = tail + extension
    if _HYPOTHETICAL.search(tail + after):
        return _fail("ambiguous_date", "hypothetical")
    role = _ROLES.get(date_basis or "")
    if role is not None:
        own_verb = role.verb.search(tail)
        own_noun = role.noun.search(tail) if role.noun else None
        if not own_verb and not own_noun:
            return _fail("basis_mismatch", "role_not_after_date")
        if not own_verb and _ANY_EVENT_VERB.search(tail):
            return _fail("basis_mismatch", "other_event_verb")
        lead = tail[: min(m.start() for m in (own_verb, own_noun) if m)]  # 날짜와 이 사건 사이
        if _ANY_EVENT_VERB.search(lead):
            return _fail("basis_mismatch", "other_event_verb")
        if date_basis not in _START_BASES and _EVENT_NOUN.search(lead):
            return _fail("basis_mismatch", "other_event_noun")
        if _REGULATION_CHANGE.search(lead):
            return _fail("basis_mismatch", "regulation_date")
        if _CLAUSE_BREAK.search(lead) or _OTHER_TIME.search(lead):
            return _fail("basis_mismatch", "date_in_other_clause")
    elif _OTHER_TIME.search(tail[:12]):
        return _fail("basis_mismatch", "date_in_other_clause")
    elif _NOUN_THEN_REQUEST.search(tail):
        # 기준 없이 "12월 24일 연차 신청했"이면 시제("했")는 신청의 것이라 연차 날짜의 연도를 정하지 못한다
        return _fail("basis_mismatch", "other_event_verb")
    if date_basis in _START_BASES and _END_ROLE.search(tail.split("까지")[0] if start_range else tail):
        return _fail("basis_mismatch", "end_event_for_start_basis")
    if item.kind == "month_day":
        if not any(_safe(year, item.month, item.day) for year in range(today.year - 1, today.year + 4)):
            return _fail("ambiguous_date", "invalid_date")
        completed, planned = (role.completed, role.planned) if role else (_COMPLETED, _PLANNED)
        value = _infer_year(
            item.month,
            item.day,
            today,
            *_tense(tail, after, completed, planned, message[left:start] + quote[: item.start]),
            past_strong=bool(_PAST_STRONG.search(_NOT_PAST.sub(" ", tail + after))),
            past_weak=_has_weak_past(_NOT_PAST.sub(" ", tail + after)),
        )
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


def _tense(
    tail: str, after: str, completed: re.Pattern[str], planned: re.Pattern[str], before: str = ""
) -> tuple[bool, bool]:
    """(완료, 예정). 날짜 뒤 말에서 그 사건 동사의 시제를 본다. 시제 없이 연결형("출발해서")이면 같은 문장
    뒤쪽의 주 서술어("…돌아온")를 일반 표지로 본다. 날짜 바로 앞의 "지난"·"다음"도 단서로 더한다."""
    if _PAST_PREFIX_VERB.search(before):
        return True, True  # "마감 지난 11월 20일": 섞인 것으로 보고 되묻는다
    if _EARLIER_IN_SENTENCE.search(before) and not _PAST_PREFIX.search(before):
        return True, True  # "지난번에 말한 12월 5일": 말한 때가 지난 것이지 사건은 모른다
    earlier = bool(_PAST_PREFIX.search(before))
    found = (
        bool(completed.search(tail) or earlier),
        bool(planned.search(tail) or _NEXT_PREFIX.search(before) or _PLANNED_HINT.search(tail + after)),
    )
    if not any(found) and _DEFERRED.search(tail):
        return bool(_COMPLETED.search(after)), bool(_PLANNED.search(after))
    return found


def _has_weak_past(text: str) -> bool:
    return any(
        not m.group(1).endswith(tuple(_ADJECTIVES)) and m.group(1) not in _HAN_NOUNS
        for m in _PAST_WEAK.finditer(text)
    )


_CORRECTION = re.compile(r"바뀌|바꿔|변경|미뤄|미루|미뤘|당겨|연기|취소|아니라|아니고")
_DAY_ONLY = re.compile(r"(?<![\d.월])\d{1,2}\s*일")


def _later_correction(message: str, current: str, history: tuple[str, ...]) -> bool:
    """이력 메시지를 인용했을 때, 그 뒤의 메시지(현재 메시지 포함)에 날짜·일·변경 말이 있으면 정정일 수 있다.
    "오늘"·"내일" 같은 상대 날짜는 정정으로 보지 않는다(현재 메시지의 다른 일일 때가 많다)."""
    index = max(i for i, m in enumerate(history) if m == message)
    for later in (*history[index + 1 :], current):
        if _MONTH_DAY.search(later) or _FULL.search(later) or _SLASH.search(later):
            return True
        if _DAY_ONLY.search(later) or _CORRECTION.search(later):
            return True
    return False


def _infer_year(
    month: int,
    day: int,
    today: date,
    completed: bool,
    planned: bool,
    *,
    past_strong: bool = False,
    past_weak: bool = False,
) -> date | None:
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
        return None if past_strong else future  # "출장 갈 때 쓴 택시비": 섞였다
    # D-56: 시제 표지가 없을 때 오늘 ±90일 창 안의 후보가 하나뿐이면 그 날짜다
    # (다른 후보는 1년 가까이 떨어져 있다).
    if completed or planned:
        return None  # 시제가 섞였으면 되묻는다
    # 사건 동사 밖의 과거 어미가 있으면 지난 날짜 후보만 본다("교육 참가는 했는데"에 올해 11월을 고르지 않게).
    near = [
        d
        for d in ((past,) if past_strong or past_weak else (past, future))
        if d is not None and abs((d - today).days) <= PLANNED_HORIZON_DAYS
    ]
    if len(set(near)) == 1:
        return near[0]
    return None


def _safe(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


# D-61: 날짜 없이 현재형으로 묻는 사건 기준 질문은 사건 날짜를 오늘로 본다. 과거 단서가 있으면 묻는다.
_EARLIER_WORDS = re.compile(
    r"(?<![가-힣])(지난\s*번|저번|지난|지지난|예전|작년|재작년|전년|전에|그때|당시|종전)"
    r"|이전 ?기준|개정 ?전|며칠 ?전|\d+\s*(일|주|달|개월|년)\s*(전|만에)"
)
# 날짜 비슷한 표현(월만, 명절): 정확한 날짜는 아니어도 사건이 오늘이 아닐 수 있다.
_LOOSE_DATE = re.compile(
    r"(?<!\d)\d{1,2}\s*월(?!\s*\d)|추석|설날|설 연휴|연휴|(?<![가-힣])(다음|다다음)\s*(주|달)"
)
# 사건이 끝난 뒤의 일(정산·환급·복귀 뒤 청구): 사건은 이미 지났다.
_AFTER_EVENT = re.compile(r"정산|환급|돌아와서|다녀와서|복귀 ?(후|해서|하고)|끝나고|마치고|수료 ?후")
# 날짜·조사만 남은 인용 꼬리(D-63)
_ONLY_PARTICLE = re.compile(r"\s*(에|에는|에도|부터|에서|의|로|으로|까지|쯤)?\s*")


def assume_today_check(
    message: str,
    history_user_messages: tuple[str, ...],
    today: date,
    other_history: tuple[str, ...] = (),
) -> dict[str, Any]:
    """current 기준 검색에서 사건 기준 규정이 걸렸을 때, 사건 날짜를 오늘로 가정해도 되는가.

    허용: 이번 메시지와 이력의 본인 메시지에 날짜 표현이 없고, 이번 메시지에 과거 단서(완료 표지·과거 어미·
    "지난번·예전·작년")가 없다. 그 밖에는 되묻는다(조용히 틀린 판본보다 되묻기가 낫다).
    """

    def dated(text: str) -> bool:
        # "오늘"은 가정하려는 날짜 자체라 날짜 표현으로 세지 않는다.
        return any(f.kind != "relative" or f.value != today for f in _find_dates(text, today))

    # other_history: 이력의 assistant 메시지. "그 교육"이 앞서 안내한 날짜의 교육을 가리킬 수 있어
    # 날짜만 본다(과거 단서는 사용자 메시지에서만).
    if any(dated(m) or _LOOSE_DATE.search(m) for m in (message, *history_user_messages, *other_history)):
        return {"allowed": False, "reason": "date_in_messages"}
    for text in (
        message,
        *history_user_messages,
    ):  # 이력의 과거 단서도 본다("지난달 출장 다녀왔어요" 뒤 "한도는?")
        cleaned = _NOT_PAST.sub(" ", text)
        if (
            _COMPLETED.search(text)
            or _PAST_STRONG.search(cleaned)
            or _has_weak_past(cleaned)
            or _EARLIER_WORDS.search(text)
            or _AFTER_EVENT.search(text)
        ):
            return {"allowed": False, "reason": "past_cue"}
    return {"allowed": True, "reason": None, "markers": TENSE_MARKERS_VERSION}
