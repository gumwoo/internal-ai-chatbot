"""APP-04 채점: 실행 결과(eval_run)를 gold(eval/cases)와 규칙으로 대조한다(docs/13 측정 절, D-51).

주 판정은 규칙 채점이다(D-25/D-27): outcome, 인용 위치, 금액·날짜 같은 숫자 사실, 기권, 권한 누출,
hard negative, 후보 회수(Recall@pool)·실제 문맥 회수(Recall@budget·Hit@budget)·문맥 완결성.
의미 충실성(지원되지 않은 주장)은 judge 보조 판정으로 따로 붙인다(eval_judge).
근거 없음·권한 거절처럼 gold 근거가 빈 문항의 Recall은 N/A로 둔다(0이나 1로 채우지 않는다).

규칙 정답(rule_correct, D-51)
- answered: outcome=answered, gold 근거 하나 이상 인용, gold 사실의 두 자리 이상 숫자·날짜·금액을 모두 말함,
  금지 숫자 없음, 별도 그룹 hard negative 인용 없음, 권한 누출 없음.
  근거 집합을 모두 인용했으면 rule_complete.
- needs_clarification: outcome이 같고 누출 없음.
- insufficient_evidence: 기권(insufficient_evidence·no_results), 금지 숫자 없음, 누출 없음.
"""

import re
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

_SPACE = re.compile(r"\s+")
_DATE_FULL = re.compile(r"(\d{4})\s*(?:[.\-/]|년)\s*(\d{1,2})\s*(?:[.\-/]|월)\s*(\d{1,2})\s*일?\.?")
_DATE_MD = re.compile(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일")
_MAN = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*만\s*원?")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
# 조항 번호(제3조·2항·1호)의 숫자는 사실 숫자가 아니다. "3조원"(금액)은 지우지 않는다.
_ARTICLE = re.compile(r"제\s*\d+\s*[조항호]|\d+\s*[항호](?!\s*원)")
ABSTAIN = {"insufficient_evidence", "no_results"}
ROLES = {
    "emp-sales": {"employee"},
    "emp-dev": {"employee"},
    "head-sales": {"employee", "dept_head"},
    "hr-staff": {"employee", "hr_staff"},
    "it-support": {"employee", "it_support"},
}


def norm(text: str) -> str:
    return _SPACE.sub("", text or "")


# rule-v2(D-60): 질문에 나온 숫자는 금지 숫자로 보지 않는다(질문 금액을 되짚은 정답을 오답으로 세던 문제).
SCORING_VERSION = "rule-v2"


def numbers(text: str) -> set[str]:
    """숫자 사실 토큰. 날짜는 표기와 무관하게 'MM-DD'(연도는 따로), 'N만 원'은 원 단위 정수로 맞춘다."""
    found: set[str] = set()
    rest = _ARTICLE.sub(" ", text or "")

    def full(m: re.Match) -> str:
        found.update({m.group(1), f"{int(m.group(2)):02d}-{int(m.group(3)):02d}"})
        return " "

    def month_day(m: re.Match) -> str:
        found.add(f"{int(m.group(1)):02d}-{int(m.group(2)):02d}")
        return " "

    def man(m: re.Match) -> str:
        found.add(str(int(round(float(m.group(1).replace(",", "")) * 10000))))
        return " "

    rest = _DATE_FULL.sub(full, rest)
    rest = _DATE_MD.sub(month_day, rest)
    rest = _MAN.sub(man, rest)
    for n in _NUMBER.findall(rest):
        value = n.replace(",", "")
        if value.endswith(".0"):
            value = value[:-2]
        found.add(value)
    return found


@dataclass(frozen=True)
class PassageText:
    passage_id: str
    source_file_id: str
    pages: frozenset[int]
    text: str


def anchor_hit(anchor: dict[str, Any], passage: PassageText) -> bool:
    """gold 인용(PDF·쪽·정확 인용문)이 이 passage에 들어 있는가. 공백은 무시한다. 청크 경계에 걸쳐 잘린 경우를
    위해 인용 길이의 80% 이상(최소 8자)이 연속으로 겹치면 맞은 것으로 본다(parser alignment). 쪽 정보가 없는
    passage는 맞추지 않는다."""
    if anchor["source_file_id"] != passage.source_file_id or anchor.get("page") not in passage.pages:
        return False
    quote, text = norm(anchor["quote"]), norm(passage.text)
    if not quote:
        return False
    if quote in text:
        return True
    match = SequenceMatcher(None, quote, text, autojunk=False).find_longest_match(0, len(quote), 0, len(text))
    return match.size >= max(8, int(len(quote) * 0.8))


def _recall(evidence_sets: list[list[dict]], passages: list[PassageText]) -> tuple[float | None, bool | None]:
    """가장 잘 맞는 대체 근거 집합 기준의 회수율과 하나라도 맞았는지. gold가 비면 (None, None)."""
    if not evidence_sets:
        return None, None
    best, hit = 0.0, False
    for group in evidence_sets:
        found = [any(anchor_hit(a, p) for p in passages) for a in group]
        hit = hit or any(found)
        best = max(best, sum(found) / len(found))
    return best, hit


def config_label(result: dict[str, Any]) -> str:
    """집계 단위: 전략 × 엄격 모드 × 예산(같은 문항이 설정마다 한 번)."""
    config = result.get("config") or {}
    strict = "strict" if result.get("strict", True) else "operational"
    return f"{result['strategy']}|{strict}|b{config.get('budget', '?')}"


def _readable(source: dict[str, Any] | None, roles: set[str]) -> bool | None:
    """이 계정 역할로 읽을 수 있는가. 판정할 수 없는 정책(사용자·부서·capability 조건)·모르는 문서는 None."""
    if source is None:
        return None
    policy = source.get("access_policy") or {}
    if policy.get("audience") == "authenticated" and not policy.get("required_capabilities"):
        return True
    if set(policy) - {"audience", "allowed_role_ids"}:
        return None
    return bool(set(policy.get("allowed_role_ids") or []) & roles)


def score_case(
    case: dict[str, Any],
    result: dict[str, Any],
    passages: dict[str, PassageText],
    sources: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """한 문항 한 설정의 규칙 채점. passages: 결과에 나온 passage_id → 본문·쪽(DB에서 읽은 값)."""
    final = result["turns"][-1] if result.get("turns") else {}
    outcome = final.get("outcome")
    answer = final.get("answer") or ""
    error = result.get("error") or final.get("error")
    if not error and final and final.get("status") != 200:
        error = f"http_{final.get('status')}"
    if not final and not error:
        error = "no_turn"
    expected = case["expected_outcome"]
    outcome_ok = outcome in ABSTAIN if expected == "insufficient_evidence" else outcome == expected

    cited = [passages[c["passage_id"]] for c in final.get("citations", []) if c.get("passage_id") in passages]
    pool_ids = [
        p
        for tool in result.get("tools", [])
        for group in (tool.get("trace") or {}).get("pool", [])
        for p in group.get("passage_ids", [])
    ]
    traces = [(run.get("evidence_trace") or {}) for run in result.get("runs", [])]
    packed_ids = [p["passage_id"] for t in traces for p in (t.get("packed") or [])]
    pool = [passages[i] for i in dict.fromkeys(pool_ids) if i in passages]
    packed = [passages[i] for i in dict.fromkeys(packed_ids) if i in passages]
    recall_pool, hit_pool = _recall(case["evidence_sets"], pool)
    recall_budget, hit_budget = _recall(case["evidence_sets"], packed)
    citation_recall, citation_hit = _recall(case["evidence_sets"], cited)

    # 한 자리 수("1회 과정", "3단계")는 사실의 핵심인지 규칙으로 가릴 수 없어 judge에 맡긴다(D-51).
    all_fact_numbers = (
        set().union(*(numbers(f) for f in case["required_facts"])) if case["required_facts"] else set()
    )
    fact_numbers = {n for n in all_fact_numbers if len(n.replace("-", "")) >= 2}
    answer_numbers = numbers(answer)
    number_recall = (len(fact_numbers & answer_numbers) / len(fact_numbers)) if fact_numbers else None
    # 한 자리 수는 기권 안내·날짜에 흔해 금지 판정에서 뺀다(오답으로 몰지 않게).
    # 질문에 나온 숫자(사용자가 말한 금액·날짜)를 답이 되짚는 것은 금지 주장이 아니다(rule-v2).
    question_numbers = set().union(*(numbers(t) for t in case.get("turns") or []))
    forbidden_numbers = {
        n
        for n in set().union(*(numbers(f) for f in case["forbidden_claims"]))
        - all_fact_numbers
        - question_numbers
        if len(n.replace("-", "")) >= 2
    }
    forbidden_number_hit = bool(forbidden_numbers & answer_numbers)

    separate = [a for a in case["hard_negative_anchors"] if not a.get("same_group")]
    same_group = [a for a in case["hard_negative_anchors"] if a.get("same_group")]
    hn_cited = any(anchor_hit(a, p) for a in separate for p in cited)
    hn_in_context = any(anchor_hit(a, p) for a in separate for p in packed)
    # 같은 조항·표 안의 오답 위치는 정답과 함께 들어온다. 그것을 인용하고 틀린 경우만 센다(docs/13).
    hn_same_group_wrong = forbidden_number_hit and any(anchor_hit(a, p) for a in same_group for p in cited)

    roles = ROLES.get(case["actor"], set())
    seen_files = {p.source_file_id for p in cited + packed + pool}
    readable = {f: _readable(sources.get(f), roles) for f in seen_files}
    leaked = sorted(f for f, ok in readable.items() if ok is False)
    unscorable = sorted(f for f, ok in readable.items() if ok is None)
    hidden_titles = [
        s.get("title")
        for s in sources.values()
        if _readable(s, roles) is False and s.get("title") and norm(s["title"]) in norm(answer)
    ]
    leak = bool(leaked or hidden_titles)

    strategy_mismatch = any(
        (r.get("retrieval_context") or {}).get("strategy") not in (None, result["strategy"])
        for r in result.get("runs", [])
    )
    if expected == "answered":
        rule_correct = (
            outcome_ok
            and bool(citation_hit)
            and (number_recall is None or number_recall == 1.0)
            and not forbidden_number_hit
            and not hn_cited
        )
    elif expected == "needs_clarification":
        rule_correct = outcome_ok
    else:
        rule_correct = outcome_ok and not forbidden_number_hit
    rule_correct = bool(rule_correct) and not leak and not error and not strategy_mismatch
    config = result.get("config") or {}
    return {
        "case_id": case["case_id"],
        "scoring_version": SCORING_VERSION,
        "split": case["split"],
        "category": case["category"],
        "strategy": result["strategy"],
        "label": config_label(result),
        "budget": config.get("budget"),
        "expected_outcome": expected,
        "outcome": outcome,
        "error": error,
        "strategy_mismatch": strategy_mismatch,
        "outcome_ok": outcome_ok,
        "recall_pool": recall_pool,
        "hit_pool": hit_pool,
        "recall_budget": recall_budget,
        "hit_budget": hit_budget,
        "evidence_in_context": None if recall_budget is None else recall_budget == 1.0,
        "found_not_packed": None if recall_pool is None else (recall_pool or 0) > (recall_budget or 0),
        "citation_recall": citation_recall,
        "number_recall": number_recall,
        "forbidden_number_hit": forbidden_number_hit,
        "hard_negative_cited": hn_cited,
        "hard_negative_in_context": hn_in_context,
        "hard_negative_same_group_wrong": hn_same_group_wrong,
        "leaked_source_files": leaked,
        "leaked_titles": hidden_titles,
        "unscorable_source_files": unscorable,
        "over_abstain": expected == "answered" and outcome in ABSTAIN,
        "rule_correct": rule_correct,
        "rule_complete": rule_correct and expected == "answered" and citation_recall == 1.0,
        "strict_failure": any((t.get("trace") or {}).get("strict_failure") for t in result.get("tools", [])),
        "fallback": any((t.get("trace") or {}).get("fallback_reason") for t in result.get("tools", [])),
        "dropped_groups": sum(len(t.get("dropped_group_ids") or []) for t in traces),
        "required_group_missing": any(t.get("required_group_missing") for t in traces),
        "context_tokens": sum(t.get("evidence_tokens") or 0 for t in traces),
        "input_tokens": sum((r.get("usage") or {}).get("input_tokens") or 0 for r in result.get("runs", [])),
        "output_tokens": sum(
            (r.get("usage") or {}).get("output_tokens") or 0 for r in result.get("runs", [])
        ),
        "usage_complete": all((r.get("usage") or {}).get("complete") for r in result.get("runs", [])),
        # D-41 빈 첫 답 강제 재호출(tool_choice=any) 횟수.
        "empty_answer_retries": sum(
            (r.get("usage") or {}).get("empty_answer_retries") or 0 for r in result.get("runs", [])
        ),
        "model_ids": sorted({m for r in result.get("runs", []) for m in (r.get("model_ids") or [])}),
        "seconds": sum(t.get("seconds") or 0 for t in result.get("turns", [])),
        "searches": sum(1 for t in result.get("tools", []) if t.get("name") == "search_documents"),
    }


def _mean(values: list[Any]) -> float | None:
    present = [float(v) for v in values if v is not None]
    return round(sum(present) / len(present), 4) if present else None


def check_complete(scores: list[dict[str, Any]], expected_ids: set[str]) -> dict[str, Any]:
    """설정마다 기대 문항이 정확히 한 번씩 있는가(빠진 문항이 집계에서 조용히 사라지지 않게)."""
    by_label: dict[str, list[str]] = defaultdict(list)
    for s in scores:
        by_label[s["label"]].append(s["case_id"])
    report = {}
    for label, ids in by_label.items():
        counts: dict[str, int] = defaultdict(int)
        for i in ids:
            counts[i] += 1
        report[label] = {
            "missing": sorted(expected_ids - set(ids)),
            "duplicated": sorted(i for i, n in counts.items() if n > 1),
            "unexpected": sorted(set(ids) - expected_ids),
        }
    return report


def aggregate(scores: list[dict[str, Any]]) -> dict[str, Any]:
    """설정(전략×엄격×예산) × (전체·split·유형)별 집계. 값이 없는 지표는 N/A(None)와 표본 수를 같이 낸다."""
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for s in scores:
        for key in ("all", f"split:{s['split']}", f"category:{s['category']}"):
            buckets[(s["label"], key)].append(s)
    out: dict[str, Any] = {}
    for (label, key), rows in sorted(buckets.items()):
        answered = [r for r in rows if r["expected_outcome"] == "answered"]
        out.setdefault(label, {})[key] = {
            "n": len(rows),
            "rule_correct": _mean([r["rule_correct"] for r in rows]),
            "rule_complete": _mean([r["rule_complete"] for r in answered]),
            "outcome_ok": _mean([r["outcome_ok"] for r in rows]),
            "recall_pool": _mean([r["recall_pool"] for r in rows]),
            "recall_pool_n": sum(r["recall_pool"] is not None for r in rows),
            "recall_budget": _mean([r["recall_budget"] for r in rows]),
            "hit_budget": _mean([r["hit_budget"] for r in rows]),
            "evidence_in_context": _mean([r["evidence_in_context"] for r in rows]),
            "found_not_packed": sum(bool(r["found_not_packed"]) for r in rows),
            "citation_recall": _mean([r["citation_recall"] for r in rows]),
            "number_recall": _mean([r["number_recall"] for r in rows]),
            "number_recall_n": sum(r["number_recall"] is not None for r in rows),
            "over_abstain": _mean([r["over_abstain"] for r in answered]),
            "hard_negative_cited": _mean([r["hard_negative_cited"] for r in rows]),
            "hard_negative_in_context": _mean([r["hard_negative_in_context"] for r in rows]),
            "hard_negative_same_group_wrong": sum(r["hard_negative_same_group_wrong"] for r in rows),
            "forbidden_number_hit": _mean([r["forbidden_number_hit"] for r in rows]),
            "leaks": sum(bool(r["leaked_source_files"] or r["leaked_titles"]) for r in rows),
            "unscorable": sum(bool(r["unscorable_source_files"]) for r in rows),
            "errors": sum(bool(r["error"]) for r in rows),
            "strategy_mismatches": sum(r["strategy_mismatch"] for r in rows),
            "strict_failures": sum(r["strict_failure"] for r in rows),
            "fallbacks": sum(r["fallback"] for r in rows),
            "required_group_missing": sum(r["required_group_missing"] for r in rows),
            "dropped_groups": sum(r["dropped_groups"] for r in rows),
            "mean_context_tokens": _mean([r["context_tokens"] for r in rows]),
            "input_tokens": sum(r["input_tokens"] for r in rows),
            "output_tokens": sum(r["output_tokens"] for r in rows),
            "usage_incomplete": sum(not r["usage_complete"] for r in rows),
            "empty_answer_retries": sum(r["empty_answer_retries"] for r in rows),
            "mean_seconds": _mean([r["seconds"] for r in rows]),
        }
    return out


def paired(scores: list[dict[str, Any]], a: str, b: str) -> dict[str, Any]:
    """같은 문항의 두 설정 규칙 정답 비교(승·패·무). 같은 설정에 같은 문항이 두 번이면 거부한다."""
    by_case: dict[str, dict[str, dict]] = defaultdict(dict)
    for s in scores:
        if s["label"] not in (a, b):
            continue
        if s["label"] in by_case[s["case_id"]]:
            raise ValueError(f"{s['label']}에 {s['case_id']}가 두 번 있다")
        by_case[s["case_id"]][s["label"]] = s
    wins = losses = ties = 0
    changed = []
    for case_id, pair in sorted(by_case.items()):
        if a not in pair or b not in pair:
            continue
        x, y = pair[a]["rule_correct"], pair[b]["rule_correct"]
        if x == y:
            ties += 1
        elif y:
            wins += 1
            changed.append({"case_id": case_id, "better": b})
        else:
            losses += 1
            changed.append({"case_id": case_id, "better": a})
    return {
        "a": a,
        "b": b,
        "pairs": wins + losses + ties,
        "b_better": wins,
        "a_better": losses,
        "same": ties,
        "changed": changed,
    }
