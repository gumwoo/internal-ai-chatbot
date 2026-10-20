"""D-72(P-29 B): 원문 검색 후보 40·문서 다양성 순서(T-27 검색 설정, 과금·DB 없음).

가짜 KnowledgeService(tests/test_edition_split.py)로 한 문서가 거리 순 앞자리를 다 차지하는 후보를 만든다.
"""

from agent.modules.retrieval.service import (
    DIVERSE_GROUPS_PER_DOCUMENT,
    RAW_CANDIDATE_LIMIT,
    RETRIEVER_CONFIG_ID,
    RetrievalService,
    SearchRequest,
    SupportGroup,
    _diversify,
)
from tests.test_edition_split import ACTOR, NOW, FakeKnowledge, _p


def _group(doc, sg, distance):
    passage = _p(doc, f"{doc}-e", "v1", None, None, basis="general_reference", role="guidance", sg=sg)
    return SupportGroup(f"{doc}:{sg}", 0, distance, (passage,))


def test_diversify_caps_each_document_in_front_and_keeps_the_rest_behind():
    groups = [_group("A", i, 0.1 + i / 100) for i in range(1, 7)] + [_group("B", 1, 0.3), _group("C", 1, 0.4)]
    order = _diversify(groups, 4)
    assert [g.group_id for g in order] == ["A:1", "A:2", "A:3", "A:4", "B:1", "C:1", "A:5", "A:6"]
    assert [g.rank for g in order] == list(range(1, 9))  # 새 순서로 순위를 다시 매긴다


def _many(doc, n, start):
    return [
        _p(doc, f"{doc}-e", "v1", None, None, basis="general_reference", role="guidance", sg=start + i)
        for i in range(n)
    ]


async def _search(passages, strategy="raw", **kwargs):
    knowledge = FakeKnowledge(passages, [])
    request = SearchRequest(query="질문", date_basis="current", **kwargs)
    return await RetrievalService(knowledge).search(
        ACTOR, request, knowledge_as_of=NOW, snapshot_id="s", strategy=strategy
    )


async def test_raw_search_takes_up_to_40_candidates_and_lets_a_second_document_in():
    # 거리 순으로 A 문서가 30개, 그 뒤에 B 문서 5개. v1(후보 20·거리 순)이면 B가 들어오지 못했다.
    passages = _many("A", 30, 1) + _many("B", 5, 100)
    result = await _search(passages)
    keys = [g.passages[0].document_key for g in result.groups]
    assert len(result.groups) == 35 and RAW_CANDIDATE_LIMIT == 40
    assert keys[:DIVERSE_GROUPS_PER_DOCUMENT] == ["A"] * 4 and keys[4:8] == ["B"] * 4
    assert result.trace()["retriever_config_id"] == RETRIEVER_CONFIG_ID == "raw-diverse-cosine-v2"


async def test_model_top_k_still_limits_the_candidates():
    result = await _search(_many("A", 30, 1), top_k=5)
    assert len(result.groups) == 5


async def test_full_context_baseline_keeps_distance_order():
    """전체 문맥 기준선(D-50)은 다양성 순서를 쓰지 않는다(허용 원문 전체를 거리 순으로)."""
    from agent.shared.actor import ActorContext

    eval_actor = ActorContext("u", ("d",), ("employee",), frozenset({"knowledge.search"}), 1, "eval_fixture")
    knowledge = FakeKnowledge(_many("A", 6, 1) + _many("B", 2, 100), [])
    result = await RetrievalService(knowledge).search(
        eval_actor,
        SearchRequest(query="질문", date_basis="current"),
        knowledge_as_of=NOW,
        snapshot_id="s",
        strategy="full_context_reference",
    )
    assert [g.passages[0].document_key for g in result.groups] == ["A"] * 6 + ["B"] * 2


async def test_operational_wiki_fallback_to_raw_uses_the_same_diverse_order():
    """D-72 시험 중 발견: 운영 B가 원문 검색으로 넘어가면 기록된 설정(raw-diverse-cosine-v2)대로
    다양성 순서를 쓴다."""
    result = await _search(_many("A", 6, 1) + _many("B", 2, 100), strategy="wiki_assisted")
    assert result.trace()["effective_strategy"] == "raw"
    assert [g.passages[0].document_key for g in result.groups][:6] == ["A"] * 4 + ["B"] * 2


async def test_raw_candidates_stop_at_40():
    result = await _search(_many("A", 30, 1) + _many("B", 30, 100))
    assert len(result.groups) == 40


async def test_tool_top_k_accepts_up_to_the_server_candidate_limit():
    """모델 인자 top_k 상한은 서버 후보 상한(40)과 같다(D-72)."""
    import pytest
    from pydantic import ValidationError

    from agent.modules.tool_execution.executor import SearchDocumentsArgs

    assert SearchDocumentsArgs(query="q", top_k=40).top_k == 40
    with pytest.raises(ValidationError):
        SearchDocumentsArgs(query="q", top_k=41)
