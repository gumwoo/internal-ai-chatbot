"""개발용 명령(APP-03/04 성격). 운영 환경(APP_ENV=production)에서는 실행하지 않는다.

    uv run python -m agent.cli seed-trainings [--anchor YYYY-MM-DD] [--mode fixed_status|live_clock]
    uv run python -m agent.cli ask "다음 주 교육 알려줘" [--fixed-clock] [--live]

ask는 기본이 dry-run이다. 모델에 보낼 요청만 보여 주고 호출하지 않는다.
--live를 붙여야 실제 Anthropic API를 호출한다(과금된다).
"""

import argparse
import asyncio
import json
import sys
import uuid
from datetime import date
from typing import Any

from agent.modules.agent_runtime.contracts import FINAL_OUTPUT_SCHEMA, ConversationSnapshot
from agent.modules.agent_runtime.observer import InMemoryObserver
from agent.modules.agent_runtime.prompt import PROMPT_VERSION, system_prompt
from agent.modules.agent_runtime.runtime import AgentRuntime
from agent.modules.identity_access.test_stub import TestStubCurrentActor
from agent.modules.model_integration.anthropic_chat import AnthropicChatModel
from agent.modules.model_integration.ports import ModelConfig, ModelMessage, ModelRequest
from agent.modules.tool_execution.executor import ToolExecutor
from agent.modules.training.service import TrainingService, load_demo_trainings
from agent.shared.clock import Clock, FixedClock, SystemClock
from agent.shared.contracts import ExecutionContext, ExecutionPolicy
from agent.shared.db import make_engine
from agent.shared.settings import Settings

# 표시용 가격(USD / 100만 토큰, 프롬프트 100K 토큰 이하). 출처: Anthropic 모델 문서의 Haiku 5.5 항목.
# 실제 청구액이 아니라 측정 토큰 × 공시 가격으로 계산한 값이다.
_PRICE_PER_MTOK = {"claude-haiku-5-5": (0.10, 0.50)}


def _settings() -> Settings:
    settings = Settings()
    if settings.app_env == "production":
        sys.exit("개발용 명령은 APP_ENV=production에서 실행하지 않는다")
    return settings


def _model_config(settings: Settings) -> ModelConfig:
    return ModelConfig(model=settings.chat_model, max_output_tokens=1024, config_version=PROMPT_VERSION)


async def _seed(args: argparse.Namespace) -> None:
    settings = _settings()
    clock = SystemClock()
    anchor = date.fromisoformat(args.anchor) if args.anchor else clock.now().date()
    engine = make_engine(settings.database_url, settings.db_connect_timeout_s)
    try:
        report = await load_demo_trainings(
            engine, anchor_date=anchor, fixture_mode=args.mode or settings.fixture_mode, now=clock.now()
        )
    finally:
        await engine.dispose()
    print(
        json.dumps(
            {
                "anchor_date": report.anchor_date.isoformat(),
                "fixture_mode": report.fixture_mode,
                "clock": report.clock.isoformat(),
                "shift_days": report.shift_days,
                "loaded": report.loaded,
            },
            ensure_ascii=False,
        )
    )


def _cost(model_id: str, input_tokens: int, output_tokens: int) -> float | None:
    price = _PRICE_PER_MTOK.get(model_id)
    if price is None:
        return None
    return (input_tokens * price[0] + output_tokens * price[1]) / 1_000_000


async def _ask(args: argparse.Namespace) -> None:
    settings = _settings()
    clock: Clock = FixedClock() if args.fixed_clock else SystemClock()
    actor = await TestStubCurrentActor(settings.test_actor_id or "test-a").resolve(None)  # type: ignore[arg-type]
    policy = ExecutionPolicy()
    context = ExecutionContext(
        request_id=str(uuid.uuid4()),
        conversation_id="cli",
        run_id=str(uuid.uuid4()),
        actor=actor,
        current_time=clock.now(),
        deadline_monotonic=clock.monotonic() + policy.run_timeout_s,
        policy=policy,
    )
    engine = make_engine(settings.database_url, settings.db_connect_timeout_s)
    try:
        tools = ToolExecutor(TrainingService(engine), clock)
        if not args.live:
            request = ModelRequest(
                purpose="agent_answer",
                messages=(ModelMessage(role="user", text=args.question),),
                tools=tools.describe_allowed_tools(context),
                output_contract=FINAL_OUTPUT_SCHEMA,
                timeout_s=policy.model_timeout_s,
                model_config=_model_config(settings),
                system=system_prompt(context.current_time),
            )
            params = AnthropicChatModel.build_params(request)
            print("[dry-run] 모델을 호출하지 않았다. 보낼 요청:")
            print(json.dumps(params, ensure_ascii=False, indent=2, default=str))
            return

        key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
        chat = AnthropicChatModel(api_key=key)
        try:
            runtime = AgentRuntime(chat, tools, clock, _model_config(settings))
            result = await runtime.execute(context, ConversationSnapshot(), args.question, InMemoryObserver())
        finally:
            await chat.aclose()
    finally:
        await engine.dispose()

    usage = result.usage
    model_id = result.model_ids[-1] if result.model_ids else settings.chat_model
    out: dict[str, Any] = {
        "status": result.status,
        "outcome": result.outcome.value if result.outcome else None,
        "answer": result.answer,
        "training_refs": [{"code": r.get("code"), "title": r.get("title")} for r in result.training_refs],
        "tools": [
            {"ordinal": r.ordinal, "name": r.name, "attempt": r.attempt, "ok": r.ok, "error": r.error_code}
            for r in result.tool_summary
        ],
        "error": result.error.code.value if result.error else None,
        "usage": {
            "model_attempts": usage.model_attempts,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "complete": usage.complete,
            "usd_by_list_price": _cost(model_id, usage.input_tokens, usage.output_tokens),
        },
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="agent.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    seed = sub.add_parser("seed-trainings", help="개발 DB에 고정 교육 fixture를 넣는다(재실행해도 중복 없음)")
    seed.add_argument("--anchor", help="기준 날짜 YYYY-MM-DD. 기본은 오늘(KST)")
    seed.add_argument("--mode", choices=["fixed_status", "live_clock"], help="기본은 FIXTURE_MODE 설정")

    ask = sub.add_parser("ask", help="질문 하나로 Agent를 실행한다. 기본은 dry-run")
    ask.add_argument("question")
    ask.add_argument("--fixed-clock", action="store_true", help="서버 시각을 2026-10-16 10:00 KST로 고정")
    ask.add_argument("--live", action="store_true", help="실제 Anthropic API를 호출한다(과금)")

    args = parser.parse_args(argv)
    handler = _seed if args.command == "seed-trainings" else _ask
    # psycopg async는 Windows Proactor 루프를 지원하지 않는다.
    asyncio.run(handler(args), loop_factory=asyncio.SelectorEventLoop)


if __name__ == "__main__":
    main()
