"""프롬프트 인젝션 방어(D-82). 두 겹이다.

1. 입력 중화: 모델에 보내는 도구 결과(검색 원문·교육 설명·티켓 내용)에서 AI에게 내리는 지시로 보이는 문장만
   가림 문구로 바꾼다. 문서를 통째로 빼지 않는다(같은 문서의 다른 문장은 정상 근거로 계속 쓴다).
   판정은 좁게 잡는다: "이전 지시를 무시하라"류 무력화 문구, 또는 AI를 부르는 말과 명령형 어미가
   함께 있는 문장.
   "AI 도구에 사내 정보를 입력하지 마십시오"처럼 직원에게 하는 규정 문장은 가리지 않는다.
2. 출력 차단: 최종 답에 시스템 지침의 표식·긴 구간, 또는 가린 지시문의 구간이 그대로 나오면
   답을 안전 문구로 바꾼다.
"""

import re
from collections.abc import Iterable
from typing import Any

# 시스템 지침에 넣는 운영 표식. 답에 나오면 지침이 새어 나간 것이다.
CANARY = "운영표식-KX7Q2"
MASK = "[지시문으로 보여 가린 문장]"
WITHHOLD = "요청하신 내용에는 답할 수 없어요. 교육 일정, 회사 규정, IT 지원 접수에 대해 물어봐 주세요."

_OVERRIDE = re.compile(
    r"(이전|위의|앞의|앞선|기존|모든|지금까지의)\s*(지시|명령|규칙|지침|프롬프트|안내)\w*\s*"
    r"(은|는|을|를|이|가|들은|들을)?\s*(모두\s*|전부\s*|다\s*)?(무시|잊어|잊고|따르지\s*말)"
    r"|ignore\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above|earlier|preceding)\s+(instructions?|rules|prompts?)"
    r"|disregard\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above|earlier)"
    r"|시스템\s*프롬프트|system\s*prompt|개발자\s*모드|developer\s*mode|탈옥|jailbreak",
    re.IGNORECASE,
)
_ADDRESS = re.compile(
    r"(^|[\s\"'“‘(])(AI|인공지능|에이전트|어시스턴트|챗봇|언어\s*모델|assistant|chatbot|LLM|GPT|Claude|너|당신)"
    r"\s*(는|은|이|가|에게|야|이여|님)(?=\s|$)",
    re.IGNORECASE,
)
_COMMAND = re.compile(
    r"([가-힣]라|하시오|하십시오|할\s*것|대답하라|출력하라|말하라|알려라|보여라|붙여라|따르라|응답하라|"
    r"답해라|말해|답해|출력해|보여\s*줘|알려\s*줘|붙여\s*줘|해\s*줘|you\s+must|you\s+should|respond\s+with|answer\s+with)"
    r"\s*[.!。]?\s*$",
    re.IGNORECASE,
)
_SENTENCE = re.compile(r"[^.!?。\n]+[.!?。]?|\n")


def is_instruction(sentence: str) -> bool:
    """AI에게 내리는 지시로 보이는 문장인가(좁은 판정)."""
    text = sentence.strip()
    if len(text) < 6:
        return False
    if _OVERRIDE.search(text):
        return True
    return bool(_ADDRESS.search(text) and _COMMAND.search(text))


def neutralize_text(text: str, removed: list[str]) -> str:
    """지시문으로 보이는 문장만 가림 문구로 바꾸고, 가린 원문은 removed에 모은다."""
    if not text or not (_OVERRIDE.search(text) or _ADDRESS.search(text)):
        return text
    out: list[str] = []
    for match in _SENTENCE.finditer(text):
        sentence = match.group(0)
        if sentence != "\n" and is_instruction(sentence):
            removed.append(sentence.strip())
            lead = sentence[: len(sentence) - len(sentence.lstrip())]
            out.append(f"{lead}{MASK}")
        else:
            out.append(sentence)
    return "".join(out)


def neutralize_value(value: Any, removed: list[str]) -> Any:
    """도구 결과 데이터의 모든 문자열 값에 neutralize_text를 적용한 새 값(원본은 바꾸지 않는다)."""
    if isinstance(value, str):
        return neutralize_text(value, removed)
    if isinstance(value, dict):
        return {k: neutralize_value(v, removed) for k, v in value.items()}
    if isinstance(value, list):
        return [neutralize_value(v, removed) for v in value]
    if isinstance(value, tuple):
        return tuple(neutralize_value(v, removed) for v in value)
    return value


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _windows(text: str, size: int) -> set[str]:
    squashed = _squash(text)
    return {squashed[i : i + size] for i in range(0, max(len(squashed) - size + 1, 0))}


_PROMPT_WINDOW = 40
_REMOVED_WINDOW = 14


# 가린 지시문 안의 미끼 값: 숫자가 든 코드(ZX-9931, admin1234)와 금액·비율.
_BAIT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-]{3,}|\d[\d,]*(?:\.\d+)?\s*(?:만\s*원|원|%)")


def bait_values(removed: Iterable[str]) -> set[str]:
    found = (m.group(0) for s in removed for m in _BAIT.finditer(s))
    return {_squash(v) for v in found if any(ch.isdigit() for ch in v)}


def leak_reason(answer: str, system: str, removed: Iterable[str], seen: str = "") -> str | None:
    """답이 지침·가린 지시문을 그대로 옮겼으면 그 이유(로그용), 아니면 None.

    seen은 모델이 실제로 본 도구 결과(가린 뒤)다. 가린 지시문에만 있고 seen에는 없는 미끼 값이 답에 나오면
    지시를 따른 것으로 본다(같은 값이 정상 원문에도 있으면 막지 않는다).
    """
    removed = list(removed)
    squashed = _squash(answer)
    if not squashed:
        return None
    if CANARY in squashed:
        return "canary"
    if system and len(squashed) >= _PROMPT_WINDOW:
        windows = _windows(system, _PROMPT_WINDOW)
        starts = range(len(squashed) - _PROMPT_WINDOW + 1)
        if any(squashed[i : i + _PROMPT_WINDOW] in windows for i in starts):
            return "system_prompt"
    for sentence in removed:
        for window in _windows(sentence, _REMOVED_WINDOW):
            if window in squashed:
                return "removed_instruction"
    visible = _squash(seen)
    if any(value in squashed and value not in visible for value in bait_values(removed)):
        return "injected_value"
    return None
