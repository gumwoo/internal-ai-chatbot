"""Gemini judge 어댑터: 사고(thinking) token도 출력 사용량에 넣는다(D-59)."""

from types import SimpleNamespace

from agent.modules.model_integration.gemini_chat import GeminiJudgeModel
from agent.modules.model_integration.ports import ModelConfig, ModelMessage, ModelRequest


class _Models:
    def __init__(self, meta):
        self.meta = meta

    async def generate_content(self, model, contents, config):
        return SimpleNamespace(
            text='{"verdict": "correct"}', usage_metadata=self.meta, model_version="gemini-x"
        )


def _request():
    return ModelRequest(
        purpose="eval_judge",
        messages=(ModelMessage(role="user", text="q"),),
        tools=(),
        output_contract={"type": "object"},
        timeout_s=5.0,
        model_config=ModelConfig(model="gemini-x", max_output_tokens=4096, config_version="judge-v1"),
        system="s",
    )


async def test_output_usage_counts_thinking_tokens():
    meta = SimpleNamespace(prompt_token_count=10, candidates_token_count=5, thoughts_token_count=7)
    client = SimpleNamespace(aio=SimpleNamespace(models=_Models(meta)))
    response = await GeminiJudgeModel(api_key="k", client=client).complete_once(_request())
    assert (response.usage.input_tokens, response.usage.output_tokens) == (10, 12)


async def test_output_usage_without_thinking_field():
    meta = SimpleNamespace(prompt_token_count=10, candidates_token_count=5)
    client = SimpleNamespace(aio=SimpleNamespace(models=_Models(meta)))
    response = await GeminiJudgeModel(api_key="k", client=client).complete_once(_request())
    assert response.usage.output_tokens == 5
