"""브라우저 E2E용 백엔드(T-20/21). 과금 없음: 규칙 기반 가짜 모델과 글자 2-gram 임베딩을 쓴다.

실제 세션 로그인·CSRF·Origin·DB·티켓 상태 기계·SSE는 그대로다. 모델 판단만 가짜다(키워드로 도구를 고른다).
시험 DB(TEST_DATABASE_URL)를 비우고 교육·데모 조직·지원 범위·시험 문서 corpus(8개 PDF)를 적재한다.

    uv run python -m tests.e2e_server            # 127.0.0.1:8011
"""

import asyncio
import json
import os
import uuid
from typing import Any

import uvicorn
from sqlalchemy import text

from agent.app.main import create_app
from agent.modules.identity_access.service import IdentityService, load_demo_org
from agent.modules.it_support.service import load_support_scopes
from agent.modules.knowledge.service import KnowledgeService
from agent.modules.model_integration.ports import ModelResponse, Usage
from agent.modules.training.service import load_demo_trainings
from agent.shared.clock import FIXTURE_NOW, FixedClock
from agent.shared.contracts import ToolCallProposal
from agent.shared.db import make_engine
from tests.conftest import alembic_config, make_settings
from tests.knowledge_fixtures import BigramEmbedder, prepared_corpus

PORT = int(os.environ.get("E2E_PORT", "8011"))


class TickingClock(FixedClock):
    """읽을 때마다 1ms 흐르는 시계. 생성 시각이 겹치지 않아 대화 목록이 최근순으로 정렬된다.

    날짜·만료(5분)·교육 주 판정에는 영향이 없을 만큼 작다(요청 수천 번에 수 초).
    """

    def now(self):  # noqa: ANN201 - FixedClock.now와 같은 형
        self.advance(0.001)
        return super().now()


USAGE = Usage(input_tokens=1, output_tokens=1, complete=True)
TABLES = (
    "tickets, ticket_audit, idempotency_records, ticket_prepare_receipts, ticket_action_heads,"
    " ticket_actions, support_scopes, trainings, training_fixture_loads, tool_result_receipts, tool_calls,"
    " message_receipts,"
    " messages, agent_runs, conversations, auth_sessions, membership_audit, user_roles, user_departments,"
    " users, role_capabilities, roles, departments, corpus_pointer, snapshot_members, corpus_snapshots,"
    " chunk_embeddings, chunks, document_pages, parsed_artifacts, document_editions, source_files, acl_audit,"
    " resource_acl, logical_documents,"
    " wiki_pointer, wiki_snapshot_members, wiki_snapshots, wiki_embeddings,"
    " wiki_source_links, wiki_claims, wiki_pages, wiki_builds"
)


def _final(answer: str, outcome: str = "answered", **extra: Any) -> ModelResponse:
    candidate = {
        "answer": answer,
        "outcome": outcome,
        "training_ids": extra.get("training_ids", []),
        "selected_training_id": None,
        "citation_ids": extra.get("citation_ids", []),
        "ticket_ids": extra.get("ticket_ids", []),
        "action_id": extra.get("action_id"),
    }
    return ModelResponse((), candidate, "e2e-rule-model", "agent_answer", "e2e", USAGE)


def _tool(name: str, args: dict[str, Any]) -> ModelResponse:
    proposal = ToolCallProposal(name=name, arguments=args, provider_call_id=f"toolu_{uuid.uuid4().hex[:8]}")
    return ModelResponse((proposal,), None, "e2e-rule-model", "agent_answer", "e2e", USAGE)


class RuleModel:
    """질문 키워드로 도구를 고르고, 도구 결과로 최종 답을 만든다(서버 검증 경로는 실제와 같다)."""

    async def complete_once(self, request) -> ModelResponse:
        last = request.messages[-1]
        if last.role == "tool_result":
            # 실제 모델처럼 도구 결과 뒤 답을 쓰는 시간이 있다. 없으면 빠른 기계(CI)에서 진행 단계와 결과가
            # 한 덩어리로 도착해 화면의 진행 표시를 시험할 수 없다.
            await asyncio.sleep(0.3)
            call = request.messages[-2].tool_calls[0]
            result = json.loads(last.tool_results[0].content)
            if call.name == "search_documents" and call.arguments.get("query") == "외부교육비 지원 한도 정리":
                return self._summary(result)
            return self._after(call.name, result)
        question = (last.text or "").split("[사용자 질문]\n", 1)[-1]
        if "VPN" in question:
            quote = question.split(".")[0].strip()
            return _tool(
                "prepare_it_ticket",
                {
                    "subject": "IT 지원 요청",
                    "description": quote,
                    "category": "network",
                    "target_service": "VPN",
                    "origin_candidates": [
                        {"field": "subject", "template_id": "ticket.subject.generic.v1"},
                        {"field": "description", "quote": quote},
                        {"field": "category", "quote": "VPN"},
                        {"field": "target_service", "quote": "VPN"},
                    ],
                },
            )
        if "티켓" in question:
            return _tool("list_it_tickets", {})
        if "교육" in question and ("일정" in question or "다음 주" in question):
            return _tool("list_trainings", {"date_preset": "next_week"})
        if "정리" in question:
            # 답 형식(D-75): 결론 문장 + "- " 항목, 받은 원문 전부 인용(화면이 같은 쪽 조각을 묶는다)
            return _tool(
                "search_documents",
                {
                    "query": "외부교육비 지원 한도 정리",
                    "date_basis": "training_start",
                    "as_of_date": "2026-09-29",
                    "date_quote": "9월 29일에 시작한",
                },
            )
        if "한도" in question or "규정" in question:
            args: dict[str, Any] = {"query": "외부교육비 1회 과정 지원 한도"}
            if "9월 29일에 시작한" in question:
                args.update(
                    date_basis="training_start", as_of_date="2026-09-29", date_quote="9월 29일에 시작한"
                )
            return _tool("search_documents", args)
        return _final("교육 일정, 회사 규정, IT 지원 접수를 도와드릴 수 있습니다.")

    def _summary(self, result: dict[str, Any]) -> ModelResponse:
        if not result.get("ok") or result["data"]["resolution"] != "resolved":
            return _final("날짜를 알려 주세요.", "needs_clarification")
        passages = [p for g in result["data"]["groups"] for p in g["passages"]]
        if not passages:
            return _final("근거를 찾지 못했습니다.", "insufficient_evidence")
        answer = (
            "외부교육비는 과정 한도와 연간 한도를 함께 봅니다.\n\n"
            "- 사전 승인을 받은 교육만 지원합니다\n"
            "- 한도를 넘는 금액은 본인이 부담합니다"
        )
        return _final(answer, citation_ids=[p["citation_id"] for p in passages[:12]])  # 인용 상한 30 안

    def _after(self, name: str, result: dict[str, Any]) -> ModelResponse:
        if not result.get("ok"):
            return _final("요청을 처리하지 못했습니다.", "insufficient_evidence")
        data = result["data"]
        if name == "list_trainings":
            items = data["items"]
            if not items:
                return _final("해당 기간의 교육이 없습니다.", "no_results")
            titles = ", ".join(i["title"] for i in items)
            return _final(
                f"다음 주 교육은 {len(items)}건입니다: {titles}", training_ids=[i["id"] for i in items]
            )
        if name == "search_documents":
            if data["resolution"] != "resolved":
                prompt = (data.get("clarification") or {}).get("prompt") or "날짜를 알려 주세요."
                return _final(prompt, "needs_clarification")
            passages = [p for g in data["groups"] for p in g["passages"]]
            if not passages:
                return _final("근거를 찾지 못했습니다.", "insufficient_evidence")
            return _final(
                "규정 원문에 따르면 아래 근거를 확인해 주세요.", citation_ids=[passages[0]["citation_id"]]
            )
        if name == "prepare_it_ticket":
            return _final(
                "아래 내용으로 IT 지원 접수를 준비했습니다. 내용을 확인한 뒤 화면에서 접수해 주세요.",
                "action_pending",
                action_id=data["action_id"],
            )
        if name == "list_it_tickets":
            items = data["items"]
            if not items:
                return _final("열린 티켓이 없습니다.", "no_results")
            return _final(f"티켓 {len(items)}건이 있습니다.", ticket_ids=[t["id"] for t in items])
        return _final("확인했습니다.")


async def prepare_database(url: str) -> None:
    engine = make_engine(url)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {TABLES}"))  # noqa: S608 - 고정 테이블 목록
    await load_demo_trainings(
        engine, anchor_date=FIXTURE_NOW.date(), fixture_mode="fixed_status", now=FIXTURE_NOW
    )
    await load_demo_org(engine, FIXTURE_NOW)
    await load_support_scopes(engine)
    operator = await IdentityService(engine, FixedClock()).resolve_operator_actor("ops-admin")
    corpus, _ = await prepared_corpus(label="e2e")
    await KnowledgeService(engine, FixedClock()).publish(operator, corpus)
    await engine.dispose()


def main() -> None:
    from agent.shared.settings import Settings

    # 시험 DB 주소는 환경 변수 또는 앱 설정(.env)에서 읽는다(값을 출력하지 않는다).
    url = os.environ.get("TEST_DATABASE_URL") or Settings().test_database_url
    if not url:
        raise SystemExit("TEST_DATABASE_URL이 없다")
    from alembic import command

    command.upgrade(alembic_config(url), "head")  # alembic은 자체 이벤트 루프를 쓴다(루프 밖에서 호출)
    asyncio.run(prepare_database(url), loop_factory=asyncio.SelectorEventLoop)
    settings = make_settings(
        database_url=url,
        auth_mode="local_session",
        allowed_origins="http://127.0.0.1:5190,http://localhost:5190",
    )
    app = create_app(settings, clock=TickingClock(), chat_model=RuleModel(), embedding_model=BigramEmbedder())
    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, loop="asyncio", log_level="warning")
    server = uvicorn.Server(config)
    asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)


if __name__ == "__main__":
    main()
