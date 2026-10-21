"""답 본문 안의 인용 표시(D-76). 모델은 근거를 쓴 문장 끝에 `[c1-2]`·`[c1-2, c3-1]`처럼 citation_id를 단다.

서버는 이번 실행 원장에 있는 ID만 남기고, 화면은 이 표시를 번호로 바꿔 그린다. 채점·다음 턴 이력에서는 지운다
(표시 안의 숫자가 금액·날짜 숫자로 세지지 않게, 지난 실행의 ID를 모델이 다시 쓰지 않게).
"""

import re
from collections.abc import Callable

_ID = r"c\d+-\d+"
MARKER = re.compile(rf"\s?\[({_ID}(?:\s*[,，]\s*{_ID})*)\]")
_SPLIT = re.compile(r"\s*[,，]\s*")


def marker_ids(text: str) -> list[str]:
    """본문에 나온 순서대로 인용 ID(중복 없음)."""
    found: list[str] = []
    for match in MARKER.finditer(text or ""):
        for cid in _SPLIT.split(match.group(1)):
            if cid not in found:
                found.append(cid)
    return found


def keep_markers(text: str, keep: Callable[[str], bool]) -> str:
    """keep이 참인 ID만 남긴다. 남는 ID가 없는 표시는 앞 공백과 함께 지운다."""

    def replace(match: re.Match[str]) -> str:
        ids = [cid for cid in _SPLIT.split(match.group(1)) if keep(cid)]
        if not ids:
            return ""
        lead = " " if match.group(0).startswith(" ") else ""
        return f"{lead}[{', '.join(ids)}]"

    return MARKER.sub(replace, text or "")


def strip_markers(text: str) -> str:
    return keep_markers(text, lambda _cid: False)
