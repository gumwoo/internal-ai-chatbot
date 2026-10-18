"""APP-04 평가 실행기: 평가 문항(eval/README.md)을 같은 앱 경로로 실행하고 문항별 결과를 기록한다.

- 문항마다 그 계정(eval_fixture actor, 직원과 같은 업무 권한)으로 새 대화를 만들고 전략을 서버 설정으로
  고정한다(raw / wiki_assisted, 엄격 모드). 직원 HTTP와 같은 메시지 API를 앱 안에서 호출한다.
- 기록: 답·outcome·인용, run별 사용량·모델 ID, 검색 경로(tool_calls.retrieval_trace), 시간.
- 채점은 따로 한다(eval_score). 이 실행기는 결과를 바꾸거나 실패를 빼지 않는다.
"""

import json
import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select

from agent.app.main import API_PREFIX, create_app
from agent.modules.conversation.service import ServerOptions
from agent.modules.conversation.tables import agent_runs, tool_calls
from agent.shared.actor import ActorContext
from agent.shared.clock import Clock
from agent.shared.contracts import ExecutionPolicy
from agent.shared.errors import AppError, ErrorCode
from agent.shared.settings import Settings


@dataclass
class EvalActor:
    """CP-02 CurrentActor: 평가기가 문항마다 바꿔 끼우는 actor(요청 헤더로 바뀌지 않는다)."""

    actor: ActorContext | None = None

    async def resolve(self, request) -> ActorContext:
        if self.actor is None:
            raise AppError(ErrorCode.AUTHENTICATION_REQUIRED)
        return self.actor


def load_cases(paths: Iterable[Path]) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for path in paths
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


async def run_cases(
    cases: list[dict[str, Any]],
    *,
    settings: Settings,
    clock: Clock,
    strategy: str,
    strict: bool,
    out: Path,
    policy: ExecutionPolicy | None = None,
    chat_model=None,
    embedding_model=None,
) -> list[dict[str, Any]]:
    current = EvalActor()
    app = create_app(
        settings,
        current_actor=current,
        clock=clock,
        chat_model=chat_model,
        embedding_model=embedding_model,
        policy=policy,
    )
    origin = settings.allowed_origins.split(",")[0].strip()
    results = []
    out.parent.mkdir(parents=True, exist_ok=True)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://eval", timeout=180.0) as client:
            with out.open("a", encoding="utf-8") as sink:
                for case in cases:
                    result = await _run_case(app, client, current, case, strategy, strict, origin)
                    sink.write(json.dumps(result, ensure_ascii=False, default=str) + "\n")
                    sink.flush()
                    results.append(result)
    return results


async def _run_case(app, client, current, case, strategy, strict, origin) -> dict[str, Any]:
    actor = await app.state.identity.resolve_eval_actor(case["actor"])
    current.actor = actor
    created = await app.state.conversations.create_conversation(
        actor, None, server_options=ServerOptions(strategy, strict)
    )
    conversation = created["id"]
    turns = []
    for content in case["turns"]:
        started = time.monotonic()
        response = await client.post(
            f"{API_PREFIX}/conversations/{conversation}/messages",
            json={"content": content},
            headers={"Origin": origin, "Idempotency-Key": str(uuid.uuid4())},
        )
        body = response.json() if response.content else {}
        turns.append(
            {
                "status": response.status_code,
                "seconds": round(time.monotonic() - started, 3),
                "outcome": body.get("outcome"),
                "answer": body.get("answer"),
                "citations": body.get("citations") or [],
                "error": (body.get("error") or {}).get("code")
                if isinstance(body.get("error"), dict)
                else None,
                "run_id": body.get("run_id"),
            }
        )
    async with app.state.engine.connect() as conn:
        runs = (
            await conn.execute(
                select(agent_runs)
                .where(agent_runs.c.conversation_id == uuid.UUID(conversation))
                .order_by(agent_runs.c.accepted_at)
            )
        ).all()
        traces = (
            await conn.execute(
                select(
                    tool_calls.c.run_id,
                    tool_calls.c.ordinal,
                    tool_calls.c.name,
                    tool_calls.c.ok,
                    tool_calls.c.error_code,
                    tool_calls.c.retrieval_trace,
                )
                .where(tool_calls.c.run_id.in_([r.id for r in runs]))
                .order_by(tool_calls.c.run_id, tool_calls.c.ordinal, tool_calls.c.attempt)
            )
        ).all()
    return {
        "case_id": case["case_id"],
        "split": case["split"],
        "category": case["category"],
        "strategy": strategy,
        "strict": strict,
        "actor": case["actor"],
        "turns": turns,
        "runs": [
            {
                "run_id": str(r.id),
                "status": r.status,
                "outcome": r.outcome,
                "error_code": r.error_code,
                "usage": r.usage,
                "model_ids": r.model_ids,
                "retrieval_context": r.retrieval_context,
                "prompt_version": r.prompt_version,
            }
            for r in runs
        ],
        "tools": [
            {
                "run_id": str(t.run_id),
                "ordinal": t.ordinal,
                "name": t.name,
                "ok": t.ok,
                "error_code": t.error_code,
                "trace": t.retrieval_trace,
            }
            for t in traces
        ],
    }
