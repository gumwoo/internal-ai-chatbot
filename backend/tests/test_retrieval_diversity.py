"""D-72(P-29 B): 원문 검색 후보 passage 40·거리 순(T-27 검색 설정, 과금·DB 없음).

가짜 KnowledgeService(tests/test_edition_split.py)로 한 문서가 거리 순 앞자리를 차지하는 후보를 만든다.
v1(후보 20)이면 뒤 문서가 들어오지 못했다. 문서 다양성 순서는 검색 단계 비교에서 이득이 없어 쓰지 않는다.
"""

import pytest
from pydantic import ValidationError

from agent.modules.retrieval.service import (
    RAW_CANDIDATE_LIMIT,
    RETRIEVER_CONFIG_ID,
    RetrievalService,
    SearchRequest,
)
from agent.modules.tool_execution.executor import SearchDocumentsArgs
from tests.test_edition_split import ACTOR, NOW, FakeKnowledge, _p


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


async def test_raw_search_takes_up_to_40_candidates_in_distance_order():
    # 거리 순으로 A 문서 30개 뒤에 B 문서 5개. v1(후보 20)이면 B가 들어오지 못했다.
    result = await _search(_many("A", 30, 1) + _many("B", 5, 100))
    keys = [g.passages[0].document_key for g in result.groups]
    assert RAW_CANDIDATE_LIMIT == 40 and keys == ["A"] * 30 + ["B"] * 5
    assert result.trace()["retriever_config_id"] == RETRIEVER_CONFIG_ID == "raw-exact-cosine-v2"


async def test_raw_candidates_stop_at_40_and_model_top_k_still_limits():
    assert len((await _search(_many("A", 30, 1) + _many("B", 30, 100))).groups) == 40
    assert len((await _search(_many("A", 30, 1), top_k=5)).groups) == 5


def test_tool_top_k_accepts_up_to_the_server_candidate_limit():
    """모델 인자 top_k 상한은 서버 후보 상한(40)과 같다(D-72)."""
    assert SearchDocumentsArgs(query="q", top_k=40).top_k == 40
    with pytest.raises(ValidationError):
        SearchDocumentsArgs(query="q", top_k=41)
