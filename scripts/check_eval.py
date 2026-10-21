"""평가셋 기계 검사(eval/README.md 형식). 모델 판단 없이 원문과 규칙만 대조한다.

    python -B scripts/check_eval.py [파일.jsonl ...]     # 기본: eval/cases/dev.jsonl·holdout.jsonl

원문은 프로젝트 파서로 내보낸 쪽별 텍스트(data/staging/eval-sources/*.json)를 쓴다.
검사: 필드·값, case_id 중복, 유형·split 수(기본 파일일 때), 인용이 그 쪽에 공백 정규화 후 occurrence번째로
있는지, 근거 판본이 사건 날짜의 시행 구간인지, 질문 시각에 공개된 판본인지, 권한 거절·허용 사례의 계정 역할.
"""

import json
import re
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "data" / "staging" / "eval-sources"
DEFAULT = [ROOT / "eval" / "cases" / "dev.jsonl", ROOT / "eval" / "cases" / "holdout.jsonl"]
PLAN = {
    "single_doc": (10, 20),
    "multi_doc": (13, 27),
    "exception": (8, 17),
    "revision": (7, 13),
    "no_evidence": (5, 10),
    "access": (7, 13),
}
ROLES = {
    "emp-sales": {"employee"},
    "emp-dev": {"employee"},
    "head-sales": {"employee", "dept_head"},
    "hr-staff": {"employee", "hr_staff"},
    "it-support": {"employee", "it_support"},
}
OUTCOMES = {"answered", "needs_clarification", "insufficient_evidence"}
BASES = {"current", "explicit_date", "training_start", "trip_start", "approval_date", "request_date",
         "work_date", "processing_date"}
REQUIRED = ("case_id", "split", "category", "tags", "asked_at", "actor", "turns", "expected_outcome",
            "date_basis", "as_of_date", "required_facts", "forbidden_claims", "evidence_sets",
            "hard_negative_anchors", "rationale", "generated_by")
SPACE = re.compile(r"\s+")


def norm(text: str) -> str:
    return SPACE.sub(" ", text).strip()


def load_sources() -> dict:
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in SOURCES.glob("PDF-*.json")}


def allowed(source: dict, actor: str) -> bool:
    policy = source["access_policy"]
    if policy.get("audience") == "authenticated":
        return True
    return bool(set(policy.get("allowed_role_ids") or []) & ROLES.get(actor, set()))


def check_anchor(anchor: dict, sources: dict, where: str, problems: list[str]) -> dict | None:
    source = sources.get(anchor.get("source_file_id"))
    if source is None:
        problems.append(f"{where}: 없는 source_file_id {anchor.get('source_file_id')}")
        return None
    pages = {p["page"]: p["text"] for p in source["pages"]}
    page = anchor.get("page")
    if page not in pages:
        problems.append(f"{where}: {anchor['source_file_id']}에 {page}쪽 없음")
        return None
    quote = norm(str(anchor.get("quote", "")))
    if not 8 <= len(quote) <= 200:
        problems.append(f"{where}: 인용 길이 {len(quote)}")
    text = norm(pages[page])
    count = text.count(quote) if quote else 0
    occurrence = anchor.get("occurrence", 1)
    if count == 0:
        problems.append(f"{where}: 인용이 {anchor['source_file_id']} {page}쪽에 없음: {quote[:40]!r}")
    elif not isinstance(occurrence, int) or not 1 <= occurrence <= count:
        problems.append(f"{where}: occurrence {occurrence}(실제 {count}회)")
    return source


def check_case(case: dict, sources: dict) -> list[str]:
    cid = case.get("case_id", "?")
    problems = [f"{cid}: 필드 없음 {k}" for k in REQUIRED if k not in case]
    if problems:
        return problems
    if case["category"] not in PLAN:
        problems.append(f"{cid}: category {case['category']}")
    # holdout2~8: 새 검증셋(D-62·D-70·D-73·D-81·D-84·D-87·D-89)
    if case["split"] not in ("dev", "holdout", "holdout2", "holdout3", "holdout4", "holdout5", "holdout6", "holdout7", "holdout8"):
        problems.append(f"{cid}: split {case['split']}")
    if case["expected_outcome"] not in OUTCOMES:
        problems.append(f"{cid}: expected_outcome {case['expected_outcome']}")
    if case["actor"] not in ROLES:
        problems.append(f"{cid}: actor {case['actor']}")
    if case["date_basis"] not in BASES:
        problems.append(f"{cid}: date_basis {case['date_basis']}")
    if not case["turns"] or not all(isinstance(t, str) and t.strip() for t in case["turns"]):
        problems.append(f"{cid}: turns 비었음")
    asked = datetime.fromisoformat(case["asked_at"])
    as_of = date.fromisoformat(case["as_of_date"]) if case["as_of_date"] else None
    # D-67: 날짜 없는 과거 사건을 판본별로 나눠 답하는 문항(tag edition_split)은 사건 기준 + 날짜 없음이다.
    dateless_ok = case["expected_outcome"] == "needs_clarification" or "edition_split" in case["tags"]
    if case["date_basis"] != "current" and as_of is None and not dateless_ok:
        problems.append(f"{cid}: {case['date_basis']}인데 as_of_date 없음")
    answered = case["expected_outcome"] == "answered"
    if answered and not case["evidence_sets"]:
        problems.append(f"{cid}: answered인데 근거 없음")
    if not answered and case["evidence_sets"]:
        problems.append(f"{cid}: {case['expected_outcome']}인데 근거 있음")
    event_day = as_of or asked.date()
    for i, group in enumerate(case["evidence_sets"]):
        if not group:
            problems.append(f"{cid}: evidence_sets[{i}] 비었음")
        for j, anchor in enumerate(group):
            source = check_anchor(anchor, sources, f"{cid}.evidence[{i}][{j}]", problems)
            if source is None:
                continue
            if not allowed(source, case["actor"]):
                problems.append(f"{cid}: {case['actor']}가 볼 수 없는 {source['source_file_id']}를 근거로 씀")
            if datetime.fromisoformat(source["available_from"]) > asked:
                problems.append(f"{cid}: {source['source_file_id']}는 질문 시각에 공개 전")
            if source.get("guidance_valid_to") and datetime.fromisoformat(source["guidance_valid_to"]) <= asked:
                problems.append(f"{cid}: {source['source_file_id']}는 질문 시각에 유효하지 않은 안내")
            if source["document_role"] == "normative" and case["category"] != "revision":
                start = date.fromisoformat(source["effective_from"]) if source["effective_from"] else None
                end = date.fromisoformat(source["effective_to"]) if source["effective_to"] else None
                if (start and event_day < start) or (end and event_day >= end):
                    problems.append(
                        f"{cid}: {source['source_file_id']} 시행 구간({start}~{end})이 사건 날짜 {event_day}와 다름"
                    )
    for k, anchor in enumerate(case["hard_negative_anchors"]):
        check_anchor(anchor, sources, f"{cid}.hard_negative[{k}]", problems)
    if case["category"] == "access":
        # 거절 문항: 제한 문서를 근거로 쓰지 않는다(위 allowed 검사). 공개 문서 부분만 답하는 혼합 문항은
        # answered일 수 있지만, 제한 부분을 말하면 틀리도록 금지 주장이 있어야 한다.
        if "denied" in case["tags"] and not case["forbidden_claims"]:
            problems.append(f"{cid}: denied인데 forbidden_claims 없음")
        if "allowed" in case["tags"] and not answered:
            problems.append(f"{cid}: allowed인데 {case['expected_outcome']}")
    if case["category"] == "multi_doc" and "faq_sufficient" not in case["tags"]:
        for i, group in enumerate(case["evidence_sets"]):
            keys = {sources[a["source_file_id"]]["document_key"] for a in group if a.get("source_file_id") in sources}
            if len(keys) < 2:
                problems.append(f"{cid}: multi_doc evidence_sets[{i}] 문서 {len(keys)}개")
    return problems


def main(paths: list[Path]) -> int:
    sources = load_sources()
    if not sources:
        print("원문 내보내기(data/staging/eval-sources)가 없다", file=sys.stderr)
        return 2
    cases = [json.loads(line) for p in paths for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    problems: list[str] = []
    ids = Counter(c.get("case_id") for c in cases)
    problems += [f"case_id 중복 {k}" for k, n in ids.items() if n > 1]
    for case in cases:
        problems += check_case(case, sources)
    counts = Counter((c.get("category"), c.get("split")) for c in cases)
    if paths == DEFAULT:
        for category, (dev, holdout) in PLAN.items():
            for split, want in (("dev", dev), ("holdout", holdout)):
                if counts[(category, split)] != want:
                    problems.append(f"{category}/{split}: {counts[(category, split)]}개(목표 {want})")
    summary = {
        "cases": len(cases),
        "by_category_split": {f"{k[0]}/{k[1]}": v for k, v in sorted(counts.items())},
        "problems": problems,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 1 if problems else 0


if __name__ == "__main__":
    args = [Path(a) for a in sys.argv[1:]]
    sys.exit(main(args or DEFAULT))
