# ruff: noqa: F811  (pytest fixture를 다른 시험 모듈에서 가져와 인자로 쓴다)
"""전체 문맥 기준선(D-22, docs/13 full-context-reference-v1). 과금 없음.

평가 포트만 쓰고, 날짜 해석은 A와 같으며, 검색 대신 그 사건 날짜에 허용된 passage 전체를 넣는다.
"""

from dataclasses import replace
from datetime import date

import pytest

from agent.app.eval_run import run_cases
from agent.modules.conversation.service import ServerOptions
from agent.modules.retrieval.service import FULL_CONTEXT_CONFIG_ID, RetrievalService, SearchRequest
from agent.shared.clock import FIXTURE_NOW, FixedClock
from agent.shared.errors import AppError, ErrorCode
from tests.conftest import api_client, make_settings
from tests.knowledge_fixtures import BigramEmbedder
from tests.test_document_agent import EMPLOYEE, HR, ORIGIN, Capturing, _app, final, tool_turn
from tests.test_knowledge import _publish, org  # noqa: F401
from tests.test_wiki import _search

EVAL_EMPLOYEE = replace(EMPLOYEE, source="eval_fixture")
EVAL_HR = replace(HR, source="eval_fixture")


async def _corpus(org):
    engine, operator, _ = org
    knowledge, published, _ = await _publish(engine, operator)
    return engine, knowledge, published.snapshot_id


async def _search_all(knowledge, actor, corpus, as_of=date(2026, 9, 29)):
    request = SearchRequest(query="외부교육비 지원 한도", date_basis="training_start", as_of_date=as_of)
    return await RetrievalService(knowledge).search(
        actor, request, knowledge_as_of=FIXTURE_NOW, snapshot_id=corpus, strategy="full_context_reference"
    )


_COUNT_SQL = (
    "SELECT count(*) FROM chunks c JOIN parsed_artifacts p USING (artifact_id)"
    " JOIN document_editions e USING (edition_id) JOIN resource_acl a ON a.document_key = e.document_key"
    " WHERE e.edition_state <> 'withdrawn' AND e.available_from <= :k"
    " AND a.policy->>'audience' = 'authenticated'"
    " AND (e.document_role = 'guidance'"
    " OR (e.effective_from <= :d AND (e.effective_to IS NULL OR :d < e.effective_to)))"
)


async def _visible_count(engine, as_of: date) -> int:
    from sqlalchemy import text

    async with engine.connect() as conn:
        return await conn.scalar(text(_COUNT_SQL), {"k": FIXTURE_NOW, "d": as_of})


async def test_baseline_puts_every_allowed_passage_for_the_event_date(org):
    engine, knowledge, corpus = await _corpus(org)
    result = await _search_all(knowledge, EVAL_EMPLOYEE, corpus)
    passages = [p for g in result.groups for p in g.passages]
    assert result.retriever_config_id == FULL_CONTEXT_CONFIG_ID
    # 사건 기준이 맞지 않는 규범(다른 application_basis)은 A와 같이 빠지므로 허용 원문 수 이하다.
    assert 0 < len(passages) <= await _visible_count(engine, date(2026, 9, 29))
    files = {p.source_file_id for p in passages}
    assert "PDF-031" in files and "PDF-030" not in files  # 9/29 교육은 종전 판본만(규범 적용 구간)
    assert not files & {"PDF-013", "PDF-093"}  # 제한 문서는 권한 없는 계정에 넣지 않는다
    # 다른 사건 기준(출장 시작일)의 규범은 교육 시작일 사건에 넣지 않는다(A와 같은 기준 필터).
    assert not files & {"PDF-081", "PDF-082"}
    assert len({p.passage_id for p in passages}) == len(passages)
    distances = [g.distance for g in result.groups]
    assert distances == sorted(distances) and [g.rank for g in result.groups] == list(
        range(1, len(distances) + 1)
    )
    for group in result.groups:
        ordinals = [p.extra["ordinal"] for p in group.passages]
        assert ordinals == sorted(ordinals)  # 그룹 안 원문 순서


async def test_baseline_respects_each_actor_permissions(org):
    _, knowledge, corpus = await _corpus(org)
    employee = await _search_all(knowledge, EVAL_EMPLOYEE, corpus, as_of=date(2026, 10, 16))
    hr = await _search_all(knowledge, EVAL_HR, corpus, as_of=date(2026, 10, 16))
    files = lambda r: {p.source_file_id for g in r.groups for p in g.passages}  # noqa: E731
    assert "PDF-013" in files(hr) and "PDF-013" not in files(employee)
    assert "PDF-093" not in files(hr)  # 인사 담당자도 결재 위임 문서는 못 본다


async def test_baseline_is_only_for_the_evaluation_port(org, migrated):
    _, knowledge, corpus = await _corpus(org)
    with pytest.raises(AppError) as error:
        await _search_all(knowledge, EMPLOYEE, corpus)  # test_stub(직원 경로) actor
    assert error.value.code is ErrorCode.RETRIEVAL_NOT_READY
    app = _app(migrated, Capturing([]))
    async with api_client(app):
        with pytest.raises(AppError) as created:
            await app.state.conversations.create_conversation(
                EMPLOYEE, None, server_options=ServerOptions("full_context_reference")
            )
    assert created.value.code is ErrorCode.INVALID_REQUEST


async def test_baseline_needs_the_same_date_clarification_as_a(org):
    _, knowledge, corpus = await _corpus(org)
    request = SearchRequest(query="외부교육비 지원 한도", date_basis="current")
    result = await RetrievalService(knowledge).search(
        EVAL_EMPLOYEE,
        request,
        knowledge_as_of=FIXTURE_NOW,
        snapshot_id=corpus,
        strategy="full_context_reference",
    )
    # D-67: A와 같은 날짜 처리 — 날짜를 모르면 되묻지 않고 판본별 원문을 함께 준다(판본을 고르지 않는다)
    assert result.resolution == "resolved" and result.edition_split is not None
    assert {g.as_of_date.isoformat() for g in result.groups} == {
        e["as_of_date"] for e in result.edition_split["editions"]
    }


async def test_eval_runner_runs_the_baseline_with_a_large_budget(org, migrated, tmp_path):
    from agent.shared.contracts import ExecutionPolicy

    await _corpus(org)
    model = Capturing([tool_turn(_search()), final("종전 기준입니다.", citations=["c1-1"])])
    case = {
        "case_id": "EV-T-F",
        "split": "dev",
        "category": "revision",
        "actor": "emp-sales",
        "turns": ["9월 29일에 시작한 외부교육 한도는?"],
    }
    (result,) = await run_cases(
        [case],
        settings=make_settings(database_url=migrated, allowed_origins=ORIGIN),
        clock=FixedClock(),
        strategy="full_context_reference",
        strict=True,
        out=tmp_path / "f.jsonl",
        policy=ExecutionPolicy(final_context_token_limit=150_000),
        chat_model=model,
        embedding_model=BigramEmbedder(),
    )
    (tool,) = result["tools"]
    assert tool["trace"]["retriever_config_id"] == FULL_CONTEXT_CONFIG_ID
    (run,) = result["runs"]
    pool = {p for g in tool["trace"]["pool"] for p in g["passage_ids"]}
    packed = {p["passage_id"] for p in run["evidence_trace"]["packed"]}
    assert packed == pool  # 큰 예산이면 허용 원문이 모두 문맥에 들어간다
    assert run["evidence_trace"]["context_token_limit"] == 150_000
