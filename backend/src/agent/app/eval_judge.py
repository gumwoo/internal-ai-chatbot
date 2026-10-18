"""APP-04 judge 보조 판정(docs/13 K9): 지원되지 않은 주장·충실성. 규칙 채점을 대신하지 않는다.

블라인딩: judge 입력은 익명 answer ID·질문·답변·gold 사실/예외/금지 주장·gold 인용 원문과
시스템이 인용한 원문만이다.
A/B 라벨·검색 경로·Wiki 흔적·모델 이름·시간/비용은 넣지 않는다. 판정 순서는 seed로 섞고 매핑은 따로 저장한다.
무료 티어 한도로 판정이 끊기면 그 문항은 실패로 남기고 일부 표본만으로 결론을 내지 않는다.
"""

import hashlib
import random
from datetime import datetime
from typing import Any

from agent.modules.model_integration.ports import (
    ChatModel,
    ModelCallError,
    ModelConfig,
    ModelMessage,
    ModelRequest,
)
from agent.shared.clock import KST

JUDGE_PROMPT_VERSION = "judge-v1"

JUDGE_SYSTEM = """당신은 사내 규정 질의응답의 채점자다. 주어진 gold(정답 사실·예외·금지 주장·근거 원문)만
기준으로 답변을 판정한다. 답변이 어느 시스템에서 나왔는지는 알 수 없고 알 필요도 없다.
- facts: gold 사실마다 답변이 그 사실을 말했는지(supported), 빠뜨렸는지(missing),
  반대로 말했는지(contradicted).
- exceptions: gold 예외·조건마다 같은 방식.
- forbidden_violated: 금지 주장 중 하나라도 답변이 주장했는가.
- unsupported_claim: 답변에 gold 근거 원문과 시스템 인용 원문 어디에도 없는 규칙·금액·기한·조건이 있는가.
- abstained: 답변이 근거 부족·권한 없음·확인 불가로 답을 보류했는가.
- verdict: correct(사실 모두 supported, 예외 빠짐 없음, 금지·근거 없는 주장 없음) / partial / incorrect.
  gold 사실이 없는 문항(근거 없음·권한 거절)은 abstained이고 금지 주장이 없으면 correct다.
- reason: 한두 문장."""

JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "facts": {
            "type": "array",
            "items": {"type": "string", "enum": ["supported", "missing", "contradicted"]},
        },
        "exceptions": {
            "type": "array",
            "items": {"type": "string", "enum": ["supported", "missing", "contradicted"]},
        },
        "forbidden_violated": {"type": "boolean"},
        "unsupported_claim": {"type": "boolean"},
        "abstained": {"type": "boolean"},
        "verdict": {"type": "string", "enum": ["correct", "partial", "incorrect"]},
        "reason": {"type": "string"},
    },
    "required": [
        "facts",
        "exceptions",
        "forbidden_violated",
        "unsupported_claim",
        "abstained",
        "verdict",
        "reason",
    ],
}


def judge_text(case: dict[str, Any], answer: str, cited_quotes: list[str], gold_quotes: list[str]) -> str:
    def listed(items: list[str], numbered: bool = False) -> list[str]:
        if not items:
            return ["(없음)"]
        return [f"{i}. {x}" if numbered else f"- {x}" for i, x in enumerate(items, 1)]

    lines = [f"질문: {' / '.join(case['turns'])}", "", "[답변]", answer or "(빈 답변)", ""]
    lines += ["[gold 사실]", *listed(case["required_facts"], True), ""]
    lines += ["[gold 예외·조건]", *listed(case.get("required_exceptions") or [], True), ""]
    lines += ["[금지 주장]", *listed(case["forbidden_claims"]), ""]
    lines += ["[gold 근거 원문]", *listed(gold_quotes), ""]
    lines += ["[시스템이 인용한 원문]", *listed(cited_quotes)]
    return "\n".join(lines)


def answer_id(case_id: str, label: str, answer_text: str, seed: int) -> str:
    """익명 answer ID는 내용(문항·설정·판정 입력)과 seed로 정한다. 실행 순서·파일 순서가 바뀌어도 같은 답은
    같은 ID이고, 다른 답은 다른 ID다(이어하기·다른 split 판정이 엉뚱한 문항에 붙지 않게)."""
    digest = hashlib.sha256(f"{seed}|{case_id}|{label}|{answer_text}".encode()).hexdigest()
    return digest[:32]


def blind_order(items: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    """판정 순서를 섞고 내용 기반 익명 answer ID를 붙인다(매핑은 호출자가 따로 저장)."""
    tagged = [
        {**item, "answer_id": answer_id(item["case_id"], item["label"], item["text"], seed)} for item in items
    ]
    tagged.sort(key=lambda item: item["answer_id"])  # 입력 순서와 무관한 기준 순서
    random.Random(seed).shuffle(tagged)  # noqa: S311 - 재현 가능한 순서 섞기(보안 용도 아님)
    return tagged


def valid_verdict(candidate: dict[str, Any], case: dict[str, Any]) -> bool:
    """judge 응답 형식 검사: 필수 키, 사실·예외 판정 수가 gold 수와 같은지."""
    if any(key not in candidate for key in JUDGE_SCHEMA["required"]):
        return False
    return len(candidate["facts"]) == len(case["required_facts"]) and len(candidate["exceptions"]) == len(
        case.get("required_exceptions") or []
    )


async def judge_one(
    chat: ChatModel, config: ModelConfig, text: str, case: dict[str, Any] | None = None
) -> dict[str, Any]:
    request = ModelRequest(
        purpose="eval_judge",
        messages=(ModelMessage(role="user", text=text),),
        tools=(),
        output_contract=JUDGE_SCHEMA,
        timeout_s=60.0,
        model_config=config,
        system=JUDGE_SYSTEM,
    )
    judged_at = datetime.now(KST).isoformat()
    try:
        response = await chat.complete_once(request)
    except ModelCallError as error:
        return {"judge_error": error.kind.value, "judged_at": judged_at}
    candidate = response.final_candidate or {}
    if case is not None and not valid_verdict(candidate, case):
        return {"judge_error": "schema_mismatch", "judged_at": judged_at, "judge_model": response.model_id}
    return {
        **candidate,
        "judge_model": response.model_id,
        "judged_at": judged_at,
        "judge_usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        },
    }
