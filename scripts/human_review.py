"""사람 검수 표본(평가 결과 30건)을 만들고, 검수 결과와 규칙·judge 판정의 일치를 계산한다.

과금 없음(API를 부르지 않는다). 검수 CSV에는 규칙·judge 판정을 넣지 않고(블라인드),
판정은 키 파일에 따로 둔다.

    python -B scripts/human_review.py make  [--scores …] [--results …] [--out data/staging/human-review]
    python -B scripts/human_review.py score [--out data/staging/human-review]

표본: 규칙과 judge가 정면으로 갈린 문항(규칙 정답·judge 부분 / 규칙 오답·judge 정답) 전부
+ 나머지에서 seed로 고른 무작위.
검수자는 `판정` 열에 정답/부분/오답, `이유` 열에 한 줄을 쓴다.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "data/staging/eval-results"
DEFAULT_SCORES = RESULTS / "scores-holdout2-after.json"
DEFAULT_RESULTS = RESULTS / "holdout2-raw-b4000-after.jsonl"
DEFAULT_CASES = ROOT / "eval/cases/holdout2.jsonl"
DEFAULT_OUT = ROOT / "data/staging/human-review"
SEED = 20261020
SIZE = 30
HUMAN = {"정답": "correct", "부분": "partial", "오답": "incorrect"}
FIELDS = [
    "번호",
    "case_id",
    "분류",
    "질문",
    "기대 결과",
    "필수 사실",
    "필수 예외",
    "금지 주장",
    "정답 근거(원문)",
    "시스템 결과",
    "시스템 답변",
    "시스템 인용(원문)",
    "판정",
    "이유",
]


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def make(args: argparse.Namespace) -> None:
    scores = {s["case_id"]: s for s in json.loads(Path(args.scores).read_text(encoding="utf-8"))["scores"]}
    results = {r["case_id"]: r for r in _jsonl(Path(args.results))}
    cases = {c["case_id"]: c for c in _jsonl(Path(args.cases))}

    def judge(cid: str) -> str | None:
        return (scores[cid].get("judge") or {}).get("verdict")

    split = sorted(
        cid
        for cid, s in scores.items()
        if (s["rule_correct"] and judge(cid) == "partial")
        or (not s["rule_correct"] and judge(cid) == "correct")
    )
    rest = sorted(cid for cid in scores if cid not in split)
    # 재현 가능한 표본 추출이라 암호용 난수가 필요 없다
    picked = split + random.Random(SEED).sample(rest, max(0, SIZE - len(split)))  # noqa: S311
    random.Random(SEED + 1).shuffle(picked)  # noqa: S311 — 검수자가 어느 쪽 표본인지 순서로 알 수 없게

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows, key = [], []
    for n, cid in enumerate(picked, 1):
        case, result = cases[cid], results[cid]
        last = result["turns"][-1]
        rows.append(
            {
                "번호": n,
                "case_id": cid,
                "분류": case["category"],
                "질문": "\n".join(f"[{i}] {t}" for i, t in enumerate(case["turns"], 1)),
                "기대 결과": case["expected_outcome"],
                "필수 사실": _bullets(case["required_facts"]),
                "필수 예외": _bullets(case["required_exceptions"]),
                "금지 주장": _bullets(case["forbidden_claims"]),
                "정답 근거(원문)": "\n".join(
                    f"{q['source_file_id']} p.{q['page']}: {q['quote']}"
                    for group in case["evidence_sets"]
                    for q in group
                ),
                "시스템 결과": last.get("outcome") or f"오류 {last.get('status')}",
                "시스템 답변": last.get("answer") or "",
                "시스템 인용(원문)": "\n---\n".join(c.get("quote", "") for c in last.get("citations") or []),
                "판정": "",
                "이유": "",
            }
        )
        key.append(
            {
                "case_id": cid,
                "sample": "disagreement" if cid in split else "random",
                "rule_correct": scores[cid]["rule_correct"],
                "judge": judge(cid),
            }
        )
    with (out / "review.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as f:  # Excel에서 한글이 깨지지 않게 BOM
        writer = csv.DictWriter(f, FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    (out / "key.json").write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{out / 'review.csv'}: {len(rows)}건(불일치 {len(split)}, 무작위 {len(rows) - len(split)})")


def _kappa(pairs: list[tuple[str, str]]) -> float | None:
    n = len(pairs)
    if not n:
        return None
    observed = sum(a == b for a, b in pairs) / n
    left, right = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    expected = sum(left[k] * right[k] for k in left) / (n * n)
    return None if expected == 1 else round((observed - expected) / (1 - expected), 3)


def _report(name: str, pairs: list[tuple[str, str]]) -> dict:
    agree = sum(a == b for a, b in pairs)
    return {
        "비교": name,
        "n": len(pairs),
        "일치": agree,
        "일치율": round(agree / len(pairs), 3) if pairs else None,
        "kappa": _kappa(pairs),
    }


def score(args: argparse.Namespace) -> None:
    out = Path(args.out)
    key = {k["case_id"]: k for k in json.loads((out / "key.json").read_text(encoding="utf-8"))}
    with (out / "review.csv").open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    bad = [r["case_id"] for r in rows if r["판정"].strip() not in HUMAN]
    if bad:
        raise SystemExit(f"판정이 비었거나 정답/부분/오답이 아닌 행: {', '.join(bad)}")
    report = []
    for sample in ("all", "random", "disagreement"):
        chosen = [r for r in rows if sample == "all" or key[r["case_id"]]["sample"] == sample]
        human = [(HUMAN[r["판정"].strip()], key[r["case_id"]]) for r in chosen]
        report.append(
            {
                "표본": sample,
                **_report("사람 vs judge(3단계)", [(h, k["judge"] or "missing") for h, k in human]),
            }
        )
        report.append(
            {
                "표본": sample,
                **_report("사람 vs 규칙(정답 여부)", [(h == "correct", k["rule_correct"]) for h, k in human]),
            }
        )
        report.append(
            {
                "표본": sample,
                **_report(
                    "사람 vs judge(정답 여부)", [(h == "correct", k["judge"] == "correct") for h, k in human]
                ),
            }
        )
    (out / "agreement.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    for line in report:
        print(json.dumps(line, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    m = sub.add_parser("make")
    m.add_argument("--scores", default=str(DEFAULT_SCORES))
    m.add_argument("--results", default=str(DEFAULT_RESULTS))
    m.add_argument("--cases", default=str(DEFAULT_CASES))
    m.add_argument("--out", default=str(DEFAULT_OUT))
    s = sub.add_parser("score")
    s.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()
    {"make": make, "score": score}[args.command](args)


if __name__ == "__main__":
    main()
