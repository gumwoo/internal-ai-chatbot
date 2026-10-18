"""APP-04 채점: 실행 결과(eval_run)를 gold(eval/cases)와 규칙으로 대조한다(docs/13 측정 절).

주 판정은 규칙 채점이다(D-25/D-27): outcome, 인용 위치, 금액·날짜 같은 숫자 사실, 기권, 권한 누출,
hard negative 인용, 후보 회수(Recall@pool)와 실제 문맥 회수(Recall@budget·Hit@budget).
의미 충실성(지원되지 않은 주장)은 judge 보조 판정으로 따로 붙인다(eval_judge).
judge가 없어도 규칙 채점은 완결된다.
근거 없음·권한 거절처럼 gold 근거가 빈 문항의 Recall은 N/A로 둔다(0이나 1로 채우지 않는다).
"""

import re
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

_SPACE = re.compile(r"\s+")
# 숫자 사실: 금액·비율·횟수·날짜 등. "1,100,000원"·"80%"·"3일"·"2026-10-01"·"10월 1일".
_NUMBER = re.compile(r"\d[\d,.]*")
# 조항 번호(제3조·2항·1호)의 숫자는 사실 숫자로 보지 않는다.
_ARTICLE = re.compile(r"(?:제\s*)?\d+\s*[조항호]")
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


def numbers(text: str) -> set[str]:
    cleaned = _ARTICLE.sub(" ", text or "")
    return {n.replace(",", "").rstrip(".") for n in _NUMBER.findall(cleaned) if n.strip(",.")}


@dataclass(frozen=True)
class PassageText:
    passage_id: str
    source_file_id: str
    pages: frozenset[int]
    text: str


def anchor_hit(anchor: dict[str, Any], passage: PassageText) -> bool:
    """gold 인용(PDF·쪽·정확 인용문)이 이 passage에 들어 있는가. 공백은 무시하고, 청크 경계에 걸쳐 잘린
    경우를 위해 인용의 80% 이상(최대 40자 기준)이 연속으로 겹치면 맞은 것으로 본다(parser alignment)."""
    if anchor["source_file_id"] != passage.source_file_id:
        return False
    if passage.pages and anchor.get("page") not in passage.pages:
        return False
    quote, text = norm(anchor["quote"]), norm(passage.text)
    if not quote:
        return False
    if quote in text:
        return True
    match = SequenceMatcher(None, quote, text, autojunk=False).find_longest_match(0, len(quote), 0, len(text))
    return match.size >= max(8, int(min(len(quote), 40) * 0.8))


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


def score_case(
    case: dict[str, Any],
    result: dict[str, Any],
    passages: dict[str, PassageText],
    sources: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """한 문항 한 전략의 규칙 채점. passages: 결과에 나온 passage_id → 본문·쪽(DB에서 읽은 값)."""
    final = result["turns"][-1] if result["turns"] else {}
    outcome = final.get("outcome")
    answer = final.get("answer") or ""
    error = final.get("error") or (None if final.get("status") == 200 else f"http_{final.get('status')}")
    expected = case["expected_outcome"]
    if expected == "insufficient_evidence":
        outcome_ok = outcome in ABSTAIN
    else:
        outcome_ok = outcome == expected

    cited = [passages[c["passage_id"]] for c in final.get("citations", []) if c.get("passage_id") in passages]
    pool_ids: list[str] = []
    for tool in result.get("tools", []):
        for group in (tool.get("trace") or {}).get("pool", []):
            pool_ids.extend(group.get("passage_ids", []))
    packed_ids = [
        p["passage_id"]
        for run in result.get("runs", [])
        for p in ((run.get("evidence_trace") or {}).get("packed") or [])
    ]
    pool = [passages[i] for i in dict.fromkeys(pool_ids) if i in passages]
    packed = [passages[i] for i in dict.fromkeys(packed_ids) if i in passages]
    recall_pool, _ = _recall(case["evidence_sets"], pool)
    recall_budget, hit_budget = _recall(case["evidence_sets"], packed)
    citation_recall, _ = _recall(case["evidence_sets"], cited)

    # 숫자 사실: gold 사실에 있는 숫자가 답에 있는가(금액·기한·비율). 숫자 없는 사실은 judge가 본다.
    fact_numbers = (
        set().union(*(numbers(f) for f in case["required_facts"])) if case["required_facts"] else set()
    )
    answer_numbers = numbers(answer)
    number_recall = (len(fact_numbers & answer_numbers) / len(fact_numbers)) if fact_numbers else None
    forbidden_numbers = set().union(*(numbers(f) for f in case["forbidden_claims"])) - fact_numbers
    forbidden_number_hit = bool(forbidden_numbers & answer_numbers)

    hard_negative_cited = any(anchor_hit(a, p) for a in case["hard_negative_anchors"] for p in cited)
    roles = ROLES.get(case["actor"], set())
    leaked = sorted(
        {p.source_file_id for p in cited + packed if not _readable(sources.get(p.source_file_id), roles)}
    )
    answered_ok = expected == "answered" and outcome_ok and (citation_recall or 0) > 0
    abstain_ok = expected != "answered" and outcome_ok and not forbidden_number_hit and not leaked
    return {
        "case_id": case["case_id"],
        "split": case["split"],
        "category": case["category"],
        "strategy": result["strategy"],
        "expected_outcome": expected,
        "outcome": outcome,
        "error": error,
        "outcome_ok": outcome_ok,
        "recall_pool": recall_pool,
        "recall_budget": recall_budget,
        "hit_budget": hit_budget,
        "citation_recall": citation_recall,
        "number_recall": number_recall,
        "forbidden_number_hit": forbidden_number_hit,
        "hard_negative_cited": hard_negative_cited,
        "leaked_source_files": leaked,
        "over_abstain": expected == "answered" and outcome in ABSTAIN,
        "rule_correct": bool(answered_ok or abstain_ok) and not leaked,
        "strict_failure": any((t.get("trace") or {}).get("strict_failure") for t in result.get("tools", [])),
        "fallback": any((t.get("trace") or {}).get("fallback_reason") for t in result.get("tools", [])),
        "input_tokens": sum((r.get("usage") or {}).get("input_tokens") or 0 for r in result.get("runs", [])),
        "output_tokens": sum(
            (r.get("usage") or {}).get("output_tokens") or 0 for r in result.get("runs", [])
        ),
        "usage_complete": all((r.get("usage") or {}).get("complete") for r in result.get("runs", [])),
        "seconds": sum(t.get("seconds") or 0 for t in result["turns"]),
        "searches": sum(1 for t in result.get("tools", []) if t.get("name") == "search_documents"),
    }


def _readable(source: dict[str, Any] | None, roles: set[str]) -> bool:
    if source is None:
        return False
    policy = source.get("access_policy") or {}
    if policy.get("audience") == "authenticated":
        return True
    return bool(set(policy.get("allowed_role_ids") or []) & roles)


def _mean(values: list[Any]) -> float | None:
    present = [float(v) for v in values if v is not None]
    return round(sum(present) / len(present), 4) if present else None


def aggregate(scores: list[dict[str, Any]]) -> dict[str, Any]:
    """전략 × (전체·split·유형)별 집계. 값이 없는 지표는 N/A(None)와 표본 수를 같이 낸다."""
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for s in scores:
        for key in ("all", f"split:{s['split']}", f"category:{s['category']}"):
            buckets[(s["strategy"], key)].append(s)
    out: dict[str, Any] = {}
    for (strategy, key), rows in sorted(buckets.items()):
        out.setdefault(strategy, {})[key] = {
            "n": len(rows),
            "rule_correct": _mean([r["rule_correct"] for r in rows]),
            "outcome_ok": _mean([r["outcome_ok"] for r in rows]),
            "recall_pool": _mean([r["recall_pool"] for r in rows]),
            "recall_pool_n": sum(r["recall_pool"] is not None for r in rows),
            "recall_budget": _mean([r["recall_budget"] for r in rows]),
            "hit_budget": _mean([r["hit_budget"] for r in rows]),
            "citation_recall": _mean([r["citation_recall"] for r in rows]),
            "number_recall": _mean([r["number_recall"] for r in rows]),
            "number_recall_n": sum(r["number_recall"] is not None for r in rows),
            "over_abstain": _mean([r["over_abstain"] for r in rows if r["expected_outcome"] == "answered"]),
            "hard_negative_cited": _mean([r["hard_negative_cited"] for r in rows]),
            "forbidden_number_hit": _mean([r["forbidden_number_hit"] for r in rows]),
            "leaks": sum(bool(r["leaked_source_files"]) for r in rows),
            "errors": sum(bool(r["error"]) for r in rows),
            "strict_failures": sum(r["strict_failure"] for r in rows),
            "fallbacks": sum(r["fallback"] for r in rows),
            "input_tokens": sum(r["input_tokens"] for r in rows),
            "output_tokens": sum(r["output_tokens"] for r in rows),
            "usage_incomplete": sum(not r["usage_complete"] for r in rows),
            "mean_seconds": _mean([r["seconds"] for r in rows]),
        }
    return out


def paired(scores: list[dict[str, Any]], a: str = "raw", b: str = "wiki_assisted") -> dict[str, Any]:
    """같은 문항의 A/B 규칙 정답 비교(승·패·무). 작은 표본에서 우위를 자동 선언하지 않는다."""
    by_case: dict[str, dict[str, dict]] = defaultdict(dict)
    for s in scores:
        by_case[s["case_id"]][s["strategy"]] = s
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
        "pairs": wins + losses + ties,
        f"{b}_better": wins,
        f"{a}_better": losses,
        "same": ties,
        "changed": changed,
    }
