"""티켓 입력 출처 정규화(D-42, 04-field-origins)와 강제 재호출 요청 형태(D-41). DB·과금 없음."""

from datetime import date

import pytest

from agent.modules.model_integration.anthropic_chat import AnthropicChatModel
from agent.modules.model_integration.ports import ModelConfig, ModelMessage, ModelRequest
from agent.shared.contracts import ToolSpec
from agent.shared.ticket_origins import allowed_normalizations, locate, normalize, occurred_at

TODAY = date(2026, 10, 16)


@pytest.mark.parametrize(
    ("quote", "expected"),
    [
        ("오늘 오전 9시 30분", "2026-10-16T09:30:00+09:00"),
        ("어제 오후 3시", "2026-10-15T15:00:00+09:00"),
        ("10월 14일 14:10", "2026-10-14T14:10:00+09:00"),
        ("2026년 10월 1일 오후 2시 반", "2026-10-01T14:30:00+09:00"),
        ("12월 30일 저녁 8시", "2025-12-30T20:00:00+09:00"),  # 발생 시각은 과거다(오늘 이전의 가장 가까운 날)
    ],
)
def test_occurred_at_needs_explicit_date_and_time(quote, expected):
    assert occurred_at(quote, TODAY).isoformat() == expected


@pytest.mark.parametrize(
    "quote",
    [
        "오전 9시",
        "오늘 3시",
        "어제 오늘 오전 9시",
        "아까",
        "10월 14일",
        "오늘 밤 12시",
        "어제부터 10시간째",
        "2027년 1월 1일 10:00",
    ],
)
def test_occurred_at_rejects_missing_or_ambiguous_parts(quote):
    with pytest.raises(ValueError):
        occurred_at(quote, TODAY)


@pytest.mark.parametrize(
    ("field", "quote", "expected"),
    [
        ("category", "VPN이 안 돼요", "network"),
        ("category", "노트북 화면이 깨져요", "device"),
        ("request_type", "VPN이 안 돼요", "incident"),
        ("request_type", "계정 발급 신청하고 싶어요", "service_request"),
        ("urgent_work", "내일 발표라 급해요", True),
        ("urgent_work", "급하지 않아요", False),
        ("urgent_work", "안 급해요", False),
        ("urgent_work", "긴급하지는 않아요", False),
        ("urgent_work", "당장은 아니에요", False),
        ("urgent_work", "빨리 안 해도 돼요", False),
    ],
)
def test_category_and_boolean_come_only_from_user_words(field, quote, expected):
    normalization = next(iter(allowed_normalizations(field)))
    assert normalize(field, normalization, quote, TODAY) == expected


@pytest.mark.parametrize(
    ("field", "quote"),
    [
        ("category", "VPN 노트북이 안 돼요"),  # 두 분류에 걸리면 하나로 정할 수 없다
        ("category", "이상해요"),
        ("urgent_work", "내일 회의가 있어요"),
    ],
)
def test_unclear_category_or_boolean_is_rejected(field, quote):
    normalization = next(iter(allowed_normalizations(field)))
    with pytest.raises(ValueError):
        normalize(field, normalization, quote, TODAY)


def test_free_text_only_identity_or_trim_and_quote_must_be_unique():
    assert allowed_normalizations("description") == {"identity", "trim"}
    assert allowed_normalizations("urgent_work") == {"user_boolean"}
    assert allowed_normalizations("reply_channel") == frozenset()
    assert locate("😀 VPN이 안 돼요", "VPN이 안 돼요") == 2  # code point
    assert locate("VPN VPN", "VPN") is None and locate("abc", "") is None


def _request(tool_choice: str) -> ModelRequest:
    return ModelRequest(
        purpose="agent_answer",
        messages=(ModelMessage(role="user", text="안녕"),),
        tools=(ToolSpec("list_trainings", "교육", {"type": "object", "properties": {}}),),
        output_contract={
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
        },
        timeout_s=10,
        model_config=ModelConfig(model="claude-haiku-5-5", max_output_tokens=100, config_version="t"),
        tool_choice=tool_choice,
    )


def test_forced_tool_call_drops_final_json_format():
    forced = AnthropicChatModel.build_params(_request("any"))
    assert forced["tool_choice"] == {"type": "any"} and "output_config" not in forced
    normal = AnthropicChatModel.build_params(_request("auto"))
    assert "tool_choice" not in normal and "output_config" in normal
