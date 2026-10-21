"""D-71(P-28 B): 모델 문맥에 들어간 원문의 영업일 기한 문장을 찾아, 사용자 날짜로 계산한 마감일 표를 만든다.

모델이 계산 도구(D-69)를 부르기를 기다리지 않는다. 계산은 같은 함수·공휴일표(MOD-03 business_days)다.
기준일 짝(복귀일인지 출발일인지)은 모델이 원문 기한 문장(rule)을 보고 고른다.

찾는 기한(코퍼스 문형):
- after: 기준이 있는 "…부터/로부터/후/뒤 N영업일 이내·안에·동안·까지"(기준 없는 "P3 1영업일 이내"는 뺀다)
- before: "N영업일 전(까지)"
- nth_of_next_month: "다음 달·익월 N영업일"
- "다음 영업일"(after 1), "전 영업일까지"(before 1)
"첫 N영업일"(기준일을 1일로 셈)은 기준 표지(부터·후) 바로 뒤에 숫자가 오지 않아 잡히지 않는다.

D-83: 기한 문장의 기준 사건(끝나는 날·시작일·요청일·통지일·사용일)과 사용자 날짜 문구 뒤의 말을 대조해
맞는 짝에 matches_rule을 표시하고 앞에 둔다. "11월 16일부터 사흘 동안"이면 끝나는 날(18일)도 후보로 넣는다.
"""

import re
from datetime import date, timedelta
from typing import Any

from agent.modules.tool_execution.business_days import (
    CALENDAR_VERSION,
    BeyondMonth,
    Direction,
    OutOfCalendar,
    deadline,
)

_AFTER = re.compile(
    r"(?P<anchor>[가-힣A-Za-z]{1,8}(?:일|날)?)\s*(?:부터|로부터|후|뒤|이후)\s*,?\s*(?P<n>\d{1,2})\s*영업일"
    r"(?!\s*전)"
)
_BEFORE = re.compile(r"(?P<n>\d{1,2})\s*영업일\s*전")
_NEXT_MONTH = re.compile(r"(?:다음\s*달|익월)\s*(?P<n>\d{1,2})\s*영업일")
# "안 다음 영업일 종료 전까지"(기준일 다음 영업일 하루), "교육 시작 전 영업일까지"(기준일 전 영업일 하루)
_NEXT_DAY = re.compile(r"(?<![달월])\s다음\s*영업일|^다음\s*영업일")
_PREV_DAY = re.compile(r"(?<![\d])전\s*영업일까지")
# 마감이 휴일이면 다음 영업일로 미루는 규칙은 기한이 아니다
_ROLLOVER = re.compile(r"휴(무)?일이면|휴일인 경우|휴일과 겹치")
_CLAUSE = re.compile(r"[^.\n。|]+")
_SPLIT_WORD = re.compile(r"영\s*\n\s*업\s*\n?\s*일|영업\s*\n\s*일")
MAX_RULES = 6
MAX_BASES = 4

# D-83: 기준 사건. 기한 문장에서는 숫자 바로 앞 말로, 사용자 날짜 문구에서는 날짜 뒤 말로 판정한다.
_EVENTS = (
    ("end", re.compile(r"종료|끝[나난났내냈]|마치|마친|마쳤|수료|복귀|돌아[오와온왔]|귀임")),
    ("start", re.compile(r"시작|출발|개강|입과|떠나|내려가|올라가|적용\s*예정|시행\s*예정|입사")),
    ("request", re.compile(r"요청|신청|접수|상신|의뢰")),
    ("notice", re.compile(r"통지|통보|공지|발표|발령")),
    ("use", re.compile(r"사용|결제|구매|거래")),
)
BASE_ROLES = {
    "end": "끝나는 날",
    "start": "시작·출발일",
    "request": "요청·신청일",
    "notice": "통지일",
    "use": "사용·결제일",
}
_FROM = re.compile(r"^[^가-힣]*\d{1,2}\s*일\s*(?:\(?[월화수목금토일]요?일?\)?\s*)?부터")
_DURATION = re.compile(r"부터\s*(이틀|사흘|나흘|닷새|엿새|이레|열흘|(\d{1,2})\s*일)\s*(?:동안|간)")
_DAYS = {"이틀": 2, "사흘": 3, "나흘": 4, "닷새": 5, "엿새": 6, "이레": 7, "열흘": 10}
_PATTERNS = {"after": _AFTER, "before": _BEFORE, "nth_of_next_month": _NEXT_MONTH}


def rule_event(piece: str, n: int, direction: Direction) -> str | None:
    """기한 문장의 기준 사건: 그 기한 숫자 바로 앞(최대 12자)에서 가장 가까운 사건 말."""
    pattern = _PATTERNS.get(direction)
    match = next((m for m in pattern.finditer(piece) if int(m.group("n")) == n), None) if pattern else None
    if match is None:
        return None
    window = piece[max(0, match.start() - 12) : match.start("n")]
    best: tuple[str, int] | None = None
    for name, regex in _EVENTS:
        for hit in regex.finditer(window):
            if best is None or hit.end() > best[1]:
                best = (name, hit.end())
    return best[0] if best else None


def base_events(quote: str) -> set[str]:
    """사용자 날짜 문구가 말하는 사건. "…일부터"는 시작이다."""
    events = {name for name, regex in _EVENTS if regex.search(quote)}
    if _FROM.search(quote):
        events.add("start")
    return events


def _expand_bases(bases: list[tuple[date, str]]) -> list[tuple[date, str, set[str]]]:
    """기준일 후보에 사건을 붙이고, "부터 사흘 동안"이면 달력일로 센 끝나는 날을 더한다."""
    out: list[tuple[date, str, set[str]]] = []
    for base, quote in bases[:MAX_BASES]:
        out.append((base, quote, base_events(quote)))
        duration = _DURATION.search(quote)
        if duration:
            days = _DAYS.get(duration.group(1)) or int(duration.group(2) or 0)
            end = base + timedelta(days=days - 1)
            if days > 1 and end not in {d for d, _, _ in out} and end not in {d for d, _ in bases}:
                out.append((end, f"{quote} → {days}일째 끝나는 날", {"end"}))
    return out


def _normalize(text: str) -> str:
    """PDF 줄바꿈을 정리한다: "3영\n업일"을 잇고, 표 행(| 구분)이 아닌 줄은 한 줄로 잇는다."""
    lines: list[str] = []
    for line in _SPLIT_WORD.sub("영업일", text or "").split("\n"):
        if lines and "|" not in line and "|" not in lines[-1]:
            lines[-1] = f"{lines[-1]} {line}"
        else:
            lines.append(line)
    return "\n".join(lines)


def find_rules(text: str) -> list[tuple[str, int, Direction]]:
    """원문 한 덩어리에서 (그 기한 주변 조각, N, direction)."""
    found: list[tuple[str, int, Direction]] = []
    for clause in _CLAUSE.finditer(_normalize(text)):
        piece = clause.group(0).strip()
        if "영업일" not in piece:
            continue
        hits: list[tuple[int, int, int, Direction]] = [
            *(
                (m.start(), m.end(), int(m.group("n")), "nth_of_next_month")
                for m in _NEXT_MONTH.finditer(piece)
            ),
            *((m.start(), m.end(), int(m.group("n")), "before") for m in _BEFORE.finditer(piece)),
            *(
                (m.start(), m.end(), int(m.group("n")), "after")
                for m in _AFTER.finditer(piece)
                if not (
                    m.group("anchor").endswith("오") and piece[m.end("anchor") :].lstrip().startswith("후")
                )
            ),
        ]
        if not _ROLLOVER.search(piece):
            hits += [(m.start(), m.end(), 1, "after") for m in _NEXT_DAY.finditer(piece)]
        hits += [(m.start(), m.end(), 1, "before") for m in _PREV_DAY.finditer(piece)]
        for start, end, n, direction in sorted(hits):
            if 1 <= n <= 60:
                # 기한마다 그 앞뒤 조각을 준다(한 문장의 두 기한이 같은 문자열이 되지 않게)
                tail = piece[end : end + 15].split(",")[0]  # 뒤 조각은 다음 기한 앞(쉼표)에서 끊는다
                found.append((f"{piece[max(0, start - 40) : end]}{tail}".strip(), n, direction))
    return found


def deadline_hints(passages: list[dict[str, Any]], bases: list[tuple[date, str]]) -> dict[str, Any] | None:
    """모델 보기의 passage(citation_id·text·version·as_of_date)와 기준일 후보(날짜, 문구)로 계산표를 만든다.

    기한이나 계산 가능한 기준일이 없으면 None. 계산표는 원문 근거 예산(final_context_token_limit) 밖이다.
    """
    rules: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str]] = set()
    expanded: list[tuple[date, str, set[str]]] | None = None  # 기한 문장이 있을 때만 만든다
    for passage in passages:
        for piece, n, direction in find_rules(passage.get("text") or ""):
            key = (re.sub(r"\s+", "", piece), n, direction, passage.get("version"))
            if key in seen:
                continue
            seen.add(key)
            if expanded is None:
                expanded = _expand_bases(bases)
            computed = []
            event = rule_event(piece, n, direction)
            judged = event is not None and any(events for _, _, events in expanded)
            for base, quote, events in expanded:
                try:
                    result = deadline(base, n, direction)
                except (OutOfCalendar, BeyondMonth):
                    continue
                data = result.as_result()
                entry = {
                    "base_date": data["base_date"],
                    "base_quote": quote,
                    "deadline": data["deadline"],
                    "deadline_weekday": data["deadline_weekday"],
                    "skipped_holidays": data["skipped_holidays"],
                }
                if judged:
                    entry["matches_rule"] = event in events
                computed.append(entry)
            # 맞는 짝을 앞에 둔다(같은 표시끼리는 원래 순서).
            computed.sort(key=lambda entry: not entry.get("matches_rule", False))
            if computed:
                rules.append(
                    {
                        "citation_id": passage.get("citation_id"),
                        # 판본별 결과(D-67)에서도 어느 판본의 기한인지 구분하게 한다
                        "version": passage.get("version"),
                        "as_of_date": passage.get("as_of_date"),
                        "rule": piece,
                        "business_days": n,
                        "direction": direction,
                        "base_event": BASE_ROLES.get(event) if event else None,
                        "computed": computed,
                    }
                )
            if len(rules) >= MAX_RULES:
                break
        if len(rules) >= MAX_RULES:
            break
    if not rules:
        return None
    return {
        "rules": rules,
        "counting": {
            "after": "기준일은 세지 않고 다음 영업일을 1로 센다",
            "before": "기준일 전날부터 거꾸로 센다(그날까지)",
            "nth_of_next_month": "다음 달 N번째 영업일",
        },
        "calendar_version": CALENDAR_VERSION,
        "calendar_note": (
            "토·일과 법정 공휴일(대체·임시공휴일 포함)을 뺀 영업일이며 회사 자체 휴무일은 반영하지 않았다"
        ),
    }
