# ruff: noqa: F811  (pytest fixture를 다른 시험 모듈에서 가져와 인자로 쓴다)
"""D-40(P-19): 문서 우선관계·경과조항 확장·복수 사건 날짜. 과금 없음.

T-17 "명시된 우선관계만 적용", 05-retrieval-assembly "반대편 판본의 경과조항". 관계 값은 review-manifest가
원문 문장으로 만든 검수본(D-36·D-40)과 같은 규칙으로 만든다.
"""

import copy

import pytest

from agent.app.corpus_ops import INPUT_ROOT
from agent.modules.ingestion.manifest import check_relations
from agent.modules.ingestion.parser import parse_pdf
from agent.modules.ingestion.review import apply_review
from agent.shared.actor import ActorContext
from tests.conftest import api_client
from tests.knowledge_fixtures import make_test_manifest
from tests.test_document_agent import Capturing, _app, _ask, final, tool_turn
from tests.test_knowledge import _publish, org  # noqa: F401

FILES = ("PDF-041", "PDF-042", "PDF-091", "PDF-092", "PDF-093")
HEAD = ActorContext(
    "head-sales",
    ("dept-sales",),
    ("employee", "dept_head"),
    frozenset({"training.read", "knowledge.search", "ticket.read_own"}),
    1,
    "test_stub",
)


def reviewed_manifest():
    manifest = make_test_manifest(FILES)
    documents = {e["source_file_id"]: parse_pdf(INPUT_ROOT / e["filename"]) for e in manifest["files"]}
    apply_review(manifest, documents)
    return manifest


@pytest.fixture
async def related(org):
    engine, operator, _ = org
    manifest = reviewed_manifest()
    await _publish(engine, operator, manifest, label="relations")
    return manifest


def test_review_writes_explicit_relations_with_evidence_and_checks_form():
    manifest = reviewed_manifest()
    by_id = {e["source_file_id"]: e for e in manifest["files"]}
    assert all(e["review_status"] == "reviewed" and e["available_from"] for e in manifest["files"])
    kinds = {(r["kind"], r["target_code"]) for r in by_id["PDF-091"]["authority_relations"]}
    # 대상 문서가 manifest에 있는 관계만 만든다(이 시험 corpus에는 SEC-072가 없어 그 관계는 빠진다).
    assert ("limited_by", "CM-093") in kinds and not any(code == "SEC-072" for _, code in kinds)
    assert all(r["quote"] for r in by_id["PDF-091"]["authority_relations"])
    (cm092,) = by_id["PDF-091"]["transition_relations"]
    assert cm092["to_source_file_id"] == "PDF-092" and [c["event"] for c in cm092["event_conditions"]] == [
        "request_date",
        "approval_date",
    ]
    # 관계 형식 검사: 대상 문서·종류·사건 값·비교 값·반대편 판본이 틀리면 거절한다.
    assert check_relations(manifest["files"]) == []
    for mutate, expected in [
        (lambda r: r["authority_relations"][0].__setitem__("kind", "overrides"), "종류 오류"),
        (
            lambda r: r["authority_relations"][0].__setitem__("target_document_key", "DOC-999"),
            "대상 문서 없음",
        ),
        (
            lambda r: r["transition_relations"][0]["event_conditions"][0].__setitem__("event", "today"),
            "사건 종류",
        ),
        (
            lambda r: r["transition_relations"][0]["event_conditions"][0].__setitem__("compare", "near"),
            "비교 값",
        ),
        (lambda r: r["transition_relations"][0].__setitem__("to_source_file_id", "PDF-041"), "반대편 판본"),
    ]:
        broken = copy.deepcopy(manifest["files"])
        mutate(next(e for e in broken if e["source_file_id"] == "PDF-091"))
        assert any(expected in error for error in check_relations(broken)), expected


def _approval(date_iso, quote, other=None):
    args = {
        "query": "결재 처리 상태 최종 승인 반려 회수",
        "date_basis": "approval_date",
        "as_of_date": date_iso,
        "date_quote": quote,
    }
    if other:
        args["other_events"] = [other]
    return ("search_documents", args)


async def _data(migrated, search, question, actor=None):
    model = Capturing([tool_turn(search), final("답")])
    kwargs = {"actor": actor} if actor else {}
    async with api_client(_app(migrated, model, **kwargs)) as client:
        await _ask(client, question)
    return model.tool_payloads()[0]["data"]


def _roles(data):
    return {(p["title"], p["source_role"], p["heading"]) for g in data["groups"] for p in g["passages"]}


async def test_transition_clause_needs_both_events_and_is_attached_when_conditions_hold(related, migrated):
    question = "9월 28일에 상신했고 10월 5일에 최종 승인된 결재"
    # 상신일을 모르면 경과조항 조건을 판단할 수 없다. 기본 판본 결과는 두고 상신일을 묻는 후속 문구를 싣는다.
    data = await _data(migrated, _approval("2026-10-05", "10월 5일에 최종 승인된"), question)
    assert data["resolution"] == "resolved" and data["groups"]
    assert data["transition_pending"]["required_event_type"] == "request_date"
    assert all(role == "base" for _, role, _ in _roles(data))
    # 상신일(9/28, 사용자 문장으로 확인)과 승인일(10/5)이 조건을 모두 충족하면 종전본 제9조를 붙인다.
    other = {"date_basis": "request_date", "as_of_date": "2026-09-28", "date_quote": "9월 28일에 상신했고"}
    data = await _data(migrated, _approval("2026-10-05", "10월 5일에 최종 승인된", other), question)
    roles = _roles(data)
    assert data["resolution"] == "resolved"
    transitions = [h for _, role, h in roles if role == "transition"]
    assert transitions == ["제9조(미결 문서)"] and data["transition_pending"] is None
    # 같은 조항은 결과 전체에서 한 번만 붙는다(그룹마다 중복 주입하지 않음).
    flat = [p for g in data["groups"] for p in g["passages"] if p["source_role"] == "transition"]
    assert len({p["text"] for p in flat}) == len(flat)


async def test_transition_is_not_attached_when_a_known_condition_fails(related, migrated):
    # 상신이 10/1 이후면 조건 밖이다(붙이지 않음).
    other = {"date_basis": "request_date", "as_of_date": "2026-10-02", "date_quote": "10월 2일에 상신했고"}
    data = await _data(
        migrated,
        _approval("2026-10-05", "10월 5일에 최종 승인된", other),
        "10월 2일에 상신했고 10월 5일에 최종 승인된 결재",
    )
    assert data["resolution"] == "resolved" and all(role == "base" for _, role, _ in _roles(data))
    # 승인일이 9월이면 기본 판본이 종전본이고, 현행본의 경과조항 조건(승인 10/1 이후)도 밖이라 묻지 않는다.
    data = await _data(
        migrated, _approval("2026-09-20", "9월 20일에 최종 승인된"), "9월 20일에 최종 승인된 결재"
    )
    assert data["resolution"] == "resolved"


async def test_unverified_other_event_is_treated_as_missing(related, migrated):
    forged = {"date_basis": "request_date", "as_of_date": "2026-09-28", "date_quote": "9월 28일에 상신했고"}
    data = await _data(
        migrated, _approval("2026-10-05", "10월 5일에 최종 승인된", forged), "10월 5일에 최종 승인된 결재"
    )
    assert data["transition_pending"]["required_event_type"] == "request_date"  # 말하지 않은 상신일은 안 씀
    assert all(role == "base" for _, role, _ in _roles(data))


async def test_single_event_transition_for_account_processing(related, migrated):
    search = (
        "search_documents",
        {
            "query": "계정 생성 변경 승인 요청 접수번호 처리자 기록",
            "date_basis": "processing_date",
            "as_of_date": "2026-09-25",
            "date_quote": "9월 25일에 처리된",
        },
    )
    data = await _data(migrated, search, "9월 25일에 처리된 계정 변경 기록 기준")
    assert any(
        role == "transition" and heading == "제13조(종전 기준과의 관계)" for _, role, heading in _roles(data)
    )


async def test_authority_relations_only_show_visible_targets(related, migrated):
    # 현행본(PDF-091)이 기본 판본이 되게 10월 승인, 경과조항 조건 밖(10월 상신)으로 둔다.
    other = {"date_basis": "request_date", "as_of_date": "2026-10-02", "date_quote": "10월 2일에 상신했고"}
    search = _approval("2026-10-05", "10월 5일에 최종 승인된", other)
    search = ("search_documents", {**search[1], "query": "전결 대결 위임 범위 보안사고 긴급"})
    question = "10월 2일에 상신했고 10월 5일에 최종 승인된 결재"
    employee = await _data(migrated, search, question)
    head = await _data(migrated, search, question, actor=HEAD)
    assert head["resolution"] == "resolved"
    restricted = "결재권한 위임 및 대결 기준"
    assert all(
        r["to_title"] != restricted for r in employee["authority_relations"]
    )  # 제한 문서는 드러내지 않음
    assert any(r["to_title"] == restricted and r["kind"] == "limited_by" for r in head["authority_relations"])
    assert all(r["quote"] for r in head["authority_relations"])


@pytest.mark.parametrize(
    ("request_quote", "request_iso", "approval_quote", "approval_iso", "attached"),
    [
        ("9월 30일에 상신했고", "2026-09-30", "10월 1일에 최종 승인된", "2026-10-01", True),  # 경계 안쪽
        ("10월 1일에 상신했고", "2026-10-01", "10월 5일에 최종 승인된", "2026-10-05", False),  # 상신 경계 밖
    ],
)
async def test_transition_condition_boundaries(
    related, migrated, request_quote, request_iso, approval_quote, approval_iso, attached
):
    other = {"date_basis": "request_date", "as_of_date": request_iso, "date_quote": request_quote}
    data = await _data(
        migrated, _approval(approval_iso, approval_quote, other), f"{request_quote} {approval_quote} 결재"
    )
    assert any(role == "transition" for _, role, _ in _roles(data)) is attached


async def test_conflicting_other_event_dates_are_not_used(related, migrated):
    search = _approval("2026-10-05", "10월 5일에 최종 승인된")
    search[1]["other_events"] = [
        {"date_basis": "request_date", "as_of_date": "2026-09-28", "date_quote": "9월 28일에 상신했고"},
        {"date_basis": "request_date", "as_of_date": "2026-10-02", "date_quote": "10월 2일에 상신한"},
    ]
    data = await _data(
        migrated, search, "9월 28일에 상신했고 10월 5일에 최종 승인된 결재. 10월 2일에 상신한 건도 있다"
    )
    assert data["transition_pending"]["required_event_type"] == "request_date"  # 어느 상신일인지 모름


async def test_transition_prompt_is_appended_and_citation_marks_transition(related, migrated):
    question = "9월 28일에 상신했고 10월 5일에 최종 승인된 결재"
    data = await _data(migrated, _approval("2026-10-05", "10월 5일에 최종 승인된"), question)
    cid = next(p["citation_id"] for g in data["groups"] for p in g["passages"])
    model = Capturing(
        [tool_turn(_approval("2026-10-05", "10월 5일에 최종 승인된")), final("현행 기준", citations=[cid])]
    )
    async with api_client(_app(migrated, model)) as client:
        _, response = await _ask(client, question)
    assert response.json()["answer"].endswith(
        "경과조항 적용 여부를 확인하려면 신청일(상신일)이 필요합니다. 날짜를 알려 주시겠어요?"
    )
    other = {"date_basis": "request_date", "as_of_date": "2026-09-28", "date_quote": "9월 28일에 상신했고"}
    search = _approval("2026-10-05", "10월 5일에 최종 승인된", other)
    data = await _data(migrated, search, question)
    transition = next(
        p["citation_id"] for g in data["groups"] for p in g["passages"] if p["source_role"] == "transition"
    )
    model = Capturing([tool_turn(search), final("현행 기준으로 재검토", citations=[transition])])
    async with api_client(_app(migrated, model)) as client:
        _, response = await _ask(client, question)
    assert response.json()["citations"][0]["source_role"] == "transition"


def test_relation_checks_reject_basis_mismatch_and_self_reference_and_review_sets_guidance_windows():
    manifest = reviewed_manifest()
    broken = copy.deepcopy(manifest["files"])
    base = next(e for e in broken if e["source_file_id"] == "PDF-091")
    base["transition_relations"][0]["application_basis"] = "request_date"
    base["authority_relations"][0]["target_document_key"] = base["document_key"]
    errors = check_relations(broken)
    assert any("기본 판본과 다름" in e for e in errors) and any("자기 문서" in e for e in errors)
    guidance = make_test_manifest(("PDF-045", "PDF-046"))
    apply_review(guidance, {})
    new, old = sorted(guidance["files"], key=lambda e: e["source_file_id"])
    assert new["guidance_valid_from"] == new["available_from"] == "2026-10-01T00:00:00+09:00"
    assert old["guidance_valid_to"] == new["available_from"] and new["guidance_valid_to"] is None


async def test_opposite_edition_and_relation_titles_respect_knowledge_time(org):
    """공개 시각 전의 반대편 판본 조항·우선관계 대상 제목은 내보내지 않는다(미래 지식 제외)."""
    from datetime import datetime

    from agent.shared.clock import KST
    from tests.test_knowledge import NOW

    engine, operator, actors = org
    knowledge, snapshot, _ = await _publish(engine, operator, reviewed_manifest(), label="relations-time")
    before = datetime(2026, 9, 20, 10, tzinfo=KST)  # 현행본(PDF-041·PDF-093)은 10-01 공개

    async def clause(at):
        return await knowledge.transition_passages(
            actors["emp-sales"],
            snapshot.snapshot_id,
            "PDF-041",
            "제13조(종전 기준과의 관계)",
            knowledge_as_of=at,
        )

    assert await clause(NOW) and await clause(before) == []
    head = actors["head-sales"]
    titles = await knowledge.relation_titles(head, snapshot.snapshot_id, {"DOC-093"}, knowledge_as_of=NOW)
    assert titles == {"DOC-093": "결재권한 위임 및 대결 기준"}
    assert (
        await knowledge.relation_titles(head, snapshot.snapshot_id, {"DOC-093"}, knowledge_as_of=before) == {}
    )
