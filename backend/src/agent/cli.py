"""개발용 명령(APP-03/04 성격). 운영 환경(APP_ENV=production)에서는 실행하지 않는다.

    uv run python -m agent.cli seed-trainings [--anchor YYYY-MM-DD] [--mode fixed_status|live_clock]
    uv run python -m agent.cli seed-identity
    uv run python -m agent.cli draft-manifest            # data/raw/document-manifest.json 초안(검수 전)
    uv run python -m agent.cli validate-manifest [--release]
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
from agent.modules.identity_access.service import load_demo_org
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
    mode = args.mode or settings.fixture_mode
    if mode is None:
        # MOD-04: fixture_mode는 기본값 없이 명시한다.
        sys.exit("fixture_mode가 없다. --mode 또는 FIXTURE_MODE를 지정한다(fixed_status | live_clock)")
    engine = make_engine(settings.database_url, settings.db_connect_timeout_s)
    try:
        report = await load_demo_trainings(engine, anchor_date=anchor, fixture_mode=mode, now=clock.now())
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


async def _seed_identity(args: argparse.Namespace) -> None:
    """데모 조직(D-30) 적재. 비밀번호는 해시만 저장하고 출력하지 않는다."""
    settings = _settings()
    engine = make_engine(settings.database_url, settings.db_connect_timeout_s)
    try:
        report = await load_demo_org(engine, SystemClock().now())
        from agent.modules.it_support.service import load_support_scopes

        report["support_scopes"] = await load_support_scopes(engine)  # D-42 데모 지원 범위
    finally:
        await engine.dispose()
    print(json.dumps(report, ensure_ascii=False))


async def _draft_manifest(args: argparse.Namespace) -> None:
    from agent.app.corpus_ops import MANIFEST_PATH, draft_manifest, write_json

    _settings()
    if MANIFEST_PATH.exists() and not args.force:
        # 검수한 manifest를 초안으로 덮어쓰지 않는다.
        sys.exit(f"{MANIFEST_PATH}가 이미 있다. 다시 만들려면 --force")
    manifest = draft_manifest(SystemClock().now())
    write_json(MANIFEST_PATH, manifest)
    states = [e["edition_state"] for e in manifest["files"]]
    print(
        json.dumps(
            {"written": str(MANIFEST_PATH), "files": len(states), "superseded": states.count("superseded")}
        )
    )


async def _review_manifest(args: argparse.Namespace) -> None:
    """D-36·D-40 규칙으로 manifest를 검수본으로 만든다. 원문을 읽기만 하고 PDF는 바꾸지 않는다."""
    from agent.app.corpus_ops import INPUT_ROOT, MANIFEST_PATH, write_json
    from agent.modules.ingestion.manifest import load_manifest, to_metadata, validate_manifest
    from agent.modules.ingestion.parser import parse_pdf
    from agent.modules.ingestion.review import apply_review
    from agent.modules.knowledge.service import validate_metadata

    manifest = load_manifest(MANIFEST_PATH)
    if manifest.get("status") == "reviewed" and not args.force:
        sys.exit("이미 검수본이다. 다시 적용하려면 --force")
    documents = {e["source_file_id"]: parse_pdf(INPUT_ROOT / e["filename"]) for e in manifest["files"]}
    notes = apply_review(manifest, documents)
    report = validate_manifest(manifest, INPUT_ROOT, release=True)
    problems = validate_metadata([to_metadata(e) for e in manifest["files"]])
    if report.errors or problems:
        print(
            json.dumps({"written": False, "errors": report.errors, "metadata": problems}, ensure_ascii=False)
        )
        sys.exit(1)
    write_json(MANIFEST_PATH, manifest)
    print(json.dumps({"written": str(MANIFEST_PATH), "notes": notes}, ensure_ascii=False))


async def _validate_manifest(args: argparse.Namespace) -> None:
    from agent.app.corpus_ops import INPUT_ROOT, MANIFEST_PATH
    from agent.modules.ingestion.manifest import load_manifest, validate_manifest

    report = validate_manifest(load_manifest(MANIFEST_PATH), INPUT_ROOT, release=args.release)
    print(
        json.dumps(
            {
                "ok": report.ok,
                "files": report.files,
                "document_keys": report.document_keys,
                "superseded": report.superseded,
                "errors": report.errors,
                "not_publishable": len(report.not_publishable),
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
            # 일부 시도의 사용량을 모르면 금액을 계산하지 않는다(모르는 비용을 0원처럼 보이지 않게, T-19).
            "usd_by_list_price": (
                _cost(model_id, usage.input_tokens, usage.output_tokens) if usage.complete else None
            ),
        },
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="agent.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    seed = sub.add_parser("seed-trainings", help="개발 DB에 고정 교육 fixture를 넣는다(재실행해도 중복 없음)")
    seed.add_argument("--anchor", help="기준 날짜 YYYY-MM-DD. 기본은 오늘(KST)")
    seed.add_argument("--mode", choices=["fixed_status", "live_clock"], help="기본은 FIXTURE_MODE 설정")

    sub.add_parser("seed-identity", help="개발 DB에 데모 조직·계정을 넣는다(재실행해도 중복 없음)")
    draft = sub.add_parser("draft-manifest", help="수령 목록·PDF 본문으로 manifest 초안(needs_review)을 쓴다")
    draft.add_argument("--force", action="store_true", help="이미 있는 manifest를 덮어쓴다")
    validate = sub.add_parser("validate-manifest", help="manifest를 검사한다(T-18)")
    validate.add_argument("--release", action="store_true", help="100파일·91키·종전9 구성까지 검사")
    review = sub.add_parser("review-manifest", help="D-36·D-40 규칙으로 manifest 검수본을 만든다")
    review.add_argument("--force", action="store_true", help="이미 검수본이어도 다시 적용한다")

    ask = sub.add_parser("ask", help="질문 하나로 Agent를 실행한다. 기본은 dry-run")
    ask.add_argument("question")
    ask.add_argument("--fixed-clock", action="store_true", help="서버 시각을 2026-10-16 10:00 KST로 고정")
    ask.add_argument("--live", action="store_true", help="실제 Anthropic API를 호출한다(과금)")

    args = parser.parse_args(argv)
    handler = {
        "seed-trainings": _seed,
        "seed-identity": _seed_identity,
        "draft-manifest": _draft_manifest,
        "validate-manifest": _validate_manifest,
        "review-manifest": _review_manifest,
        "ask": _ask,
    }[args.command]
    # psycopg async는 Windows Proactor 루프를 지원하지 않는다.
    asyncio.run(handler(args), loop_factory=asyncio.SelectorEventLoop)


if __name__ == "__main__":
    main()
