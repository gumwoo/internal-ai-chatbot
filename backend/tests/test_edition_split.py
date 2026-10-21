"""D-67 판본별 결과의 경계(T-15). 가짜 KnowledgeService로 판본 구성을 바꿔 본다(DB·모델 호출 없음).

독립 검증(2026-10-20)에서 재현된 결함의 회귀 시험이다.
"""

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from agent.modules.agent_runtime.runtime import _edition_split_notes
from agent.modules.knowledge.contracts import BasisHint, Passage
from agent.modules.retrieval.service import RetrievalService, SearchRequest
from agent.shared.actor import ActorContext

ACTOR = ActorContext("u", ("d",), ("employee",), frozenset({"knowledge.search"}), 1, "test_stub")
NOW = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)  # KST 2026-10-16 12:00


def _p(doc, edition, version, start, end, basis="training_start", role="normative", sg=1, text="본문"):
    return Passage(
        passage_id=f"{edition}-{sg}",
        document_key=doc,
        edition_id=edition,
        source_file_id=f"F-{edition}",
        artifact_id=f"A-{edition}",
        corpus_snapshot_id="s",
        title=doc,
        version=version,
        document_type="규정",
        document_role=role,
        application_basis=basis,
        edition_state="current",
        available_from=datetime(2024, 1, 1, tzinfo=UTC),
        effective_from=start,
        effective_to=end,
        support_group=sg,
        kind="clause",
        heading=None,
        section_path=(),
        text=text,
        page_spans=(),
        token_estimate=10,
        acl_revision=1,
    )


class FakeKnowledge:
    def __init__(self, passages, periods):
        self.passages = passages
        self.periods = periods
        self.covers_calls = []

    async def embed_query(self, q):
        return (0.0,)

    async def lookup_basis(self, actor, snapshot_id, vector, *, knowledge_as_of):
        seen = {}
        for p in self.passages:
            seen.setdefault(p.document_key, BasisHint(p.document_key, p.document_role, p.application_basis))
        return list(seen.values())

    async def normative_periods(self, actor, snapshot_id, key, *, knowledge_as_of):
        return self.periods

    async def normative_covers(self, actor, snapshot_id, key, *, as_of_date, knowledge_as_of):
        self.covers_calls.append(as_of_date)
        return any(
            p.document_key == key
            and p.document_role == "normative"
            and p.effective_from <= as_of_date
            and (p.effective_to is None or as_of_date < p.effective_to)
            for p in self.passages
        )

    async def search(
        self, actor, snapshot_id, vector, *, knowledge_as_of, as_of_date, limit, date_filter=True
    ):
        out = []
        for p in self.passages:
            if p.document_role == "normative" and date_filter:
                if not (
                    p.effective_from <= as_of_date and (p.effective_to is None or as_of_date < p.effective_to)
                ):
                    continue
            out.append(p)
        from dataclasses import replace

        return [replace(p, rank=i + 1, distance=0.1 * i) for i, p in enumerate(out)][:limit]

    async def support_group(self, actor, passage):
        return [passage]

    async def edition_relations(self, ids):
        return {}

    async def relation_titles(self, actor, snapshot_id, keys, *, knowledge_as_of):
        return {}


async def _run(knowledge, **kw):
    req = SearchRequest(query="외부교육 한도", date_basis="training_start", **kw)
    return await RetrievalService(knowledge).search(ACTOR, req, knowledge_as_of=NOW, snapshot_id="s")


def _split(*editions):
    return {
        "event_key": None,
        "date_basis": "training_start",
        "edition_split": {"document_key": "DOC", "editions": list(editions)},
        "clarification": {"prompt": "교육 시작일을 알려 주세요."},
    }


def _cite(day, doc="DOC"):
    return {
        "document_role": "normative",
        "event_key": None,
        "date_basis": "training_start",
        "as_of_date": day,
        "document_key": doc,
    }


E1 = {
    "version": "v1",
    "effective_from": "2024-01-01",
    "effective_to": "2025-01-01",
    "as_of_date": "2024-12-31",
}
E2 = {
    "version": "v2",
    "effective_from": "2025-01-01",
    "effective_to": "2026-10-01",
    "as_of_date": "2026-09-30",
}
E3 = {"version": "v3", "effective_from": "2026-10-01", "effective_to": None, "as_of_date": "2026-10-16"}


async def test_single_edition_that_ended_before_today_asks_instead_of_answering():
    """유일한 판본이 이미 끝났으면(오늘 사건은 공백) 그 판본으로 확정하지 않고 묻는다."""
    old = _p("DOC", "e1", "v1", date(2025, 1, 1), date(2026, 10, 1))
    k = FakeKnowledge([old], [(date(2025, 1, 1), date(2026, 10, 1), "v1")])
    r = await _run(k)
    assert r.resolution == "needs_clarification" and r.edition_split is None


async def test_published_future_edition_within_horizon_is_included_at_its_start_date():
    """90일 안에 시행될 판본이 공개돼 있으면 현행 하나로 확정하지 않고 시행일 날짜로 함께 준다."""
    cur = _p("DOC", "e1", "v1", date(2025, 1, 1), date(2026, 11, 1))
    nxt = _p("DOC", "e2", "v2", date(2026, 11, 1), None)
    k = FakeKnowledge(
        [cur, nxt], [(date(2025, 1, 1), date(2026, 11, 1), "v1"), (date(2026, 11, 1), None, "v2")]
    )
    r = await _run(k)
    assert r.resolution == "resolved" and r.edition_split is not None
    assert [e["as_of_date"] for e in r.edition_split["editions"]] == ["2026-10-16", "2026-11-01"]
    assert {p.version for g in r.groups for p in g.passages} == {"v1", "v2"}


async def test_edition_beyond_horizon_is_left_out():
    cur = _p("DOC", "e1", "v1", date(2025, 1, 1), date(2027, 6, 1))
    far = _p("DOC", "e2", "v2", date(2027, 6, 1), None)
    k = FakeKnowledge(
        [cur, far], [(date(2025, 1, 1), date(2027, 6, 1), "v1"), (date(2027, 6, 1), None, "v2")]
    )
    r = await _run(k)
    assert r.date_evidence["source"] == "single_edition"
    assert {p.version for g in r.groups for p in g.passages} == {"v1"}


@pytest.mark.parametrize("problem", ["year_marker_not_supported", "tense_unclear", "range_not_supported"])
async def test_ambiguous_date_still_asks(problem):
    """사용자가 날짜를 말했는데 연도·시제·범위가 모호하면 판본별로 답하지 않는다(90일 밖일 수 있다)."""
    cur = _p("DOC", "e1", "v1", date(2025, 1, 1), date(2026, 10, 1))
    nxt = _p("DOC", "e2", "v2", date(2026, 10, 1), None)
    k = FakeKnowledge(
        [cur, nxt], [(date(2025, 1, 1), date(2026, 10, 1), "v1"), (date(2026, 10, 1), None, "v2")]
    )
    r = await _run(k, date_problem="ambiguous_date", date_evidence={"problem": problem})
    assert r.resolution == "needs_clarification" and r.clarification["reason"] == "ambiguous_date"


async def test_full_context_reference_keeps_every_group_for_each_edition():
    """전체 문맥 기준선은 판본별 결과에서도 허용 원문 전체다(D-50)."""
    passages = (
        [_p("DOC", "e1", "v1", date(2025, 1, 1), date(2026, 10, 1), sg=i) for i in range(1, 6)]
        + [_p("DOC", "e2", "v2", date(2026, 10, 1), None, sg=i) for i in range(1, 6)]
        + [
            _p("G", "g1", "g", None, None, basis="general_reference", role="guidance", sg=i)
            for i in range(1, 4)
        ]
    )
    k = FakeKnowledge(
        passages, [(date(2025, 1, 1), date(2026, 10, 1), "v1"), (date(2026, 10, 1), None, "v2")]
    )
    eval_actor = ActorContext("u", ("d",), ("employee",), frozenset({"knowledge.search"}), 1, "eval_fixture")
    req = SearchRequest(query="q", date_basis="training_start")
    r = await RetrievalService(k).search(
        eval_actor, req, knowledge_as_of=NOW, snapshot_id="s", strategy="full_context_reference"
    )
    assert r.edition_split is not None and len(r.groups) == 13


def test_note_names_every_uncited_edition():
    run = SimpleNamespace(citations={"c1-1": _cite("2024-12-31"), "c1-2": _cite("2026-10-16")})
    (note,) = _edition_split_notes(run, [_split(E1, E2, E3)], ["c1-1", "c1-2"])
    assert "2025-01-01부터 2026-10-01 전까지이면 v2 판본" in note
    assert "v1" not in note and "v3" not in note


def test_other_normative_document_does_not_count_as_an_edition_citation():
    run = SimpleNamespace(citations={"c1-1": _cite("2026-10-16"), "c1-5": _cite("2026-09-30", doc="OTHER")})
    (note,) = _edition_split_notes(run, [_split(E2, E3)], ["c1-1", "c1-5"])
    assert "v2 판본" in note


def test_same_event_split_twice_gets_one_note():
    run = SimpleNamespace(citations={"c1-1": _cite("2026-10-16")})
    assert len(_edition_split_notes(run, [_split(E2, E3), _split(E2, E3)], ["c1-1"])) == 1


async def test_trace_records_why_editions_were_or_were_not_split():
    """D-86: 판본별 결과를 만들었는지, 안 만들었으면 왜인지 도구 기록(trace)에 남는다(모델에는 안 보임)."""
    cur = _p("DOC", "e1", "v1", date(2025, 1, 1), date(2026, 10, 1))
    nxt = _p("DOC", "e2", "v2", date(2026, 10, 1), None)
    periods = [(date(2025, 1, 1), date(2026, 10, 1), "v1"), (date(2026, 10, 1), None, "v2")]
    split = await _run(FakeKnowledge([cur, nxt], periods))
    assert split.trace()["date_path"] == {
        "requested_basis": "training_start",
        "assume_today": False,
        "date_problem": None,
        "path": "event_missing_date",
        "split": "split",
    }
    asked = await _run(FakeKnowledge([cur], [periods[0]]))
    assert asked.trace()["date_path"]["split"] == "no_current_edition"
    vague = await _run(FakeKnowledge([cur, nxt], periods), date_problem="ambiguous_date")
    assert vague.trace()["date_path"]["split"] == "reason_ambiguous_date"


async def test_trace_shows_current_search_when_the_nearest_document_is_guidance():
    """current 검색에서 가장 가까운 문서가 안내(비규범)면 판본을 나누지 않는다. 그 사실이 기록에 남는다."""
    faq = _p("FAQ", "f1", "v1", date(2025, 1, 1), None, basis="general_reference", role="guidance")
    cur = _p("DOC", "e1", "v1", date(2025, 1, 1), date(2026, 10, 1))
    nxt = _p("DOC", "e2", "v2", date(2026, 10, 1), None)
    k = FakeKnowledge(
        [faq, cur, nxt], [(date(2025, 1, 1), date(2026, 10, 1), "v1"), (date(2026, 10, 1), None, "v2")]
    )
    req = SearchRequest(query="외부교육 한도", date_basis="current")
    r = await RetrievalService(k).search(ACTOR, req, knowledge_as_of=NOW, snapshot_id="s")
    path = r.trace()["date_path"]
    assert r.edition_split is None and path["path"] == "current"
    assert path["top_hint"] == {"document_role": "guidance", "application_basis": "general_reference"}


def _general_two_editions():
    cur = _p("DOC", "e1", "v1", date(2025, 1, 1), date(2026, 10, 1), basis="general_reference")
    nxt = _p("DOC", "e2", "v2", date(2026, 10, 1), None, basis="general_reference")
    periods = [(date(2025, 1, 1), date(2026, 10, 1), "v1"), (date(2026, 10, 1), None, "v2")]
    return FakeKnowledge([cur, nxt], periods)


async def test_past_question_on_general_rule_is_split_by_edition():
    """D-86: 사건 기준 없는 규정이라도 날짜 없이 지난 일을 물으면 오늘 판본 하나로 답하지 않고 나눈다."""
    req = SearchRequest(query="연차 2시간 단위", date_basis="current", past_event=True)
    r = await RetrievalService(_general_two_editions()).search(
        ACTOR, req, knowledge_as_of=NOW, snapshot_id="s"
    )
    assert r.resolution == "resolved" and r.edition_split is not None
    assert r.edition_split["event_type"] == "explicit_date"
    assert {p.version for g in r.groups for p in g.passages} == {"v1", "v2"}
    assert r.trace()["date_path"]["path"] == "current_past_general"


async def test_present_question_on_general_rule_stays_current():
    req = SearchRequest(query="연차 2시간 단위", date_basis="current")
    r = await RetrievalService(_general_two_editions()).search(
        ACTOR, req, knowledge_as_of=NOW, snapshot_id="s"
    )
    assert r.edition_split is None and {p.version for g in r.groups for p in g.passages} == {"v2"}


async def test_event_basis_on_general_rule_splits_instead_of_asking():
    """D-86: 모델이 사건 기준(근무일)을 골랐어도 가까운 규범이 사건 기준 없는 규정이면 판본별로 준다."""
    req = SearchRequest(query="근태 정정 기한", date_basis="work_date", date_problem="missing_date")
    r = await RetrievalService(_general_two_editions()).search(
        ACTOR, req, knowledge_as_of=NOW, snapshot_id="s"
    )
    assert r.resolution == "resolved" and r.edition_split["event_type"] == "explicit_date"
    assert r.trace()["date_path"]["split"] == "split"
