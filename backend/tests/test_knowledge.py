"""MOD-06 수집·MOD-05 게시·권한·근거(T-13, T-14, T-16, T-18). 과금 없음(결정적 임베딩).

manifest의 review_status=reviewed·available_from은 시험 전용 값이다(실제 검수 결과 아님, P-15 미정).
"""

import copy
import uuid
from datetime import date, datetime

import pytest
from sqlalchemy import text

from agent.app.corpus_ops import prepare_corpus
from agent.modules.identity_access.service import IdentityService, load_demo_org
from agent.modules.ingestion.manifest import validate_manifest
from agent.modules.knowledge.service import KnowledgeService, PublishRejected
from agent.shared.clock import FIXTURE_NOW, KST, FixedClock
from agent.shared.errors import AppError, ErrorCode
from tests.knowledge_fixtures import (
    BigramEmbedder,
    bigram_vector,
    make_test_manifest,
    pdf_root,
    prepared_corpus,
)

NOW = datetime(2026, 10, 16, 10, 0, tzinfo=KST)


@pytest.fixture
async def org(seeded_engine):
    await load_demo_org(seeded_engine, FIXTURE_NOW)
    identity = IdentityService(seeded_engine, FixedClock())
    operator = await identity.resolve_operator_actor("ops-admin")
    actors = {}
    for user, password in [
        ("emp-sales", "demo-emp-sales-1017"),
        ("hr-staff", "demo-hr-staff-1017"),
        ("head-sales", "demo-head-sales-1017"),
    ]:
        login = await identity.login(user, password)
        actors[user] = await identity.resolve_actor(login.token)
    return seeded_engine, operator, actors


async def _publish(engine, operator, manifest=None, label="test"):
    """manifest를 주지 않으면 공용 시험 corpus(캐시)를 게시한다."""
    if manifest is None:
        corpus, report = await prepared_corpus(label=label)
    else:
        corpus, report = await prepare_corpus(
            manifest,
            BigramEmbedder(),
            source_file_ids=None,
            label=label,
            scope="pilot",
            cache_dir=None,
            embed_per_minute=10**9,
        )
    knowledge = KnowledgeService(engine, FixedClock(), BigramEmbedder(), input_root=pdf_root())
    return knowledge, await knowledge.publish(operator, corpus), report


async def _scalar(engine, sql, **params):
    async with engine.connect() as conn:
        return await conn.scalar(text(sql), params)


def _query(knowledge_text: str):
    return bigram_vector(knowledge_text, 1536)


# --- T-18 manifest 검증 ---


def test_full_draft_manifest_has_release_shape():
    from agent.app.corpus_ops import MANIFEST_PATH
    from agent.modules.ingestion.manifest import load_manifest

    report = validate_manifest(load_manifest(MANIFEST_PATH), pdf_root(), release=True)
    assert report.ok, report.errors
    assert (report.files, report.document_keys, report.superseded) == (100, 91, 9)
    # D-36·D-40 검수본(review-manifest)이라 모두 게시 가능하다. 관계 형식 검사도 통과한다.
    assert report.not_publishable == []


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda m: m["files"].append(copy.deepcopy(m["files"][0])), "파일 ID 중복"),
        (lambda m: m["files"][0].__setitem__("filename", "../secret.pdf"), "입력 루트 밖"),
        (lambda m: m["files"][0].__setitem__("filename", "https://x/a.pdf"), "입력 루트 밖"),
        (lambda m: m["files"][0].__setitem__("filename", "C:/Windows/a.pdf"), "입력 루트 밖"),
        (lambda m: m["files"][0].__setitem__("filename", "없는_파일.pdf"), "파일 없음"),
        (lambda m: m["files"][0].__setitem__("sha256", "0" * 64), "SHA-256 불일치"),
        (lambda m: m["files"][0].pop("access_policy"), "필수 필드 없음"),
        (lambda m: m["files"][0].__setitem__("document_role", "law"), "document_role"),
        (lambda m: m["files"][0].__setitem__("application_basis", "today"), "application_basis"),
        (lambda m: m["files"][0].__setitem__("available_from", "2026-10-01T00:00:00"), "날짜 형식"),
        (lambda m: m["files"][0].__setitem__("available_from", None), "available_from 없음"),
    ],
)
def test_manifest_rejects_bad_entries(mutate, expected):
    manifest = make_test_manifest()
    assert validate_manifest(manifest, pdf_root(), release=False).ok
    mutate(manifest)
    report = validate_manifest(manifest, pdf_root(), release=False)
    assert not report.ok and any(expected in e for e in report.errors), report.errors


def test_manifest_rejects_overlapping_normative_windows_and_bad_supersession():
    manifest = make_test_manifest()
    old = next(e for e in manifest["files"] if e["source_file_id"] == "PDF-031")
    old["effective_to"] = "2026-10-02"  # 현행 ED-030(2026-10-01~)과 하루 겹침
    report = validate_manifest(manifest, pdf_root(), release=False)
    assert any("구간 겹침" in e for e in report.errors)
    manifest = make_test_manifest()
    current = next(e for e in manifest["files"] if e["source_file_id"] == "PDF-030")
    current["supersedes_source_file_id"] = "PDF-082"  # 다른 문서 키
    report = validate_manifest(manifest, pdf_root(), release=False)
    assert any("대체 대상이 같은 문서 키에 없음" in e for e in report.errors)


def test_release_shape_is_required_for_release():
    report = validate_manifest(make_test_manifest(), pdf_root(), release=True)
    assert any("100파일" in e for e in report.errors)


# --- 게시 게이트·원자성(T-14) ---


async def test_unreviewed_or_non_operator_publication_is_rejected(org):
    engine, operator, actors = org
    corpus, _ = await prepared_corpus(reviewed=False)
    knowledge = KnowledgeService(engine, FixedClock())
    with pytest.raises(PublishRejected) as rejected:
        await knowledge.publish(operator, corpus)
    assert any("검수되지 않음" in r for r in rejected.value.reasons)
    with pytest.raises(AppError) as denied:
        await knowledge.publish(actors["hr-staff"], corpus)
    assert denied.value.code is ErrorCode.ACTION_NOT_ALLOWED
    assert await knowledge.current_snapshot() is None
    assert await _scalar(engine, "SELECT count(*) FROM chunks") == 0


async def test_publish_switches_pointer_atomically_and_keeps_previous_on_failure(org, monkeypatch):
    engine, operator, _ = org
    knowledge, first, report = await _publish(engine, operator, label="v1")
    assert first.member_count == 8 and first.pointer_revision == 1
    assert all(not f["span_errors"] and not f["numbers_missing"] for f in report["files"].values())
    chunk_count = await _scalar(engine, "SELECT count(*) FROM chunks")
    assert chunk_count > 0
    assert await knowledge.current_snapshot() == first.snapshot_id

    # 두 번째 게시가 중간에 실패하면 포인터·행 수가 그대로다(준비본이 검색에 노출되지 않음).
    calls = {"n": 0}
    original = KnowledgeService._register

    async def flaky(self, conn, edition, now):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("디스크 가득 참")
        return await original(self, conn, edition, now)

    monkeypatch.setattr(KnowledgeService, "_register", flaky)
    corpus, _ = await prepared_corpus(label="v2")
    with pytest.raises(RuntimeError):
        await knowledge.publish(operator, corpus)
    assert await knowledge.current_snapshot() == first.snapshot_id
    assert await _scalar(engine, "SELECT count(*) FROM corpus_snapshots") == 1
    assert await _scalar(engine, "SELECT count(*) FROM chunks") == chunk_count

    # 같은 입력으로 다시 게시하면 판본·artifact를 재사용하고 포인터만 새 snapshot으로 바뀐다.
    monkeypatch.setattr(KnowledgeService, "_register", original)
    second = await knowledge.publish(operator, corpus)
    assert second.pointer_revision == 2 and second.snapshot_id != first.snapshot_id
    assert await _scalar(engine, "SELECT count(*) FROM chunks") == chunk_count
    assert await _scalar(engine, "SELECT count(*) FROM document_editions") == 8


async def test_changed_pdf_hash_for_same_file_id_is_rejected(org):
    engine, operator, _ = org
    knowledge, _, _ = await _publish(engine, operator)
    corpus, _ = await prepared_corpus(source_file_ids=("PDF-030",), label="x")
    edition = corpus.editions[0]
    tampered = type(corpus)(
        editions=(type(edition)(**{**edition.__dict__, "sha256": "f" * 64}),),
        manifest_hash=corpus.manifest_hash,
        config_hash=corpus.config_hash,
        label="x",
        scope="pilot",
    )
    with pytest.raises(PublishRejected):
        await knowledge.publish(operator, tampered)


# --- 검색 필터·권한(T-16) ---


async def test_search_applies_event_date_windows_and_knowledge_time(org):
    engine, operator, actors = org
    knowledge, published, _ = await _publish(engine, operator)
    query = _query("외부교육비 1회 과정당 지원 한도")
    actor = actors["emp-sales"]

    def keys(hits):
        return {h.source_file_id for h in hits}

    before = await knowledge.search(
        actor, published.snapshot_id, query, knowledge_as_of=NOW, as_of_date=date(2026, 9, 29), limit=50
    )
    after = await knowledge.search(
        actor, published.snapshot_id, query, knowledge_as_of=NOW, as_of_date=date(2026, 10, 5), limit=50
    )
    # 규범: 9/29 사건은 종전 ED-031, 10/5 사건은 현행 ED-030. 반대 판본은 섞이지 않는다.
    assert "PDF-031" in keys(before) and "PDF-030" not in keys(before)
    assert "PDF-030" in keys(after) and "PDF-031" not in keys(after)
    # 안내(GA-090, 시행 2026-10-06)는 사건 날짜와 무관하게 지식 시점으로 고른다.
    assert "PDF-090" in keys(before)
    early = await knowledge.search(
        actor,
        published.snapshot_id,
        query,
        knowledge_as_of=datetime(2026, 10, 5, 12, tzinfo=KST),
        as_of_date=date(2026, 9, 29),
        limit=50,
    )
    assert "PDF-090" not in keys(early)
    # 날짜가 없으면 규범은 나오지 않는다(오늘 날짜로 대신하지 않음).
    undated = await knowledge.search(
        actor, published.snapshot_id, query, knowledge_as_of=NOW, as_of_date=None, limit=50
    )
    assert all(h.document_role == "guidance" for h in undated)


async def test_restricted_documents_are_invisible_without_permission(org):
    engine, operator, actors = org
    knowledge, published, _ = await _publish(engine, operator)
    query = _query("부서 이동 및 직무 변경 발령 인수인계 근로조건")
    snapshot = published.snapshot_id

    async def files(actor):
        hits = await knowledge.search(
            actor, snapshot, query, knowledge_as_of=NOW, as_of_date=date(2026, 10, 16), limit=200
        )
        return {h.source_file_id for h in hits}

    employee, hr, head = actors["emp-sales"], actors["hr-staff"], actors["head-sales"]
    assert "PDF-013" not in await files(employee) and "PDF-093" not in await files(employee)
    assert "PDF-013" in await files(hr) and "PDF-093" not in await files(hr)
    assert {"PDF-013", "PDF-093"} <= await files(head)
    restricted = await knowledge.search(
        hr, snapshot, query, knowledge_as_of=NOW, as_of_date=date(2026, 10, 16), limit=200
    )
    passage = next(h for h in restricted if h.source_file_id == "PDF-013")
    # 근거·PDF 직접 조회: 권한 없음과 없는 ID가 같은 404.
    for call in (
        lambda: knowledge.get_evidence(employee, passage.passage_id),
        lambda: knowledge.get_evidence(employee, str(uuid.uuid4())),
        lambda: knowledge.get_evidence(employee, "not-a-uuid"),
        lambda: knowledge.open_source_pdf(employee, "PDF-013"),
        lambda: knowledge.open_source_pdf(employee, "PDF-999"),
    ):
        with pytest.raises(AppError) as error:
            await call()
        assert error.value.code is ErrorCode.RESOURCE_NOT_FOUND
    assert (await knowledge.get_evidence(hr, passage.passage_id)).text == passage.text
    assert (await knowledge.open_source_pdf(hr, "PDF-013")).name.startswith("HR-013")
    assert await knowledge.visible_document_keys(employee, {"DOC-013", "DOC-030"}) == {"DOC-030"}

    # ACL 변경은 바로 반영된다(과거 답변·캐시 재검증의 기준).
    revision = await knowledge.set_acl(
        operator, "DOC-013", {"audience": "restricted", "allowed_role_ids": ["auditor"]}
    )
    assert revision == 2
    assert "PDF-013" not in await files(hr)
    with pytest.raises(AppError):
        await knowledge.get_evidence(hr, passage.passage_id)
    assert await _scalar(engine, "SELECT count(*) FROM acl_audit WHERE document_key = 'DOC-013'") == 1


async def test_unknown_or_malformed_stored_policy_denies_everyone(org):
    engine, operator, actors = org
    knowledge, published, _ = await _publish(engine, operator)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                'UPDATE resource_acl SET policy = \'{"audience": "everyone"}\''
                " WHERE document_key = 'DOC-030'"
            )
        )
        await conn.execute(
            text(
                'UPDATE resource_acl SET policy = \'{"audience": "authenticated", "bonus": 1}\''
                " WHERE document_key = 'DOC-081'"
            )
        )
    hits = await knowledge.search(
        actors["head-sales"],
        published.snapshot_id,
        _query("외부교육비 출장비"),
        knowledge_as_of=NOW,
        as_of_date=date(2026, 10, 16),
        limit=200,
    )
    assert not {"DOC-030", "DOC-081"} & {h.document_key for h in hits}
    with pytest.raises(AppError):
        await knowledge.set_acl(operator, "DOC-030", {"audience": "public"})


async def test_actor_without_search_capability_sees_nothing(org):
    from agent.shared.actor import ActorContext

    engine, operator, _ = org
    knowledge, published, _ = await _publish(engine, operator)
    trainee = ActorContext("x", ("dept-sales",), ("employee",), frozenset({"training.read"}), 1, "test_stub")
    hits = await knowledge.search(
        trainee,
        published.snapshot_id,
        _query("출장비"),
        knowledge_as_of=NOW,
        as_of_date=date(2026, 10, 16),
        limit=20,
    )
    assert hits == []


# --- 원문 provenance(T-13) ---


async def test_passages_trace_back_to_page_text_and_tables_keep_headers(org):
    engine, operator, actors = org
    knowledge, published, _ = await _publish(engine, operator)
    hits = await knowledge.search(
        actors["emp-sales"],
        published.snapshot_id,
        _query("자율·선택 외부교육 지원 한도 1회 과정 한도 연간 개인 한도"),
        knowledge_as_of=NOW,
        as_of_date=date(2026, 10, 5),
        limit=30,
    )
    table = next(
        h
        for h in hits
        if h.source_file_id == "PDF-030" and h.kind == "table" and "별표 1" in (h.heading or "")
    )
    assert table.text.splitlines()[:2] == [
        "별표 1. 자율·선택 외부교육 지원 한도(2026.10.01. 적용)",
        "구분 | 지원 범위 | 한도",
    ]
    async with engine.connect() as conn:
        for span in table.page_spans:
            page_text = await conn.scalar(
                text(
                    "SELECT dp.text FROM document_pages dp JOIN chunks c ON c.artifact_id = dp.artifact_id"
                    " WHERE c.passage_id = :p AND dp.page = :page"
                ),
                {"p": uuid.UUID(table.passage_id), "page": span["page"]},
            )
            assert page_text[span["start"] : span["end"]] in table.text
    # 페이지를 넘는 표(IT-037 표 1)는 같은 support_group으로 이어진다.
    it_hits = await knowledge.search(
        actors["emp-sales"],
        published.snapshot_id,
        _query("티켓 상태 정의 접수 분류중 진행중 보류 사용자확인 해결 종결"),
        knowledge_as_of=NOW,
        as_of_date=date(2026, 10, 16),
        limit=40,
    )
    status = next(h for h in it_hits if h.source_file_id == "PDF-037" and h.heading == "표 1. 티켓 상태 정의")
    group = await knowledge.support_group(actors["emp-sales"], status)
    assert sorted({s["page"] for g in group for s in g.page_spans}) == [2, 3]
    assert all(g.text.splitlines()[1] == "상태 | 의미 | 필수 처리" for g in group)


async def test_embedding_failure_is_reported_not_published_as_partial(org):
    from agent.modules.ingestion.embedding import EmbeddingIncomplete
    from agent.modules.model_integration.ports import ModelCallError, ModelFailure

    _, _, _ = org
    failing = BigramEmbedder(fail_with=ModelCallError(ModelFailure.UPSTREAM_UNAVAILABLE))
    with pytest.raises(EmbeddingIncomplete):
        await prepare_corpus(
            make_test_manifest(("PDF-030",)),
            failing,
            source_file_ids=None,
            label="x",
            scope="pilot",
            cache_dir=None,
        )


# --- 검증 에이전트 지적 회귀(2026-10-18) ---


async def test_republish_cannot_change_published_edition_metadata(org):
    """P1: 게시된 판본의 메타데이터를 바꾸는 재게시는 거절된다. 과거 snapshot의 결과가 바뀌지 않는다."""
    engine, operator, actors = org
    knowledge, first, _ = await _publish(engine, operator, label="v1")
    manifest = make_test_manifest()
    for entry in manifest["files"]:
        if entry["source_file_id"] == "PDF-031":
            entry["effective_to"] = "2026-09-15"
        if entry["source_file_id"] == "PDF-030":
            entry["effective_from"] = "2026-09-15"
    corpus, _ = await prepare_corpus(
        manifest,
        BigramEmbedder(),
        source_file_ids=None,
        label="v2",
        scope="pilot",
        cache_dir=None,
        embed_per_minute=10**9,
    )
    with pytest.raises(PublishRejected) as rejected:
        await knowledge.publish(operator, corpus)
    assert any("메타데이터는 바꿀 수 없음" in r for r in rejected.value.reasons)
    hits = await knowledge.search(
        actors["emp-sales"],
        first.snapshot_id,
        _query("외부교육비 1회 과정 지원 한도"),
        knowledge_as_of=NOW,
        as_of_date=date(2026, 9, 20),
        limit=50,
    )
    files = {h.source_file_id for h in hits}
    assert "PDF-031" in files and "PDF-030" not in files
    assert await knowledge.current_snapshot() == first.snapshot_id


async def test_manifest_acl_change_is_rejected_not_ignored(org):
    engine, operator, _ = org
    knowledge, _, _ = await _publish(engine, operator)
    manifest = make_test_manifest(("PDF-030",))
    manifest["files"][0]["access_policy"] = {"audience": "restricted", "allowed_role_ids": ["auditor"]}
    corpus, _ = await prepare_corpus(
        manifest,
        BigramEmbedder(),
        source_file_ids=None,
        label="x",
        scope="pilot",
        cache_dir=None,
        embed_per_minute=10**9,
    )
    with pytest.raises(PublishRejected) as rejected:
        await knowledge.publish(operator, corpus)
    assert any("set_acl" in r for r in rejected.value.reasons)
    pair = make_test_manifest(("PDF-030", "PDF-031"))
    pair["files"][1]["access_policy"] = {"audience": "restricted", "allowed_role_ids": ["auditor"]}
    report = validate_manifest(pair, pdf_root(), release=False)
    assert any("access_policy가 다름" in e for e in report.errors)


def test_guidance_pair_requires_non_overlapping_windows_and_quality_blocks():
    from dataclasses import replace

    from agent.modules.ingestion.manifest import to_metadata
    from agent.modules.knowledge.service import validate_metadata

    manifest = make_test_manifest(("PDF-090",))
    base = to_metadata(manifest["files"][0])
    old = replace(base, source_file_id="PDF-X1", version="0.9")
    new = replace(base, source_file_id="PDF-X2", version="1.0")
    assert any("guidance_valid 구간이 없음" in p for p in validate_metadata([old, new]))
    t1 = datetime(2025, 4, 1, tzinfo=KST)
    t2 = datetime(2026, 10, 1, tzinfo=KST)
    ok = [replace(old, guidance_valid_from=t1, guidance_valid_to=t2), replace(new, guidance_valid_from=t2)]
    assert validate_metadata(ok) == []
    overlap = [
        replace(old, guidance_valid_from=t1, guidance_valid_to=t2),
        replace(new, guidance_valid_from=t1),
    ]
    assert any("구간 겹침" in p for p in validate_metadata(overlap))
    inverted = [replace(old, guidance_valid_from=t2, guidance_valid_to=t1)]
    assert any("역전" in p for p in validate_metadata(inverted))


async def test_parse_quality_problems_block_publication(org):
    from dataclasses import replace

    engine, operator, _ = org
    corpus, _ = await prepared_corpus(source_file_ids=("PDF-030",), label="q")
    bad = replace(
        corpus, editions=(replace(corpus.editions[0], quality={"empty_pages": [2], "numbers_missing": 3}),)
    )
    with pytest.raises(PublishRejected) as rejected:
        await KnowledgeService(engine, FixedClock()).publish(operator, bad)
    assert any("empty_pages" in r for r in rejected.value.reasons)
    assert any("numbers_missing" in r for r in rejected.value.reasons)


def test_addendum_effective_article_is_its_own_cited_unit():
    """부칙 "제1조(시행일) 이 규정은 …시행한다."가 경로가 아니라 근거 청크로 남는다(종전 8건)."""
    from agent.app.corpus_ops import INPUT_ROOT
    from agent.modules.ingestion.chunker import chunk_document
    from agent.modules.ingestion.parser import parse_pdf

    document = parse_pdf(next(INPUT_ROOT.glob("ED-031_*.pdf")))
    chunks = chunk_document(document, "외부교육비 지원 규정 [종전]")
    assert any("2025년 01월 01일부터 시행한다" in c.text for c in chunks)
    assert not any("시행한다" in part for c in chunks for part in c.section_path)


async def test_withdrawn_document_is_not_visible_for_history(org):
    engine, operator, actors = org
    knowledge, _, _ = await _publish(engine, operator)
    assert await knowledge.visible_document_keys(actors["emp-sales"], {"DOC-090"}) == {"DOC-090"}
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE document_editions SET edition_state = 'withdrawn' WHERE document_key = 'DOC-090'")
        )
    assert await knowledge.visible_document_keys(actors["emp-sales"], {"DOC-090"}) == set()
    hits = await knowledge.search(
        actors["emp-sales"],
        (await knowledge.current_snapshot()),
        _query("출장 교육 비용 정산 FAQ"),
        knowledge_as_of=NOW,
        as_of_date=date(2026, 10, 16),
        limit=50,
    )
    assert "PDF-090" not in {h.source_file_id for h in hits}
    passage = await _scalar(
        engine,
        "SELECT c.passage_id FROM chunks c JOIN parsed_artifacts p ON p.artifact_id = c.artifact_id"
        " JOIN document_editions e ON e.edition_id = p.edition_id WHERE e.document_key = 'DOC-090' LIMIT 1",
    )
    with pytest.raises(AppError):
        await knowledge.get_evidence(actors["emp-sales"], str(passage))
    with pytest.raises(AppError):
        await knowledge.open_source_pdf(actors["emp-sales"], "PDF-090")


async def test_each_acl_layer_blocks_on_its_own(org, monkeypatch):
    """SQL 선필터와 2차 정책 판정이 각각 따로 제한 문서를 막는다(한쪽이 고장 나도 새지 않음)."""
    import agent.modules.knowledge.service as ks

    engine, operator, actors = org
    knowledge, published, _ = await _publish(engine, operator)
    employee = actors["emp-sales"]
    query = _query("부서 이동 및 직무 변경 발령 인수인계 근로조건")
    restricted = await _scalar(
        engine,
        "SELECT c.passage_id FROM chunks c JOIN parsed_artifacts p ON p.artifact_id = c.artifact_id"
        " JOIN document_editions e ON e.edition_id = p.edition_id WHERE e.source_file_id = 'PDF-013' LIMIT 1",
    )
    # 2차 판정을 끄면 SQL만으로 막아야 한다.
    monkeypatch.setattr(ks, "_row_allowed", lambda actor, policy: True)
    hits = await knowledge.search(
        employee, published.snapshot_id, query, knowledge_as_of=NOW, as_of_date=date(2026, 10, 16), limit=200
    )
    assert "PDF-013" not in {h.source_file_id for h in hits}
    with pytest.raises(AppError):
        await knowledge.get_evidence(employee, str(restricted))
    with pytest.raises(AppError):
        await knowledge.open_source_pdf(employee, "PDF-013")
    monkeypatch.undo()
    # SQL을 끄면(모든 행 허용) 2차 판정만으로 막아야 한다.
    monkeypatch.setattr(ks, "_ACL_CLAUSE", "")
    monkeypatch.setattr(ks, "_SEARCH_SQL", ks._SEARCH_SQL.replace(ks._ACL_CLAUSE, ""))
    hits = await knowledge.search(
        employee, published.snapshot_id, query, knowledge_as_of=NOW, as_of_date=date(2026, 10, 16), limit=200
    )
    assert "PDF-013" not in {h.source_file_id for h in hits}
    assert [h.rank for h in hits] == list(range(1, len(hits) + 1))  # 숨긴 결과로 순위가 비지 않는다


async def test_end_date_is_exclusive_on_boundary(org):
    engine, operator, actors = org
    knowledge, published, _ = await _publish(engine, operator)
    query = _query("외부교육비 1회 과정 지원 한도")

    async def files(day):
        hits = await knowledge.search(
            actors["emp-sales"], published.snapshot_id, query, knowledge_as_of=NOW, as_of_date=day, limit=50
        )
        return {h.source_file_id for h in hits} & {"PDF-030", "PDF-031"}

    assert await files(date(2026, 9, 30)) == {"PDF-031"}
    assert await files(date(2026, 10, 1)) == {"PDF-030"}  # 종전 effective_to=10/1은 제외 날짜


async def test_pdf_with_wrong_hash_or_path_is_not_served(org):
    engine, operator, actors = org
    knowledge, _, _ = await _publish(engine, operator)
    async with engine.begin() as conn:
        # 공개 문서 행이 다른(제한) PDF 파일을 가리키게 조작
        restricted_name = await conn.scalar(
            text("SELECT filename FROM source_files WHERE source_file_id = 'PDF-013'")
        )
        await conn.execute(
            text("UPDATE source_files SET filename = :f WHERE source_file_id = 'PDF-030'"),
            {"f": restricted_name},
        )
        await conn.execute(
            text(
                "UPDATE source_files SET filename = '../../backend/pyproject.toml'"
                " WHERE source_file_id = 'PDF-081'"
            )
        )
    for file_id in ("PDF-030", "PDF-081"):
        with pytest.raises(AppError) as error:
            await knowledge.open_source_pdf(actors["emp-sales"], file_id)
        assert error.value.code is ErrorCode.RESOURCE_NOT_FOUND


async def test_support_group_stays_inside_its_snapshot(org):
    from dataclasses import replace

    engine, operator, actors = org
    knowledge, published, _ = await _publish(engine, operator)
    hits = await knowledge.search(
        actors["emp-sales"],
        published.snapshot_id,
        _query("외부교육비"),
        knowledge_as_of=NOW,
        as_of_date=date(2026, 10, 5),
        limit=5,
    )
    other = replace(hits[0], corpus_snapshot_id=str(uuid.uuid4()))
    assert await knowledge.support_group(actors["emp-sales"], other) == []


def test_manifest_rejects_alias_paths_and_duplicate_names():
    manifest = make_test_manifest()
    manifest["files"][0]["filename"] = "./" + manifest["files"][0]["filename"]
    assert any("입력 루트 밖" in e for e in validate_manifest(manifest, pdf_root(), release=False).errors)
    manifest = make_test_manifest()
    dup = copy.deepcopy(manifest["files"][1])
    dup["source_file_id"] = "PDF-999"
    manifest["files"].append(dup)
    errors = validate_manifest(manifest, pdf_root(), release=False).errors
    assert any("파일명 중복" in e for e in errors) and any("다른 ID로 중복" in e for e in errors)


async def test_embedding_cache_reuse_dedupe_and_rate_window(tmp_path):
    from agent.modules.ingestion.embedding import EmbeddingCache, embed_texts
    from agent.modules.model_integration.ports import EmbeddingConfig

    config = EmbeddingConfig("m", 8, "document")
    sleeps: list[float] = []

    async def sleep(seconds):
        sleeps.append(seconds)

    embedder = BigramEmbedder()
    cache = EmbeddingCache.open(tmp_path, config, "f")
    texts = [f"문장 {i}" for i in range(5)] + ["문장 0"]
    vectors, report = await embed_texts(
        embedder, texts, config, cache, per_minute=2, sleep=sleep, clock=lambda: 0.0
    )
    assert len(vectors) == 6 and vectors[5] == vectors[0]
    assert embedder.inputs == 5 and report.requests == 3  # 중복 1건 제외, 분당 2건 → 묶음 2개씩
    assert len(sleeps) == 2  # 분당 한도를 넘기지 않게 기다린다
    # 깨진 마지막 줄이 있어도 캐시를 열고, 남은 벡터를 재사용한다.
    with cache.path.open("a", encoding="utf-8") as handle:
        handle.write('{"key": "x", "vec')
    again = EmbeddingCache.open(tmp_path, config, "f")
    _, report2 = await embed_texts(BigramEmbedder(), texts, config, again, sleep=sleep, clock=lambda: 0.0)
    assert report2.cached == 6 and report2.requested == 0


async def test_rate_limit_waits_reset_after_success():
    from agent.modules.ingestion.embedding import EmbeddingIncomplete, embed_texts
    from agent.modules.model_integration.ports import EmbeddingConfig, ModelCallError, ModelFailure

    class Flaky(BigramEmbedder):
        def __init__(self, pattern):
            super().__init__()
            self.pattern = list(pattern)

        async def embed_once(self, texts, config, timeout_s):
            if self.pattern and self.pattern.pop(0):
                raise ModelCallError(ModelFailure.RATE_LIMITED)
            return await super().embed_once(texts, config, timeout_s)

    async def sleep(seconds):
        return None

    config = EmbeddingConfig("m", 8, "document")
    texts = [f"t{i}" for i in range(4)]
    # 429와 성공이 번갈아 와도(연속 2회 이하) 끝까지 받는다.
    vectors, report = await embed_texts(
        Flaky([1, 1, 0, 1, 1, 0, 1, 1, 0, 1, 1, 0]),
        texts,
        config,
        None,
        batch_size=1,
        sleep=sleep,
        clock=lambda: 0.0,
        max_rate_limit_waits=2,
    )
    assert len(vectors) == 4 and report.rate_limited == 8
    with pytest.raises(EmbeddingIncomplete) as error:
        await embed_texts(
            Flaky([0, 1, 1, 1]),
            texts,
            config,
            None,
            batch_size=1,
            sleep=sleep,
            clock=lambda: 0.0,
            max_rate_limit_waits=2,
        )
    assert (error.value.done, error.value.total) == (1, 4)


def test_publish_side_metadata_check_rejects_overlapping_normative_windows():
    """manifest 검증을 건너뛰어도 게시 쪽 검사(validate_metadata)가 겹치는 규범 구간을 거절한다."""
    from dataclasses import replace

    from agent.modules.ingestion.manifest import to_metadata
    from agent.modules.knowledge.service import validate_metadata

    manifest = make_test_manifest(("PDF-030", "PDF-031"))
    metas = [to_metadata(e) for e in manifest["files"]]
    assert validate_metadata(metas) == []
    old = next(m for m in metas if m.source_file_id == "PDF-031")
    overlapped = [replace(old, effective_to=date(2026, 10, 2)) if m is old else m for m in metas]
    assert any("규범 적용 구간 겹침" in p for p in validate_metadata(overlapped))
    open_ended = [replace(old, effective_to=None) if m is old else m for m in metas]
    assert any("규범 적용 구간 겹침" in p for p in validate_metadata(open_ended))
