"""평가 CLI(APP-04): eval-run(💰 Haiku + Gemini 질의 임베딩), eval-score(과금 없음), eval-judge(Gemini).

uv run python -m agent.cli eval-run --strategy raw --split dev --live [--budget 4000] [--out PATH]
uv run python -m agent.cli eval-score --results A.jsonl B.jsonl [--split dev] [--out PATH]
uv run python -m agent.cli eval-judge --results A.jsonl B.jsonl --live [--seed 20261018] [--out PATH]
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.shared.settings import REPO_ROOT, Settings

CASES_DIR = REPO_ROOT / "eval" / "cases"
SOURCES_INDEX = REPO_ROOT / "data" / "staging" / "eval-sources" / "index.json"
RESULTS_DIR = REPO_ROOT / "data" / "staging" / "eval-results"
QUERY_CACHE = REPO_ROOT / "data" / "staging" / "embeddings" / "eval-query-cache.jsonl"
# 표시용 가격(USD/100만 토큰). cli._PRICE_PER_MTOK와 같은 출처. 실제 청구액이 아니다.
_PRICE = {"claude-haiku-5-5": (0.10, 0.50)}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _cases(split: str) -> list[dict[str, Any]]:
    names = ["dev", "holdout"] if split == "all" else [split]
    return [c for name in names for c in _read_jsonl(CASES_DIR / f"{name}.jsonl")]


async def eval_run(args: argparse.Namespace, settings: Settings) -> None:
    from agent.app.eval_run import CachingEmbedder, run_cases
    from agent.modules.model_integration.gemini_embedding import GeminiEmbeddingModel
    from agent.shared.clock import FixedClock
    from agent.shared.contracts import ExecutionPolicy

    cases = _cases(args.split)
    if args.cases:
        wanted = set(args.cases.split(","))
        cases = [c for c in cases if c["case_id"] in wanted]
    asked = {c["asked_at"] for c in cases}
    if len(asked) != 1:
        sys.exit(f"질문 시각이 하나가 아니다: {sorted(asked)}")
    if not args.live:
        print(
            json.dumps({"dry_run": True, "cases": len(cases), "strategy": args.strategy}, ensure_ascii=False)
        )
        return
    key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None
    embedder = CachingEmbedder(GeminiEmbeddingModel(api_key=key), QUERY_CACHE)
    out = Path(args.out) if args.out else RESULTS_DIR / f"{args.split}-{args.strategy}-b{args.budget}.jsonl"
    if out.exists():
        sys.exit(f"{out}가 이미 있다(결과를 덮어쓰지 않는다)")
    results = await run_cases(
        cases,
        settings=settings,
        clock=FixedClock(datetime.fromisoformat(asked.pop())),
        strategy=args.strategy,
        strict=not args.operational,
        out=out,
        policy=ExecutionPolicy(final_context_token_limit=args.budget),
        embedding_model=embedder,
    )
    tokens = [r.get("usage") or {} for x in results for r in x["runs"]]
    inp = sum(t.get("input_tokens") or 0 for t in tokens)
    outp = sum(t.get("output_tokens") or 0 for t in tokens)
    price = _PRICE.get(settings.chat_model)
    print(
        json.dumps(
            {
                "written": str(out),
                "cases": len(results),
                "input_tokens": inp,
                "output_tokens": outp,
                "usage_incomplete_runs": sum(not t.get("complete") for t in tokens),
                "usd_by_list_price": round((inp * price[0] + outp * price[1]) / 1e6, 4) if price else None,
                "query_cache": {"hits": embedder.hits, "misses": embedder.misses},
            },
            ensure_ascii=False,
            indent=1,
        )
    )


async def eval_score(args: argparse.Namespace, settings: Settings) -> None:
    from agent.app.eval_run import load_passages, result_passage_ids
    from agent.app.eval_score import aggregate, paired, score_case
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
    summary = {"aggregate": aggregate(scores), "paired": paired(scores)}
    out = Path(args.out) if args.out else RESULTS_DIR / "scores.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"scores": scores, **summary}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(
        json.dumps(
            {
                "written": str(out),
                "all": {k: v.get("all") for k, v in summary["aggregate"].items()},
                "paired": {k: v for k, v in summary["paired"].items() if k != "changed"},
            },
            ensure_ascii=False,
            indent=1,
        )
    )


async def eval_judge(args: argparse.Namespace, settings: Settings) -> None:
    from agent.app.eval_judge import JUDGE_PROMPT_VERSION, blind_order, judge_one, judge_text
    from agent.modules.model_integration.gemini_chat import GeminiJudgeModel
    from agent.modules.model_integration.ports import ModelConfig

    if not settings.judge_model:
        sys.exit("JUDGE_MODEL 설정이 없다")
    cases = {c["case_id"]: c for c in _cases("all")}
    items = []
    for path in args.results:
        for result in _read_jsonl(Path(path)):
            case = cases[result["case_id"]]
            final = result["turns"][-1] if result["turns"] else {}
            gold = [a["quote"] for group in case["evidence_sets"] for a in group]
            cited = [c.get("quote", "") for c in final.get("citations", [])]
            items.append(
                {
                    "case_id": case["case_id"],
                    "strategy": result["strategy"],
                    "text": judge_text(case, final.get("answer") or "", cited, gold),
                }
            )
    ordered = blind_order(items, args.seed)
    if not args.live:
        print(
            json.dumps(
                {"dry_run": True, "items": len(ordered), "example": ordered[0]["text"][:400]},
                ensure_ascii=False,
            )
        )
        return
    key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None
    chat = GeminiJudgeModel(api_key=key)
    config = ModelConfig(
        model=settings.judge_model, max_output_tokens=1024, config_version=JUDGE_PROMPT_VERSION
    )
    out = Path(args.out) if args.out else RESULTS_DIR / "judge.jsonl"
    mapping = out.with_suffix(".mapping.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    done = (
        {json.loads(x)["answer_id"] for x in out.read_text(encoding="utf-8").splitlines()}
        if out.exists()
        else set()
    )
    mapping.write_text(
        json.dumps(
            {i["answer_id"]: {"case_id": i["case_id"], "strategy": i["strategy"]} for i in ordered},
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    errors = 0
    try:
        with out.open("a", encoding="utf-8") as sink:
            for item in ordered:
                if item["answer_id"] in done:
                    continue
                verdict = await judge_one(chat, config, item["text"])
                errors += "judge_error" in verdict
                sink.write(json.dumps({"answer_id": item["answer_id"], **verdict}, ensure_ascii=False) + "\n")
                sink.flush()
                if verdict.get("judge_error") == "rate_limited":
                    break  # 무료 티어 한도: 남은 문항은 다음 실행에서 이어서 판정한다(실패로 결론 내지 않음)
    finally:
        await chat.aclose()
    print(
        json.dumps(
            {"written": str(out), "mapping": str(mapping), "items": len(ordered), "errors": errors},
            ensure_ascii=False,
        )
    )


def register(sub) -> dict[str, Any]:
    run = sub.add_parser("eval-run", help="💰 평가 문항을 한 전략으로 실행한다(--live 없으면 dry-run)")
    run.add_argument("--strategy", choices=["raw", "wiki_assisted"], required=True)
    run.add_argument("--split", choices=["dev", "holdout", "all"], default="dev")
    run.add_argument("--budget", type=int, default=4000, help="final_context_token_limit")
    run.add_argument("--operational", action="store_true", help="엄격 모드 대신 운영 fallback")
    run.add_argument("--cases", help="쉼표로 구분한 case_id만")
    run.add_argument("--out")
    run.add_argument("--live", action="store_true")
    score = sub.add_parser("eval-score", help="실행 결과를 gold와 규칙 채점한다(과금 없음)")
    score.add_argument("--results", nargs="+", required=True)
    score.add_argument("--out")
    judge = sub.add_parser("eval-judge", help="judge 보조 판정(Gemini 무료 티어, --live 없으면 dry-run)")
    judge.add_argument("--results", nargs="+", required=True)
    judge.add_argument("--seed", type=int, default=20261018)
    judge.add_argument("--out")
    judge.add_argument("--live", action="store_true")
    return {"eval-run": eval_run, "eval-score": eval_score, "eval-judge": eval_judge}
