"""D-71(P-28 B): 모델 문맥에 들어간 원문의 영업일 기한 문장을 찾아, 사용자 날짜로 계산한 마감일 표를 만든다.

모델이 계산 도구(D-69)를 부르기를 기다리지 않는다. 계산은 같은 함수·공휴일표(MOD-03 business_days)다.
기준일 짝(복귀일인지 출발일인지)은 모델이 원문 기한 문장(rule)을 보고 고른다.

찾는 기한(코퍼스 문형):
- after: 기준이 있는 "…부터/로부터/후/뒤 N영업일 이내·안에·동안·까지"(기준 없는 "P3 1영업일 이내"는 뺀다)
- before: "N영업일 전(까지)"
- nth_of_next_month: "다음 달·익월 N영업일"
- "다음 영업일"(after 1), "전 영업일까지"(before 1)
"첫 N영업일"(기준일을 1일로 셈)은 기준 표지(부터·후) 바로 뒤에 숫자가 오지 않아 잡히지 않는다.
"""

import re
from datetime import date
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
    for passage in passages:
        for piece, n, direction in find_rules(passage.get("text") or ""):
            key = (re.sub(r"\s+", "", piece), n, direction, passage.get("version"))
            if key in seen:
                continue
            seen.add(key)
            computed = []
            for base, quote in bases[:MAX_BASES]:
                try:
                    result = deadline(base, n, direction)
                except (OutOfCalendar, BeyondMonth):
                    continue
                data = result.as_result()
                computed.append(
                    {
                        "base_date": data["base_date"],
                        "base_quote": quote,
                        "deadline": data["deadline"],
                        "deadline_weekday": data["deadline_weekday"],
                        "skipped_holidays": data["skipped_holidays"],
                    }
                )
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
