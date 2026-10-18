"""APP-04 규칙 채점·judge 블라인딩(T-27·T-35 일부). 과금 없음, DB 없음."""

from agent.app.eval_judge import blind_order, judge_text
from agent.app.eval_score import PassageText, aggregate, anchor_hit, numbers, paired, score_case

SOURCES = {
    "PDF-031": {"access_policy": {"audience": "authenticated"}},
    "PDF-030": {"access_policy": {"audience": "authenticated"}},
    "PDF-093": {"access_policy": {"audience": "restricted", "allowed_role_ids": ["dept_head"]}},
}
OLD = PassageText("p-old", "PDF-031", frozenset({1}), "제3조 1회 과정 지원 한도는 100만 원으로 한다.")
NEW = PassageText("p-new", "PDF-030", frozenset({1}), "제5조 1회 과정 지원 한도는 150만 원으로 한다.")
SECRET = PassageText("p-sec", "PDF-093", frozenset({2}), "부서장 부재 시 대결자는 팀장이 지정한다.")
PASSAGES = {p.passage_id: p for p in (OLD, NEW, SECRET)}
CASE = {
    "case_id": "EV-R-001",
    "split": "dev",
    "category": "revision",
    "actor": "emp-sales",
    "turns": ["9월 29일 시작 교육 한도?"],
    "expected_outcome": "answered",
    "required_facts": ["1회 과정 한도는 100만 원"],
    "required_exceptions": [],
    "forbidden_claims": ["한도는 150만 원"],
    "evidence_sets": [
        [{"source_file_id": "PDF-031", "page": 1, "quote": "1회 과정 지원 한도는 100만 원으로"}]
    ],
    "hard_negative_anchors": [{"source_file_id": "PDF-030", "page": 1, "quote": "지원 한도는 150만 원으로"}],
}


def result(strategy, answer, cited, pool, packed, outcome="answered"):
    return {
        "case_id": CASE["case_id"],
        "strategy": strategy,
        "turns": [
            {
                "status": 200,
                "outcome": outcome,
                "answer": answer,
                "seconds": 1.0,
                "citations": [{"passage_id": p, "quote": PASSAGES[p].text} for p in cited],
            }
        ],
        "runs": [
            {
                "usage": {"input_tokens": 100, "output_tokens": 10, "complete": True},
                "evidence_trace": {"packed": [{"passage_id": p} for p in packed]},
            }
        ],
        "tools": [{"name": "search_documents", "trace": {"pool": [{"passage_ids": pool}]}}],
    }


def test_anchor_matches_quote_page_and_file_with_whitespace_and_chunk_cuts():
    anchor = CASE["evidence_sets"][0][0]
    assert anchor_hit(anchor, OLD)
    assert not anchor_hit(anchor, NEW)  # 다른 파일
    assert not anchor_hit({**anchor, "page": 2}, OLD)  # 다른 쪽
    spaced = PassageText(
        "x", "PDF-031", frozenset({1}), "1회 과정 지원\n한도는 100만 원"
    )  # 청크가 중간에서 끊김
    assert anchor_hit(anchor, spaced)
    assert numbers("1,100,000원과 80% 그리고 3일") == {"1100000", "80", "3"}
    assert numbers("제3조 2항에 따라 5일") == {"5"}  # 조항 번호는 사실 숫자가 아니다


def test_correct_answer_with_recall_and_hard_negative_flags():
    good = score_case(
        CASE,
        result("raw", "1회 과정 한도는 100만 원입니다.", ["p-old"], ["p-new", "p-old"], ["p-old"]),
        PASSAGES,
        SOURCES,
    )
    assert good["rule_correct"] and good["recall_pool"] == 1.0 and good["recall_budget"] == 1.0
    assert (
        good["number_recall"] == 1.0 and not good["hard_negative_cited"] and not good["forbidden_number_hit"]
    )
    # 후보에는 있었지만 예산 안에 못 들어가고 종전 대신 현행을 인용해 틀린 경우
    bad = score_case(
        CASE,
        result("wiki_assisted", "한도는 150만 원입니다.", ["p-new"], ["p-old", "p-new"], ["p-new"]),
        PASSAGES,
        SOURCES,
    )
    assert not bad["rule_correct"] and bad["recall_pool"] == 1.0 and bad["recall_budget"] == 0.0
    assert bad["hard_negative_cited"] and bad["forbidden_number_hit"]
    assert paired([good, bad]) == {
        "pairs": 1,
        "wiki_assisted_better": 0,
        "raw_better": 1,
        "same": 0,
        "changed": [{"case_id": "EV-R-001", "better": "raw"}],
    }


def test_empty_gold_recall_is_na_and_leak_makes_it_wrong():
    denied = {
        **CASE,
        "case_id": "EV-A-001",
        "category": "access",
        "expected_outcome": "insufficient_evidence",
        "evidence_sets": [],
        "required_facts": [],
        "forbidden_claims": ["대결자는 팀장이 지정"],
    }
    clean = score_case(
        denied,
        {**result("raw", "확인할 수 없습니다.", [], [], [], "insufficient_evidence"), "case_id": "EV-A-001"},
        PASSAGES,
        SOURCES,
    )
    assert clean["rule_correct"] and clean["recall_pool"] is None and clean["recall_budget"] is None
    leak = score_case(
        denied,
        {
            **result("raw", "확인할 수 없습니다.", [], [], ["p-sec"], "insufficient_evidence"),
            "case_id": "EV-A-001",
        },
        PASSAGES,
        SOURCES,
    )
    assert leak["leaked_source_files"] == ["PDF-093"] and not leak["rule_correct"]
    summary = aggregate([clean, leak])["raw"]["all"]
    assert summary["n"] == 2 and summary["leaks"] == 1 and summary["recall_pool"] is None
    assert summary["recall_pool_n"] == 0


def test_over_abstain_and_strict_failure_are_counted_not_dropped():
    case_result = result("wiki_assisted", "근거가 부족합니다.", [], [], [], "insufficient_evidence")
    case_result["tools"][0]["trace"]["strict_failure"] = "no_wiki_candidates"
    scored = score_case(CASE, case_result, PASSAGES, SOURCES)
    assert scored["over_abstain"] and scored["strict_failure"] and not scored["rule_correct"]
    assert aggregate([scored])["wiki_assisted"]["all"]["strict_failures"] == 1


def test_judge_input_hides_strategy_and_order_is_reproducible():
    text = judge_text(CASE, "한도는 100만 원입니다.", ["인용 원문"], ["gold 원문"])
    for word in ("raw", "wiki", "Wiki", "전략", "haiku", "Haiku"):
        assert word not in text
    items = [
        {"case_id": f"c{i}", "strategy": "raw" if i % 2 else "wiki_assisted", "text": "t"} for i in range(6)
    ]
    first, second = blind_order(items, 7), blind_order(items, 7)
    assert [i["answer_id"] for i in first] == [i["answer_id"] for i in second]
    assert [i["case_id"] for i in first] != [i["case_id"] for i in items]  # 섞였다
    assert len({i["answer_id"] for i in first}) == 6
