"""APP-04 규칙 채점·judge 블라인딩(T-27·T-35 일부, D-51). 과금 없음, DB 없음."""

import pytest

from agent.app.eval_judge import answer_id, blind_order, judge_text, valid_verdict
from agent.app.eval_score import (
    PassageText,
    aggregate,
    anchor_hit,
    check_complete,
    numbers,
    paired,
    score_case,
)

SOURCES = {
    "PDF-031": {"access_policy": {"audience": "authenticated"}, "title": "외부교육비 지원 규정 [종전]"},
    "PDF-030": {"access_policy": {"audience": "authenticated"}, "title": "외부교육비 지원 규정"},
    "PDF-093": {
        "access_policy": {"audience": "restricted", "allowed_role_ids": ["dept_head"]},
        "title": "결재권한 위임 및 대결 기준",
    },
}
OLD = PassageText(
    "p-old",
    "PDF-031",
    frozenset({1}),
    "제3조 1회 과정 지원 한도는 100만 원으로 한다. 신청은 14일 전까지 한다.",
)
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
    "required_facts": ["1회 과정 한도는 100만 원", "신청은 14일 전까지"],
    "required_exceptions": [],
    "forbidden_claims": ["한도는 150만 원"],
    "evidence_sets": [
        [
            {"source_file_id": "PDF-031", "page": 1, "quote": "1회 과정 지원 한도는 100만 원으로"},
            {"source_file_id": "PDF-031", "page": 1, "quote": "신청은 14일 전까지 한다"},
        ]
    ],
    "hard_negative_anchors": [
        {"source_file_id": "PDF-030", "page": 1, "quote": "지원 한도는 150만 원으로", "same_group": False}
    ],
}
GOOD = "한도는 100만 원이고 신청은 14일 전까지입니다."


def result(strategy, answer, cited, pool, packed, outcome="answered", budget=4000, strict=True):
    return {
        "case_id": CASE["case_id"],
        "strategy": strategy,
        "strict": strict,
        "config": {"budget": budget},
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
                "retrieval_context": {"strategy": strategy},
                "evidence_trace": {"packed": [{"passage_id": p} for p in packed], "evidence_tokens": 50},
            }
        ],
        "tools": [{"name": "search_documents", "trace": {"pool": [{"passage_ids": pool}]}}],
    }


def score(r, case=CASE):
    return score_case(case, r, PASSAGES, SOURCES)


def test_numbers_unify_date_and_amount_forms_and_skip_article_numbers():
    for form in ("2026.10.01.", "2026년 10월 1일", "2026-10-01"):
        assert numbers(form) == {"2026", "10-01"}
    assert numbers("10월 1일") == {"10-01"}
    assert numbers("110만 원") == numbers("1,100,000원") == {"1100000"}
    assert numbers("3만원") == {"30000"} and numbers("80%") == {"80"}
    assert numbers("제3조 2항에 따라 5일") == {"5"}
    assert numbers("3조원") == {"3"}  # 금액 "조"는 조항 번호가 아니다


def test_anchor_matches_quote_page_and_file_with_whitespace_and_chunk_cuts():
    anchor = CASE["evidence_sets"][0][0]
    assert (
        anchor_hit(anchor, OLD) and not anchor_hit(anchor, NEW) and not anchor_hit({**anchor, "page": 2}, OLD)
    )
    spaced = PassageText("x", "PDF-031", frozenset({1}), "1회 과정 지원\n한도는 100만 원으로")  # 청크가 끊김
    assert anchor_hit(anchor, spaced)
    assert not anchor_hit(anchor, PassageText("y", "PDF-031", frozenset(), OLD.text))  # 쪽 정보 없음
    long_quote = {**anchor, "quote": "가" * 40 + "1회 과정 지원 한도는 100만 원으로" + "나" * 30}
    half = PassageText("z", "PDF-031", frozenset({1}), "가" * 40 + "다른 문장")
    assert not anchor_hit(long_quote, half)  # 인용 길이의 80% 미만 겹침은 맞지 않는다


def test_one_matching_citation_is_not_enough_when_facts_or_forbidden_numbers_fail():
    complete = score(result("raw", GOOD, ["p-old"], ["p-old"], ["p-old"]))
    assert complete["rule_correct"] and complete["rule_complete"] and complete["number_recall"] == 1.0
    # 근거 하나는 맞지만 금지 금액을 말한 답(검증 P1 재현): 정답이 아니다.
    forbidden = score(
        result("raw", "100만 원, 신청 14일 전. 현행은 150만 원", ["p-old"], ["p-old"], ["p-old"])
    )
    assert forbidden["forbidden_number_hit"] and not forbidden["rule_correct"]
    # 필수 사실 숫자(14일)를 빠뜨린 답도 정답이 아니다.
    missing = score(result("raw", "한도는 100만 원입니다.", ["p-old"], ["p-old"], ["p-old"]))
    assert missing["number_recall"] == 0.5 and not missing["rule_correct"]


def test_question_numbers_are_not_forbidden_numbers():
    # rule-v2(D-60): 사용자가 말한 금액을 답이 되짚어도 금지 주장이 아니다(holdout EV-E-002·EV-A-014 재현).
    case = {
        **CASE,
        "turns": ["수강료가 180만 원인 외부교육, 한도 넘는 부분은?"],
        "required_facts": ["1회 과정 한도는 100만 원"],
        "forbidden_claims": ["180만 원 전액 지원된다"],
    }
    answer = "수강료 180만 원 중 한도 100만 원까지만 지원되고 80만 원은 개인 부담입니다."
    scored = score_case(case, result("raw", answer, ["p-old"], ["p-old"], ["p-old"]), PASSAGES, SOURCES)
    assert not scored["forbidden_number_hit"] and scored["rule_correct"]
    assert scored["scoring_version"] == "rule-v2"
    # 질문에 없는 금지 숫자는 여전히 오답이다.
    wrong = score_case(
        {**case, "forbidden_claims": ["180만 원 전액, 150만 원 한도"]},
        result("raw", "한도는 150만 원이고 100만 원 이상은 재무 검토", ["p-old"], ["p-old"], ["p-old"]),
        PASSAGES,
        SOURCES,
    )
    assert wrong["forbidden_number_hit"] and not wrong["rule_correct"]


def test_hard_negatives_by_group_and_recall_split():
    wrong = score(result("wiki_assisted", "한도는 150만 원입니다.", ["p-new"], ["p-old", "p-new"], ["p-new"]))
    assert wrong["hard_negative_cited"] and wrong["hard_negative_in_context"] and not wrong["rule_correct"]
    assert wrong["recall_pool"] == 1.0 and wrong["recall_budget"] == 0.0 and wrong["found_not_packed"]
    same_group_case = {
        **CASE,
        "hard_negative_anchors": [
            {"source_file_id": "PDF-031", "page": 1, "quote": "신청은 14일 전까지 한다", "same_group": True}
        ],
        "required_facts": ["1회 과정 한도는 100만 원"],
        "evidence_sets": [[CASE["evidence_sets"][0][0]]],
    }
    ok = score(result("raw", "한도는 100만 원입니다.", ["p-old"], ["p-old"], ["p-old"]), same_group_case)
    # 같은 그룹 오답 위치는 정답과 함께 들어온다. 인용했어도 맞게 답했으면 오답으로 세지 않는다.
    assert ok["rule_correct"] and not ok["hard_negative_same_group_wrong"]


def test_empty_gold_is_na_leaks_include_pool_and_titles_and_unknown_is_unscorable():
    denied = {
        **CASE,
        "case_id": "EV-A-001",
        "category": "access",
        "expected_outcome": "insufficient_evidence",
        "evidence_sets": [],
        "required_facts": [],
        "forbidden_claims": ["대결자는 팀장이 지정"],
    }
    base = {
        **result("raw", "확인할 수 없습니다.", [], [], [], "insufficient_evidence"),
        "case_id": "EV-A-001",
    }
    clean = score(base, denied)
    assert clean["rule_correct"] and clean["recall_pool"] is None and clean["evidence_in_context"] is None
    pool_trace = {"name": "search_documents", "trace": {"pool": [{"passage_ids": ["p-sec"]}]}}
    in_pool = score({**base, "tools": [pool_trace]}, denied)
    assert in_pool["leaked_source_files"] == ["PDF-093"] and not in_pool["rule_correct"]
    titled_turn = {**base["turns"][0], "answer": "결재권한 위임 및 대결 기준은 볼 수 없습니다"}
    titled = score({**base, "turns": [titled_turn]}, denied)
    assert titled["leaked_titles"] and not titled["rule_correct"]
    unknown_trace = {"name": "s", "trace": {"pool": [{"passage_ids": ["p-x"]}]}}
    extra = {**PASSAGES, "p-x": PassageText("p-x", "PDF-999", frozenset({1}), "x")}
    unknown = score_case(denied, {**base, "tools": [unknown_trace]}, extra, SOURCES)
    assert unknown["unscorable_source_files"] == ["PDF-999"] and unknown["rule_correct"]


def test_errors_mismatch_and_strict_failures_stay_in_the_denominator():
    failed = score({**result("raw", "", [], [], []), "error": "run_exception:AppError", "turns": []})
    assert failed["error"] and not failed["rule_correct"]
    mismatch = result("raw", GOOD, ["p-old"], ["p-old"], ["p-old"])
    mismatch["runs"][0]["retrieval_context"]["strategy"] = "wiki_assisted"
    assert score(mismatch)["strategy_mismatch"] and not score(mismatch)["rule_correct"]
    strict = result("wiki_assisted", "근거가 부족합니다.", [], [], [], "insufficient_evidence")
    strict["tools"][0]["trace"]["strict_failure"] = "no_wiki_candidates"
    scored = score(strict)
    assert scored["over_abstain"] and scored["strict_failure"] and not scored["rule_correct"]
    summary = aggregate([failed, scored])
    assert summary["raw|strict|b4000"]["all"]["errors"] == 1
    assert summary["wiki_assisted|strict|b4000"]["all"]["strict_failures"] == 1


def test_configs_are_kept_apart_and_duplicates_or_missing_cases_are_reported():
    a4 = score(result("raw", GOOD, ["p-old"], ["p-old"], ["p-old"], budget=4000))
    a8 = score(result("raw", "한도는 150만 원", ["p-new"], ["p-new"], ["p-new"], budget=8000))
    b4 = score(result("wiki_assisted", "한도는 150만 원", ["p-new"], ["p-new"], ["p-new"], budget=4000))
    summary = aggregate([a4, a8, b4])
    assert summary["raw|strict|b4000"]["all"]["n"] == 1 and summary["raw|strict|b8000"]["all"]["n"] == 1
    pair = paired([a4, a8, b4], "raw|strict|b4000", "wiki_assisted|strict|b4000")
    assert (pair["pairs"], pair["a_better"], pair["b_better"]) == (1, 1, 0)
    with pytest.raises(ValueError):
        paired([a4, a4, b4], "raw|strict|b4000", "wiki_assisted|strict|b4000")
    report = check_complete([a4, a4], {"EV-R-001", "EV-R-002"})
    assert report["raw|strict|b4000"] == {
        "missing": ["EV-R-002"],
        "duplicated": ["EV-R-001"],
        "unexpected": [],
    }


def test_judge_ids_follow_content_not_position_and_input_hides_strategy():
    text = judge_text(CASE, "한도는 100만 원입니다.", ["인용 원문"], [])
    for word in ("raw", "wiki", "Wiki", "전략", "haiku", "Haiku"):
        assert word not in text
    assert "[gold 근거 원문]\n(없음)" in text  # 빈 목록 표시(연산 우선순위 버그 수정)
    items = [
        {"case_id": f"c{i}", "label": "raw|strict|b4000" if i % 2 else "wiki|strict|b4000", "text": f"t{i}"}
        for i in range(6)
    ]
    first, reversed_input = blind_order(items, 7), blind_order(list(reversed(items)), 7)
    assert [i["answer_id"] for i in first] == [i["answer_id"] for i in reversed_input]  # 입력 순서와 무관
    ids = {(i["case_id"], i["label"]): i["answer_id"] for i in first}
    assert ids[("c1", "raw|strict|b4000")] == answer_id("c1", "raw|strict|b4000", "t1", 7)
    assert len(set(ids.values())) == 6
    # 다른 답(다른 split·다른 실행 결과)은 같은 문항·설정이어도 다른 ID다.
    assert answer_id("c1", "raw|strict|b4000", "다른 답", 7) != ids[("c1", "raw|strict|b4000")]


def test_judge_verdict_shape_is_checked_against_gold_counts():
    good = {
        "facts": ["supported", "missing"],
        "exceptions": [],
        "forbidden_violated": False,
        "unsupported_claim": False,
        "abstained": False,
        "verdict": "partial",
        "reason": "r",
    }
    assert valid_verdict(good, CASE)
    assert not valid_verdict({**good, "facts": ["supported"]}, CASE)
    assert not valid_verdict({k: v for k, v in good.items() if k != "verdict"}, CASE)


def test_citing_a_separate_group_hard_negative_is_wrong_even_with_correct_numbers():
    mixed = score(result("raw", GOOD, ["p-old", "p-new"], ["p-old", "p-new"], ["p-old", "p-new"]))
    assert mixed["number_recall"] == 1.0 and not mixed["forbidden_number_hit"]
    assert mixed["hard_negative_cited"] and not mixed["rule_correct"]


def test_inline_citation_markers_are_not_scored_as_numbers():
    # D-76: 답 본문의 인용 표시는 숫자 사실로 세지 않는다(지우지 않으면 [c3-21]의 21이 금지 숫자로 걸린다).
    case = {**CASE, "forbidden_claims": ["신청은 21일 전까지"]}
    scored = score_case(
        case, result("raw", f"{GOOD} [c3-21]", ["p-old"], ["p-old"], ["p-old"]), PASSAGES, SOURCES
    )
    assert not scored["forbidden_number_hit"] and scored["rule_correct"]
