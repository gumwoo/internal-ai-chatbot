"""평가 CLI(APP-04): eval-run(💰 Haiku + Gemini 질의 임베딩), eval-score(과금 없음), eval-judge(Gemini).

uv run python -m agent.cli eval-run --strategy raw --split dev --live [--budget 4000] [--resume]
uv run python -m agent.cli eval-freeze --budget 8000 --reason "dev 스윕 결과"   # holdout 전에 예산 동결
uv run python -m agent.cli eval-score --results A.jsonl B.jsonl [--judge J.jsonl] [--out PATH]
uv run python -m agent.cli eval-judge --results A.jsonl B.jsonl --live [--seed 20261018] [--out PATH]
"""

import argparse
import ast
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.shared.settings import REPO_ROOT, Settings

CASES_DIR = REPO_ROOT / "eval" / "cases"
EVAL_MANIFEST = REPO_ROOT / "eval" / "manifest.json"
SOURCES_INDEX = REPO_ROOT / "data" / "staging" / "eval-sources" / "index.json"
RESULTS_DIR = REPO_ROOT / "data" / "staging" / "eval-results"
FREEZE = RESULTS_DIR / "freeze.json"
FULL_CONTEXT_BUDGET = 150_000  # D-50
# 동결 예산으로만 실행하는 split
HELD_OUT = frozenset(
    {"holdout", "holdout2", "holdout3", "holdout4", "holdout5", "holdout6", "holdout7", "holdout8", "all"}
)
# judge 출력 상한. gemini-3.8-flash는 사고(thinking) token도 이 상한에 넣어
# 1024이면 긴 판정의 JSON이 잘렸다(D-59).
JUDGE_MAX_OUTPUT_TOKENS = 4096
QUERY_CACHE = REPO_ROOT / "data" / "staging" / "embeddings" / "eval-query-cache.jsonl"
# 표시용 가격(USD/100만 토큰). cli._PRICE_PER_MTOK와 같은 출처. 실제 청구액이 아니다.
_PRICE = {"claude-haiku-5-5": (0.10, 0.50)}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


# 모델 답이 아니라 공급자·과금·네트워크 쪽에서 끝난 실패. 이어하기에서 다시 돈다.
_RETRY_CODES = frozenset({"MODEL_UPSTREAM_ERROR"})


def _finished(row: dict[str, Any]) -> bool:
    if row.get("error"):
        return False
    runs = row.get("runs") or []
    if isinstance(runs, str):  # 이전 결과 파일은 run 목록을 문자열로 남겼다
        runs = ast.literal_eval(runs)
    return not any(run.get("error_code") in _RETRY_CODES for run in runs)


def _retriever_config(args: argparse.Namespace) -> str | None:
    """원문 검색 설정 ID(D-72). Wiki·기준선은 실행 trace의 값을 본다."""
    from agent.modules.retrieval.service import RETRIEVER_CONFIG_ID

    return RETRIEVER_CONFIG_ID if args.strategy == "raw" else None


def _cases(split: str) -> list[dict[str, Any]]:
    # holdout2: eval-v2 새 검증셋(옛 holdout을 본 뒤 개선했으므로 최종 측정은 새 문항으로 한다, D-62)
    # holdout3: eval-v3(holdout2를 보고 D-67~D-69를 고쳤으므로 그 효과는 새 문항으로 잰다, D-70)
    # holdout4: 복수 문서 확인 셋(holdout3를 보고 D-71·D-72를 고쳤으므로 새 문항으로 확인한다, D-73)
    # holdout5: D-71~D-80과 인젝션 방어(D-82)의 효과를 재는 새 검증셋(D-81)
    # holdout6: 마감일 기준일 짝·판본별 두 갈래 결론·기한마다 검색(D-83)의 효과를 재는 새 검증셋(D-84)
    # holdout7: 판본별 재호출·사건 기준 없는 규정의 판본 나누기·마감일 인용(D-86)을 여러 번 재는 셋(D-87)
    # holdout8: 이어지는 턴의 검색 재호출(D-88)을 여러 번 재는 셋(D-89)
    if split == "all":
        names = [
            n
            for n in (
                "dev",
                "holdout",
                "holdout2",
                "holdout3",
                "holdout4",
                "holdout5",
                "holdout6",
                "holdout7",
                "holdout8",
            )
            if (CASES_DIR / f"{n}.jsonl").exists()
        ]
    else:
        names = [split]
    return [c for name in names for c in _read_jsonl(CASES_DIR / f"{name}.jsonl")]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _cost(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """실제 응답의 model_id 기준 공시가 × 측정 token. 사용량을 모르는 run이 있으면 금액을 내지 않는다."""
    inp = outp = 0
    usd = 0.0
    priced = True
    for run in runs:
        usage = run.get("usage") or {}
        inp += usage.get("input_tokens") or 0
        outp += usage.get("output_tokens") or 0
        model = (run.get("model_ids") or [None])[-1]
        price = _PRICE.get(model)
        if price is None or not usage.get("complete"):
            priced = False if usage else priced
            continue
        usd += (
            (usage.get("input_tokens") or 0) * price[0] + (usage.get("output_tokens") or 0) * price[1]
        ) / 1e6
    return {
        "input_tokens": inp,
        "output_tokens": outp,
        "usd_by_list_price": round(usd, 4) if priced else None,
    }


async def eval_run(args: argparse.Namespace, settings: Settings) -> None:
    from agent.app.eval_run import CachingEmbedder, run_cases
    from agent.modules.model_integration.gemini_embedding import GeminiEmbeddingModel
    from agent.shared.clock import FixedClock
    from agent.shared.contracts import ExecutionPolicy

    if args.split in HELD_OUT and args.strategy == "full_context_reference":
        # 전체 문맥 기준선은 A/B 예산 동결과 무관하게 D-50의 고정 예산으로만 돈다.
        if args.budget != FULL_CONTEXT_BUDGET:
            sys.exit(f"전체 문맥 기준선은 D-50 예산 {FULL_CONTEXT_BUDGET}으로만 실행한다")
    elif args.split in HELD_OUT:
        # holdout은 dev로 예산을 동결한 뒤에만 실행한다(docs/13 K9).
        frozen = json.loads(FREEZE.read_text(encoding="utf-8")) if FREEZE.exists() else None
        if frozen is None or frozen.get("budget") != args.budget:
            sys.exit(f"holdout은 동결 예산으로만 실행한다(eval-freeze 먼저). 동결: {frozen}")
    cases = _cases(args.split)
    if args.cases:
        wanted = set(args.cases.split(","))
        cases = [c for c in cases if c["case_id"] in wanted]
    asked = {c["asked_at"] for c in cases}
    if len(asked) != 1:
        sys.exit(f"질문 시각이 하나가 아니다: {sorted(asked)}")
    out = Path(args.out) if args.out else RESULTS_DIR / f"{args.split}-{args.strategy}-b{args.budget}.jsonl"
    if out.exists():
        if not args.resume:
            sys.exit(f"{out}가 이미 있다(덮어쓰지 않는다. 이어서 하려면 --resume)")
        rows = _read_jsonl(out)
        mixed = {(r.get("config") or {}).get("retriever_config_id") for r in rows} - {_retriever_config(args)}
        if mixed:
            # D-72: 검색 설정이 다른 결과에 이어 쓰면 같은 라벨로 섞인다(v1 결과에는 이 값이 없다).
            sys.exit(f"{out}는 다른 검색 설정({sorted(map(str, mixed))})의 결과다. 새 --out을 쓴다")
        kept = [r for r in rows if _finished(r)]
        if len(kept) != len(rows):
            # 다시 돌 행은 결과 파일에서 빼 따로 보존한다(채점에 중복·인프라 실패가 섞이지 않게)
            with out.with_name(out.stem + ".retried.jsonl").open("a", encoding="utf-8") as f:
                f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows if not _finished(r))
            out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in kept), encoding="utf-8")
        done = {r["case_id"] for r in kept}
        cases = [c for c in cases if c["case_id"] not in done]
    if not args.live:
        print(
            json.dumps({"dry_run": True, "cases": len(cases), "strategy": args.strategy}, ensure_ascii=False)
        )
        return
    key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None
    embedder = CachingEmbedder(GeminiEmbeddingModel(api_key=key), QUERY_CACHE)
    manifest = json.loads(EVAL_MANIFEST.read_text(encoding="utf-8"))
    results = await run_cases(
        cases,
        settings=settings,
        clock=FixedClock(datetime.fromisoformat(asked.pop())),
        strategy=args.strategy,
        strict=not args.operational,
        out=out,
        policy=ExecutionPolicy(final_context_token_limit=args.budget),
        embedding_model=embedder,
        run_meta={
            "retriever_config_id": _retriever_config(args),
            "eval_version": manifest.get("eval_version"),
            "cases_sha256": {k: v["sha256"] for k, v in manifest.get("files", {}).items()},
            "started_at": datetime.now().astimezone().isoformat(),
        },
    )
    runs = [r for x in results for r in x["runs"]]
    print(
        json.dumps(
            {
                "written": str(out),
                "cases": len(results),
                "errors": sum(bool(x.get("error")) for x in results),
                **_cost(runs),
                "usage_incomplete_runs": sum(not (r.get("usage") or {}).get("complete") for r in runs),
                "query_cache": {"hits": embedder.hits, "misses": embedder.misses},
            },
            ensure_ascii=False,
            indent=1,
        )
    )


async def eval_freeze(args: argparse.Namespace, settings: Settings) -> None:
    if FREEZE.exists() and not args.force:
        sys.exit(f"이미 동결했다: {FREEZE.read_text(encoding='utf-8')}")
    FREEZE.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "budget": args.budget,
        "reason": args.reason,
        "frozen_at": datetime.now().astimezone().isoformat(),
    }
    FREEZE.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False))


def _judge_item(result: dict[str, Any], case: dict[str, Any], passages: dict[str, Any]) -> dict[str, Any]:
    """judge 입력 한 건(eval-judge와 eval-score가 같은 내용으로 answer_id를 만든다)."""
    from agent.app.eval_judge import judge_text
    from agent.app.eval_score import config_label

    final = result["turns"][-1] if result.get("turns") else {}
    gold = [a["quote"] for group in case["evidence_sets"] for a in group]
    # 시스템이 인용한 원문은 잘린 미리보기가 아니라 passage 본문 전체를 준다(근거 없는 주장 오판 방지).
    cited = [
        passages[c["passage_id"]].text if c.get("passage_id") in passages else c.get("quote", "")
        for c in final.get("citations", [])
    ]
    return {
        "case_id": case["case_id"],
        "label": config_label(result),
        "text": judge_text(case, final.get("answer") or "", cited, gold),
    }


def _judge_rows(judge_paths: list[str]) -> dict[str, dict[str, Any]]:
    """answer_id → 판정. 성공한 판정을 실패보다 우선한다."""
    rows: dict[str, dict[str, Any]] = {}
    for path in judge_paths:
        for row in _read_jsonl(Path(path)):
            if "judge_error" not in row or row["answer_id"] not in rows:
                rows[row["answer_id"]] = row
    return rows


def _judge_by_answer(judge_paths: list[str]) -> dict[tuple[str, str], dict[str, Any]]:
    """judge 결과를 (case_id, label)로 모은다. 성공한 판정만 쓰고, 실패는 따로 센다."""
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for path in judge_paths:
        mapping = json.loads(Path(path).with_suffix(".mapping.json").read_text(encoding="utf-8"))
        for row in _read_jsonl(Path(path)):
            target = mapping.get(row["answer_id"])
            if target is None:
                continue
            key = (target["case_id"], target["label"])
            if "judge_error" not in row or key not in merged:
                merged[key] = row
    return merged


async def eval_score(args: argparse.Namespace, settings: Settings) -> None:
    from agent.app.eval_run import load_passages, result_passage_ids
    from agent.app.eval_score import aggregate, check_complete, paired, score_case
    from agent.shared.db import make_engine

    cases = {c["case_id"]: c for c in _cases("all")}
    sources = {s["source_file_id"]: s for s in json.loads(SOURCES_INDEX.read_text(encoding="utf-8"))}
    results = [r for path in args.results for r in _read_jsonl(Path(path))]
    engine = make_engine(settings.database_url, settings.db_connect_timeout_s)
    try:
        passages = await load_passages(engine, result_passage_ids(results))
    finally:
        await engine.dispose()
    scores = [score_case(cases[r["case_id"]], r, passages, sources) for r in results]
    from agent.app.eval_judge import answer_id

    # 판정은 답 내용(answer_id)으로 붙인다. (case_id, label)로 붙이면 같은 설정 라벨의 다른 실행
    # (예: 개선 전후)이 서로의 판정을 덮어쓴다(D-66).
    judged = _judge_rows(args.judge or [])
    for result, s in zip(results, scores, strict=True):
        item = _judge_item(result, cases[result["case_id"]], passages)
        verdict = judged.get(answer_id(item["case_id"], item["label"], item["text"], args.judge_seed))
        s["judge"] = (
            None
            if verdict is None
            else {
                k: verdict.get(k)
                for k in ("verdict", "unsupported_claim", "forbidden_violated", "judge_error")
            }
        )
    splits = {s["split"] for s in scores}
    expected = {c for c, case in cases.items() if case["split"] in splits}
    completeness = check_complete(scores, expected)
    by_budget: dict[str, list[str]] = {}
    for label in sorted({s["label"] for s in scores}):
        strategy, strict, budget = label.split("|")
        by_budget.setdefault(f"{strict}|{budget}", []).append(label)
    pairs = []
    for labels in by_budget.values():
        raw = next((x for x in labels if x.startswith("raw|")), None)
        for other in labels:
            if raw and other != raw:
                pairs.append(paired(scores, raw, other))
    judge_summary: dict[str, Any] = {}
    for s in scores:
        bucket = judge_summary.setdefault(
            s["label"], {"n": 0, "judged": 0, "failed": 0, "missing": 0, "correct": 0, "unsupported_claim": 0}
        )
        bucket["n"] += 1
        if s["judge"] is None:
            bucket["missing"] += 1
        elif s["judge"].get("judge_error"):
            bucket["failed"] += 1
        else:
            bucket["judged"] += 1
            bucket["correct"] += s["judge"].get("verdict") == "correct"
            bucket["unsupported_claim"] += bool(s["judge"].get("unsupported_claim"))
    summary = {
        "aggregate": aggregate(scores),
        "paired": pairs,
        "completeness": completeness,
        "judge": judge_summary if args.judge else None,
        "results_sha256": {p: _sha(Path(p)) for p in args.results},
    }
    out = Path(args.out) if args.out else RESULTS_DIR / "scores.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"scores": scores, **summary}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(
        json.dumps(
            {
                "written": str(out),
                "all": {k: v.get("all") for k, v in summary["aggregate"].items()},
                "paired": [{k: v for k, v in p.items() if k != "changed"} for p in pairs],
                "incomplete": {k: v for k, v in completeness.items() if any(v.values())},
                "judge": summary["judge"],
            },
            ensure_ascii=False,
            indent=1,
        )
    )


async def eval_judge(args: argparse.Namespace, settings: Settings) -> None:
    from agent.app.eval_judge import JUDGE_PROMPT_VERSION, blind_order, judge_one
    from agent.app.eval_run import load_passages, result_passage_ids
    from agent.modules.model_integration.gemini_chat import GeminiJudgeModel
    from agent.modules.model_integration.ports import ModelConfig
    from agent.shared.db import make_engine

    if args.live and not settings.judge_model:
        sys.exit("JUDGE_MODEL 설정이 없다")
    cases = {c["case_id"]: c for c in _cases("all")}
    results = [r for path in args.results for r in _read_jsonl(Path(path))]
    engine = make_engine(settings.database_url, settings.db_connect_timeout_s)
    try:
        passages = await load_passages(engine, result_passage_ids(results))
    finally:
        await engine.dispose()
    items = [_judge_item(result, cases[result["case_id"]], passages) for result in results]
    ordered = blind_order(items, args.seed)
    if not args.live:
        print(
            json.dumps(
                {"dry_run": True, "items": len(ordered), "example": ordered[0]["text"][:400]},
                ensure_ascii=False,
            )
        )
        return
    if settings.judge_model.startswith("claude-"):
        # D-90: Gemini 무료 키 하루 한도로 judge가 끝나지 않을 때 Anthropic 모델로 판정한다(judge_model 기록).
        from agent.modules.model_integration.anthropic_chat import AnthropicChatModel

        key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
        chat = AnthropicChatModel(api_key=key)
    else:
        key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None
        chat = GeminiJudgeModel(api_key=key)
    config = ModelConfig(
        model=settings.judge_model,
        max_output_tokens=JUDGE_MAX_OUTPUT_TOKENS,
        config_version=JUDGE_PROMPT_VERSION,
    )
    out = Path(args.out) if args.out else RESULTS_DIR / "judge.jsonl"
    mapping_path = out.with_suffix(".mapping.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    # 내용 기반 ID라 같은 답은 같은 ID다. 성공한 판정만 건너뛰고 실패한 판정은 다시 한다.
    done = {r["answer_id"] for r in _read_jsonl(out) if "judge_error" not in r} if out.exists() else set()
    mapping = json.loads(mapping_path.read_text(encoding="utf-8")) if mapping_path.exists() else {}
    mapping.update({i["answer_id"]: {"case_id": i["case_id"], "label": i["label"]} for i in ordered})
    mapping_path.write_text(json.dumps(mapping, ensure_ascii=False, indent=1), encoding="utf-8")
    errors = judged = 0
    try:
        with out.open("a", encoding="utf-8") as sink:
            for item in ordered:
                if item["answer_id"] in done:
                    continue
                verdict = await judge_one(chat, config, item["text"], cases[item["case_id"]])
                errors += "judge_error" in verdict
                judged += "judge_error" not in verdict
                sink.write(json.dumps({"answer_id": item["answer_id"], **verdict}, ensure_ascii=False) + "\n")
                sink.flush()
                if verdict.get("judge_error") == "rate_limited":
                    break  # 무료 티어 한도: 남은 문항과 실패한 문항은 다음 실행에서 다시 판정한다
    finally:
        await chat.aclose()
    print(
        json.dumps(
            {
                "written": str(out),
                "mapping": str(mapping_path),
                "items": len(ordered),
                "judged_now": judged,
                "errors": errors,
                "already_done": len(done),
            },
            ensure_ascii=False,
        )
    )


def register(sub) -> dict[str, Any]:
    run = sub.add_parser("eval-run", help="💰 평가 문항을 한 전략으로 실행한다(--live 없으면 dry-run)")
    run.add_argument("--strategy", choices=["raw", "wiki_assisted", "full_context_reference"], required=True)
    run.add_argument(
        "--split",
        choices=[
            "dev",
            "holdout",
            "holdout2",
            "holdout3",
            "holdout4",
            "holdout5",
            "holdout6",
            "holdout7",
            "holdout8",
            "all",
        ],
        default="dev",
    )
    run.add_argument("--budget", type=int, default=4000, help="final_context_token_limit")
    run.add_argument("--operational", action="store_true", help="엄격 모드 대신 운영 fallback")
    run.add_argument("--cases", help="쉼표로 구분한 case_id만")
    run.add_argument("--resume", action="store_true", help="결과 파일이 있으면 실패하지 않은 문항은 건너뛴다")
    run.add_argument("--out")
    run.add_argument("--live", action="store_true")
    freeze = sub.add_parser("eval-freeze", help="holdout 전에 예산을 동결한다")
    freeze.add_argument("--budget", type=int, required=True)
    freeze.add_argument("--reason", required=True)
    freeze.add_argument("--force", action="store_true")
    score = sub.add_parser("eval-score", help="실행 결과를 gold와 규칙 채점한다(과금 없음)")
    score.add_argument("--results", nargs="+", required=True)
    score.add_argument("--judge", nargs="*", help="eval-judge 결과 파일(같은 이름의 .mapping.json 필요)")
    score.add_argument(
        "--judge-seed", type=int, default=20261018, help="eval-judge에 쓴 seed(answer_id 계산)"
    )
    score.add_argument("--out")
    judge = sub.add_parser("eval-judge", help="judge 보조 판정(Gemini 무료 티어, --live 없으면 dry-run)")
    judge.add_argument("--results", nargs="+", required=True)
    judge.add_argument("--seed", type=int, default=20261018)
    judge.add_argument("--out")
    judge.add_argument("--live", action="store_true")
    return {
        "eval-run": eval_run,
        "eval-freeze": eval_freeze,
        "eval-score": eval_score,
        "eval-judge": eval_judge,
    }
