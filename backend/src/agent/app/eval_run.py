"""APP-04 평가 실행기: 평가 문항(eval/README.md)을 같은 앱 경로로 실행하고 문항별 결과를 기록한다.

- 문항마다 그 계정(eval_fixture actor, 직원과 같은 업무 권한)으로 새 대화를 만들고 전략을 서버 설정으로
  고정한다(raw / wiki_assisted, 엄격 모드). 직원 HTTP와 같은 메시지 API를 앱 안에서 호출한다.
- 기록: 답·outcome·인용, run별 사용량·모델 ID, 검색 경로(tool_calls.retrieval_trace), 시간.
  도구 없이 끝난 첫 응답의 outcome·answer·재호출 사유(P-31 D, 런타임 기록 함수로 받는다. DB에는 없다).
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
    run_meta: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """문항마다 결과 한 줄을 out에 이어 쓴다. 한 문항이 실패해도 그 실패를 기록하고 다음 문항으로 간다.

    결과 행의 config에 예산·엄격 모드·평가 버전 등 실행 설정을 남긴다(설정별 집계·재현용).
    """
    config = {
        "budget": (policy or ExecutionPolicy()).final_context_token_limit,
        "strict": strict,
        "chat_model": settings.chat_model,
        **(run_meta or {}),
    }
    current = EvalActor()
    # P-31 D: run_id → 도구 없이 끝난 첫 응답(outcome·answer·재호출 사유). 결과 파일에만 남는다.
    first_responses: dict[str, dict[str, Any]] = {}
    app = create_app(
        settings,
        current_actor=current,
        clock=clock,
        chat_model=chat_model,
        embedding_model=embedding_model,
        policy=policy,
        first_response_sink=first_responses.__setitem__,
    )
    origin = settings.allowed_origins.split(",")[0].strip()
    results = []
    out.parent.mkdir(parents=True, exist_ok=True)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://eval", timeout=180.0) as client:
            with out.open("a", encoding="utf-8") as sink:
                for case in cases:
                    try:
                        result = await _run_case(
                            app, client, current, case, strategy, strict, origin, first_responses
                        )
                    except Exception as exc:  # noqa: BLE001 - 실패를 기록하고 계속한다(분모에서 빼지 않음)
                        result = {
                            "case_id": case["case_id"],
                            "split": case["split"],
                            "category": case["category"],
                            "strategy": strategy,
                            "strict": strict,
                            "actor": case["actor"],
                            "error": f"run_exception:{type(exc).__name__}",
                            "turns": [],
                            "runs": [],
                            "tools": [],
                        }
                    result["config"] = config
                    sink.write(json.dumps(result, ensure_ascii=False, default=str) + "\n")
                    sink.flush()
                    results.append(result)
    return results


async def _run_case(app, client, current, case, strategy, strict, origin, first_responses) -> dict[str, Any]:
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
                "evidence_trace": r.evidence_trace,
                "model_ids": r.model_ids,
                "retrieval_context": r.retrieval_context,
                "prompt_version": r.prompt_version,
                # 첫 응답에서 도구를 불렀으면 None이다.
                "first_response": first_responses.pop(str(r.id), None),
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


class CachingEmbedder:
    """질의 임베딩 디스크 캐시(평가 전용). A/B가 같은 질의를 다시 임베딩하지 않게 한다(무료 티어 절약).

    캐시 키는 (모델, 차원, 작업, 입력 문자열)이다. 캐시에 없는 입력만 실제 모델로 보낸다.
    """

    def __init__(self, inner, path: Path) -> None:
        self._inner = inner
        self._path = path
        self._cache: dict[str, tuple[float, ...]] = {}
        self.hits = self.misses = 0
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    self._cache[row["k"]] = tuple(row["v"])

    @staticmethod
    def _key(text: str, config) -> str:
        import hashlib

        return hashlib.sha256(f"{config.model}|{config.dimension}|{config.task}|{text}".encode()).hexdigest()

    async def embed_once(self, texts, config, timeout_s):
        from agent.modules.model_integration.ports import EmbeddingBatch, Usage

        keys = [self._key(t, config) for t in texts]
        missing = [t for t, k in zip(texts, keys, strict=True) if k not in self._cache]
        model_id = config.model
        if missing:
            self.misses += len(missing)
            batch = await self._inner.embed_once(tuple(missing), config, timeout_s)
            model_id = batch.model_id
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as sink:
                for text, vector in zip(missing, batch.vectors, strict=True):
                    key = self._key(text, config)
                    self._cache[key] = vector
                    sink.write(json.dumps({"k": key, "v": list(vector)}) + "\n")
        self.hits += len(texts) - len(missing)
        return EmbeddingBatch(
            model_id=model_id,
            dimension=config.dimension,
            vectors=tuple(self._cache[k] for k in keys),
            usage=Usage(input_tokens=None, output_tokens=None, complete=False),
            input_count=len(texts),
        )


async def load_passages(engine, passage_ids: set[str]) -> dict[str, Any]:
    """채점용 passage 본문·쪽·원본 파일(권한과 무관한 평가 도구 읽기, 결과에 나온 ID만)."""
    from sqlalchemy import text

    from agent.app.eval_score import PassageText

    if not passage_ids:
        return {}
    async with engine.connect() as conn:
        rows = (
            (
                await conn.execute(
                    text(
                        "SELECT c.passage_id, c.text, c.spans, e.source_file_id FROM chunks c"
                        " JOIN parsed_artifacts p ON p.artifact_id = c.artifact_id"
                        " JOIN document_editions e ON e.edition_id = p.edition_id"
                        " WHERE c.passage_id = ANY(CAST(:ids AS uuid[]))"
                    ),
                    {"ids": [uuid.UUID(i) for i in passage_ids]},
                )
            )
            .mappings()
            .all()
        )
    return {
        str(r["passage_id"]): PassageText(
            str(r["passage_id"]),
            r["source_file_id"],
            frozenset(int(s.get("page", 0)) for s in (r["spans"] or []) if isinstance(s, dict)),
            r["text"],
        )
        for r in rows
    }


def result_passage_ids(results: list[dict[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for result in results:
        for turn in result["turns"]:
            ids.update(c["passage_id"] for c in turn.get("citations", []) if c.get("passage_id"))
        for tool in result.get("tools", []):
            for group in (tool.get("trace") or {}).get("pool", []):
                ids.update(group.get("passage_ids", []))
        for run in result.get("runs", []):
            ids.update(p["passage_id"] for p in ((run.get("evidence_trace") or {}).get("packed") or []))
    return ids
