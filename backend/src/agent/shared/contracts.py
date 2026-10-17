"""여러 모듈이 주고받는 공급자 중립 값(CT-06). MOD-02·03·07이 같은 타입을 쓴다."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolCallProposal:
    """모델의 도구 제안. call_ordinal은 서버(MOD-02)가 붙이고 모델 값은 쓰지 않는다."""

    name: str
    arguments: dict[str, Any]
    provider_call_id: str
    # prepare 계열의 비신뢰 출처 제안. 업무 arguments와 분리해 둔다.
    origin_candidates: dict[str, Any] | None = field(default=None)
