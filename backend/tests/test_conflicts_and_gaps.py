# ruff: noqa: F811  (pytest fixture를 다른 시험 모듈에서 가져와 인자로 쓴다)
"""T-17 공지·FAQ·규정 충돌/위임: 안내 판본 선택, 원규정 공백 시 결론 보류, 우선관계 없는 충돌. 과금 없음.

docs/contracts/05-retrieval-assembly.md(guidance 판본·규범 공백),
docs/corpus/01-metadata-contract.md(우선순위).
경과조항 확장(transition_relations)과 authority_relations 적용은 검수된 관계 데이터가 없어 구현하지 않았다
(docs/15-policy-options.md P-19).
"""

from datetime import date, datetime

from agent.modules.agent_runtime.prompt import system_prompt
from agent.modules.ingestion.manifest import kst_midnight
from agent.shared.clock import KST
from tests.conftest import api_client
from tests.knowledge_fixtures import make_test_manifest
from tests.test_document_agent import Capturing, _app, _ask, final, published, tool_turn  # noqa: F401
from tests.test_knowledge import _publish, _query, org  # noqa: F401

NOW = datetime(2026, 10, 16, 10, 0, tzinfo=KST)

# ED-031(종전)은 2025-01-01부터 시행이다. 그 전에 시작한 교육에는 적용할 교육비 규정 판본이 없다.
GAP_SEARCH = (
    "search_documents",
    {
        "query": "외부교육비 1회 과정 지원 한도",
        "date_basis": "training_start",
        "as_of_date": "2024-11-01",
        "date_quote": "2024년 11월 1일에 시작한",
        "event_key": "old",
    },
)
GAP_QUESTION = "2024년 11월 1일에 시작한 외부교육 한도"
# 연도 표지는 문장 단위로 보므로 두 사건을 다른 문장에 둔다(TS-26).
TWO_EVENTS = "2024년 11월 1일에 시작한 교육이 있어요. 9월 29일에 시작한 교육도 한도가 궁금해요"
COVERED_SEARCH = (
    "search_documents",
    {
        "query": "외부교육비 1회 과정 지원 한도",
        "date_basis": "training_start",
        "as_of_date": "2026-09-29",
        "date_quote": "9월 29일에 시작한",
        "event_key": "new",
    },
)


async def test_guidance_edition_is_chosen_by_knowledge_time_not_both(org):
    """IT-045/046 안내 개정 쌍: 지식 시점에 유효한 안내 판본 하나만 후보다.

    available_from만으로 둘 다 회수하지 않는다.
    """
    engine, operator, actors = org
    manifest = make_test_manifest(("PDF-045", "PDF-046"))
    for entry in manifest["files"]:  # 시험 전용 안내 판본 구간(실제 검수 값 아님, P-15)
        # 현행(045)은 10-01부터 공개지만 안내 판본은 10-10부터다. 그 사이에는 둘 다 공개돼 있어도 046만 유효.
        if entry["source_file_id"] == "PDF-046":
            entry["guidance_valid_from"] = kst_midnight(date(2025, 4, 1))
            entry["guidance_valid_to"] = kst_midnight(date(2026, 10, 10))
        else:
            entry["guidance_valid_from"] = kst_midnight(date(2026, 10, 10))
    knowledge, snapshot, _ = await _publish(engine, operator, manifest, label="guidance-pair")
    actor = actors["emp-sales"]
    query = _query("VPN 원격접속 이용 방법")
    now = await knowledge.search(
        actor, snapshot.snapshot_id, query, knowledge_as_of=NOW, as_of_date=date(2026, 10, 16), limit=20
    )
    before = await knowledge.search(
        actor,
        snapshot.snapshot_id,
        query,
        knowledge_as_of=datetime(2026, 10, 5, 10, tzinfo=KST),  # 두 판본 모두 available_from 통과
        as_of_date=date(2026, 10, 5),
        limit=20,
    )
    assert now and {h.source_file_id for h in now} == {"PDF-045"}
    assert before and {h.source_file_id for h in before} == {"PDF-046"}


async def test_normative_gap_withholds_conclusion_but_keeps_guidance_for_procedure(published, migrated):
    """원규정 공백: 금액 결론은 보류(insufficient_evidence)하고, 안내 인용은 절차 확인용으로 남긴다."""
    probe = Capturing([tool_turn(GAP_SEARCH), final("답")])
    async with api_client(_app(migrated, probe)) as client:
        await _ask(client, GAP_QUESTION)
    data = probe.tool_payloads()[0]["data"]
    assert data["resolution"] == "resolved" and data["normative_gap"]["reason"] == "normative_gap"
    passages = [p for g in data["groups"] for p in g["passages"]]
    # 공백 기간을 다른 판본(2025년 시행 종전본·현행)으로 메우지 않는다. 이 날짜에 유효한 규범은 없다.
    assert passages and all(p["document_role"] == "guidance" for p in passages)
    assert all(p["document_type"] for p in passages)  # 모델이 FAQ·공지·규정을 구분할 수 있게
    guidance = next(p["citation_id"] for p in passages if p["document_role"] == "guidance")

    model = Capturing([tool_turn(GAP_SEARCH), final("한도는 100만 원입니다", citations=[guidance])])
    async with api_client(_app(migrated, model)) as client:
        _, response = await _ask(client, GAP_QUESTION)
    body = response.json()
    assert body["outcome"] == "insufficient_evidence" and "100만" not in body["answer"]
    assert "규정 판본이 없어" in body["answer"]
    assert [c["citation_id"] for c in body["citations"]] == [guidance]

    uncited = Capturing([tool_turn(GAP_SEARCH), final("한도는 100만 원입니다")])
    async with api_client(_app(migrated, uncited)) as client:
        _, response = await _ask(client, GAP_QUESTION)
    assert response.json()["outcome"] == "insufficient_evidence"


async def test_covered_date_has_no_gap_and_gap_is_per_search(published, migrated):
    model = Capturing([tool_turn(COVERED_SEARCH), final("답")])
    async with api_client(_app(migrated, model)) as client:
        await _ask(client, "9월 29일에 시작한 외부교육 한도")
    assert model.tool_payloads()[0]["data"]["normative_gap"] is None
    # 다른 사건의 검색만 인용한 답은 그대로 둔다(공백 검색에 기대지 않은 결론).
    probe = Capturing([tool_turn(GAP_SEARCH, COVERED_SEARCH), final("답")])
    async with api_client(_app(migrated, probe)) as client:
        await _ask(client, TWO_EVENTS)
    _, covered = probe.tool_payloads()
    normative = next(p["citation_id"] for g in covered["data"]["groups"] for p in g["passages"])
    model = Capturing(
        [tool_turn(GAP_SEARCH, COVERED_SEARCH), final("9월 29일 교육은 100만 원", citations=[normative])]
    )
    async with api_client(_app(migrated, model)) as client:
        _, response = await _ask(client, TWO_EVENTS)
    assert response.json()["outcome"] == "answered"


def test_prompt_states_guidance_cannot_override_and_unranked_conflicts_show_both():
    prompt = system_prompt(NOW, documents=True)
    assert "안내(FAQ·매뉴얼, document_role=guidance)는 규정을 바꾸지 못한다" in prompt
    assert "한쪽을 고르지 말고 양쪽 원문을 모두 인용" in prompt
    assert "normative_gap" in prompt


def _gap_search(query: str, basis: str = "training_start", event_key: str = "old") -> tuple[str, dict]:
    quote = "2024년 11월 1일에 시작한" if basis == "training_start" else "2024년 11월 1일에 출발한"
    args = {"query": query, "date_basis": basis, "as_of_date": "2024-11-01", "date_quote": quote}
    return ("search_documents", {**args, "event_key": event_key})


async def _payloads(migrated, calls, question) -> list[dict]:
    probe = Capturing([tool_turn(*calls), final("답")])
    async with api_client(_app(migrated, probe)) as client:
        await _ask(client, question)
    return [pl["data"] for pl in probe.tool_payloads()]


async def test_gap_is_checked_even_when_nearest_edition_is_guidance(published, migrated):
    """재검증 P1-1: 가장 가까운 판본이 FAQ여도, 날짜 기준이 맞는 가장 가까운 규범으로 공백을 본다."""
    search = _gap_search("출장 일비 숙박비 한도", basis="trip_start")
    question = "2024년 11월 1일에 출발한 출장 일비"
    (data,) = await _payloads(migrated, [search], question)
    assert data["normative_gap"] is not None
    faq = next(p["citation_id"] for g in data["groups"] for p in g["passages"])
    model = Capturing([tool_turn(search), final("일비는 5만 원", citations=[faq])])
    async with api_client(_app(migrated, model)) as client:
        _, response = await _ask(client, question)
    body = response.json()
    assert body["outcome"] == "insufficient_evidence" and "5만" not in body["answer"]


async def test_same_event_searched_with_another_query_is_still_withheld(published, migrated):
    """재검증 P1-2: 공백은 검색 호출이 아니라 사건 문맥 단위다(재사용 citation ID 포함)."""
    first = _gap_search("외부교육비 정산 FAQ 질문 답변")
    data = await _payloads(migrated, [first, GAP_SEARCH], GAP_QUESTION)
    reused = next(p["citation_id"] for g in data[0]["groups"] for p in g["passages"])
    model = Capturing([tool_turn(first, GAP_SEARCH), final("한도는 100만 원", citations=[reused])])
    async with api_client(_app(migrated, model)) as client:
        _, response = await _ask(client, GAP_QUESTION)
    assert response.json()["outcome"] == "insufficient_evidence"


async def test_insufficient_evidence_text_from_guidance_is_replaced(published, migrated):
    """재검증 P2-6: 근거 부족으로 내면서 안내의 금액을 쓰는 문장도 서버 문구로 바꾼다."""
    (data,) = await _payloads(migrated, [GAP_SEARCH], GAP_QUESTION)
    faq = next(p["citation_id"] for g in data["groups"] for p in g["passages"])
    leak = final("FAQ 기준 한도는 100만 원", outcome="insufficient_evidence", citations=[faq])
    model = Capturing([tool_turn(GAP_SEARCH), leak])
    async with api_client(_app(migrated, model)) as client:
        _, response = await _ask(client, GAP_QUESTION)
    body = response.json()
    assert body["outcome"] == "insufficient_evidence" and "100만" not in body["answer"]


async def test_other_event_basis_only_asks_instead_of_answering_from_guidance(published, migrated):
    """재검증 P1-4: 질문 기준(근무일)의 규범은 없고 다른 사건 기준(교육 시작일) 규범만 있으면 묻는다."""
    search = (
        "search_documents",
        {
            "query": "외부교육비 1회 과정 지원 한도",
            "date_basis": "work_date",
            "as_of_date": "2026-09-29",
            "date_quote": "9월 29일에 근무한",
        },
    )
    (data,) = await _payloads(migrated, [search], "9월 29일에 근무한 날 외부교육비 한도")
    assert data["resolution"] == "needs_clarification"
    assert data["clarification"]["reason"] == "basis_mismatch"
    assert data["clarification"]["required_event_type"] == "training_start"


def test_withhold_rule_counts_events_not_calls_and_valid_normative_citations():
    """보류 규칙: 교육 ID로 우회 안 됨, 공백 사건에서 그날 유효한 규범을 인용하면 보류 안 함."""
    from agent.modules.agent_runtime import runtime
    from agent.modules.agent_runtime.contracts import FinalCandidate

    gap_ctx = ("old", "training_start", "2024-11-01")
    other_ctx = ("new", "training_start", "2026-09-29")

    def run_with(citations):
        run = type("R", (), {})()
        run.normative_gap_contexts = {gap_ctx}
        run.citations = citations
        run.search_results = [{"resolution": "resolved", "normative_gap": {"safe_message": "보류"}}]
        run.missing_required_calls = set()
        run.context = type("C", (), {"run_id": "r"})()
        return run

    def passage(ctx, role):
        return {"event_key": ctx[0], "date_basis": ctx[1], "as_of_date": ctx[2], "document_role": role}

    answer = FinalCandidate(
        answer="한도", outcome="answered", training_ids=[], selected_training_id=None, citation_ids=[]
    )
    faq = run_with({"c1-1": passage(gap_ctx, "guidance")})
    assert runtime._server_outcome(faq, answer, ["c1-1"], ["training-1"])[1] == "보류"  # 교육 ID로 우회 안 됨
    assert runtime._server_outcome(faq, answer, [], [])[1] == "보류"  # 인용 없음
    valid = run_with({"c1-1": passage(gap_ctx, "normative"), "c1-2": passage(gap_ctx, "guidance")})
    assert runtime._server_outcome(valid, answer, ["c1-1", "c1-2"], []) is None
    mixed = run_with({"c1-1": passage(gap_ctx, "guidance"), "c2-1": passage(other_ctx, "normative")})
    assert (
        runtime._server_outcome(mixed, answer, ["c1-1", "c2-1"], [])[1] == "보류"
    )  # 공백 사건을 안내로 답함
    assert runtime._server_outcome(mixed, answer, ["c2-1"], []) is None  # 다른 사건만 인용


async def test_unrelated_general_reference_rule_is_not_a_gap_target(published, migrated):
    """재검증 P2-5: 결재권한 기준(일반 기준 규범, 10-01 시행)이 가장 가까워도
    교육 시작일 질문의 공백 대상이 아니다."""
    from agent.shared.actor import ActorContext

    head = ActorContext(
        "head-sales",
        ("dept-sales",),
        ("employee", "dept_head"),
        frozenset({"training.read", "knowledge.search", "ticket.read_own"}),
        1,
        "test_stub",
    )
    search = (
        "search_documents",
        {
            "query": "결재권한 위임 대결 기준 외부교육비 한도",
            "date_basis": "training_start",
            "as_of_date": "2026-09-29",
            "date_quote": "9월 29일에 시작한",
        },
    )
    probe = Capturing([tool_turn(search), final("답")])
    async with api_client(_app(migrated, probe, actor=head)) as client:
        await _ask(client, "9월 29일에 시작한 외부교육 한도와 결재권한")
    data = probe.tool_payloads()[0]["data"]
    assert data["resolution"] == "resolved" and data["normative_gap"] is None


async def test_unpublished_edition_does_not_cover_the_date(org):
    """공개 시각 전의 판본은 적용 구간이 맞아도 공백을 메우지 않는다(미래 지식 제외)."""
    engine, operator, actors = org
    knowledge, snapshot, _ = await _publish(engine, operator)
    actor = actors["emp-sales"]

    async def covers(knowledge_as_of):
        return await knowledge.normative_covers(
            actor,
            snapshot.snapshot_id,
            "DOC-030",
            as_of_date=date(2026, 10, 5),
            knowledge_as_of=knowledge_as_of,
        )

    assert await covers(NOW) is True
    assert await covers(datetime(2026, 9, 20, 10, tzinfo=KST)) is False  # 현행은 10-01 공개


# --- D-39(P-18 B): 일부 사건만 날짜 미확인이면 확인된 사건은 답하고 서버 되묻기 문구를 붙인다 ---

TRIP_NO_DATE = (
    "search_documents",
    {"query": "출장 숙박비 한도", "date_basis": "trip_start", "event_key": "trip"},
)
TWO_TOPICS = "9월 29일에 시작한 외부교육 한도랑 출장 숙박비 한도도 알려줘"


async def _covered_citation(migrated) -> str:
    probe = Capturing([tool_turn(COVERED_SEARCH, TRIP_NO_DATE), final("답")])
    async with api_client(_app(migrated, probe)) as client:
        await _ask(client, TWO_TOPICS)
    covered, trip = probe.tool_payloads()
    # D-67: 날짜 없는 출장은 되묻지 않고 판본별 원문을 준다(되묻기 문구는 서버 보정용으로만 남는다)
    assert trip["data"]["resolution"] == "resolved" and trip["data"]["edition_split"] is not None
    return next(p["citation_id"] for g in covered["data"]["groups"] for p in g["passages"])


async def test_partial_clarification_is_appended_to_answered(published, migrated):
    cid = await _covered_citation(migrated)
    model = Capturing(
        [tool_turn(COVERED_SEARCH, TRIP_NO_DATE), final("교육비 한도는 100만 원입니다", citations=[cid])]
    )
    async with api_client(_app(migrated, model)) as client:
        _, response = await _ask(client, TWO_TOPICS)
    body = response.json()
    assert body["outcome"] == "answered"
    assert body["answer"].startswith("교육비 한도는 100만 원입니다")
    assert body["answer"].endswith("출장 시작일이 필요합니다. 날짜를 알려 주시겠어요?")


async def test_partial_clarification_is_not_duplicated_or_added_after_resolution(published, migrated):
    cid = await _covered_citation(migrated)
    asked = "교육비는 100만 원. 적용할 규정 판본을 정하려면 출장 시작일이 필요합니다. 날짜를 알려 주시겠어요?"
    model = Capturing([tool_turn(COVERED_SEARCH, TRIP_NO_DATE), final(asked, citations=[cid])])
    async with api_client(_app(migrated, model)) as client:
        _, response = await _ask(client, TWO_TOPICS)
    assert response.json()["answer"] == asked  # 모델이 이미 같은 질문을 했으면 붙이지 않는다
    trip_dated = (
        "search_documents",
        {
            "query": "출장 숙박비 한도",
            "date_basis": "trip_start",
            "as_of_date": "2026-09-29",
            "date_quote": "9월 29일에 출발한",
            "event_key": "trip",
        },
    )
    model = Capturing(
        [tool_turn(COVERED_SEARCH, TRIP_NO_DATE), tool_turn(trip_dated), final("두 한도", citations=[cid])]
    )
    async with api_client(_app(migrated, model)) as client:
        _, response = await _ask(
            client, "9월 29일에 시작한 외부교육 한도. 9월 29일에 출발한 출장 숙박비 한도"
        )
    assert response.json()["answer"] == "두 한도"  # 같은 사건이 뒤에서 확인됐으면 되묻지 않는다


async def test_partial_clarification_survives_missing_event_key_and_current_search(published, migrated):
    """재검증 P1: event_key를 비우거나 같은 key로 current 검색을 해도 날짜 미확인 사건의 되묻기는 남는다."""
    covered = ("search_documents", {k: v for k, v in COVERED_SEARCH[1].items() if k != "event_key"})
    trip = ("search_documents", {"query": "출장 숙박비 한도", "date_basis": "trip_start"})
    cid = await _covered_citation(migrated)
    for calls in (
        [covered, trip],
        [
            COVERED_SEARCH,
            TRIP_NO_DATE,
            ("search_documents", {"query": "출장 숙박비 한도", "event_key": "trip"}),
        ],
    ):
        probe = Capturing([tool_turn(*calls), final("답")])
        async with api_client(_app(migrated, probe)) as client:
            await _ask(client, TWO_TOPICS)
        first = next(
            p["citation_id"] for g in probe.tool_payloads()[0]["data"]["groups"] for p in g["passages"]
        )
        model = Capturing([tool_turn(*calls), final("교육비 100만, 숙박 10만", citations=[first])])
        async with api_client(_app(migrated, model)) as client:
            _, response = await _ask(client, TWO_TOPICS)
        assert response.json()["answer"].endswith("출장 시작일이 필요합니다. 날짜를 알려 주시겠어요?"), calls
    assert cid


async def test_gap_abstain_keeps_other_event_clarification(published, migrated):
    """규범 공백으로 결론을 보류할 때도 날짜 미확인인 다른 사건의 되묻기 문구는 남긴다."""
    question = "2024년 11월 1일에 시작한 외부교육 한도. 출장 숙박비 한도도 알려줘"
    probe = Capturing([tool_turn(GAP_SEARCH, TRIP_NO_DATE), final("답")])
    async with api_client(_app(migrated, probe)) as client:
        await _ask(client, question)
    faq = next(p["citation_id"] for g in probe.tool_payloads()[0]["data"]["groups"] for p in g["passages"])
    model = Capturing([tool_turn(GAP_SEARCH, TRIP_NO_DATE), final("한도는 100만 원", citations=[faq])])
    async with api_client(_app(migrated, model)) as client:
        _, response = await _ask(client, question)
    body = response.json()
    assert body["outcome"] == "insufficient_evidence" and "규정 판본이 없어" in body["answer"]
    assert body["answer"].endswith("출장 시작일이 필요합니다. 날짜를 알려 주시겠어요?")
