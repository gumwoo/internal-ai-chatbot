"""검색 단계 비교(모델 호출 없음): 벡터 검색과 키워드(BM25) 결합의 예산 안 정답 근거 재현율.

문항 질문 문장(여러 턴이면 이어 붙임)을 질의로, 문항 계정·지식 시점·사건 날짜로 허용된 원문 전체를 한 번 받아
(권한·게시·판본 필터는 운영 검색과 같은 SQL) 순서만 바꿔 비교한다. 후보 40 passage → support_group으로 묶고
MOD-02 예산 규칙(첫 그룹은 전체 예산 4000 안이면, 그 뒤는 검색당 몫 3000까지, 첫 초과에서 멈춤)으로
넣은 원문의 gold 근거 재현율을 eval_score와 같은 대조로 잰다.
판본·사건 기준 필터(_basis_fits)는 모든 설정에 똑같이 빼므로 운영 검색과 후보 집합이 조금 다를 수 있다
(설정 사이 비교용).

backend/에서 실행: uv run python ../scripts/retrieval_compare.py holdout7 holdout8 [--out 결과.json]
질의 임베딩은 data/staging/embeddings/eval-query-cache.jsonl을 재사용하고 없으면 Gemini로 만든다.
"""

import argparse
import asyncio
import json
import math
import re
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from agent.app.eval_cli import CASES_DIR, QUERY_CACHE
from agent.app.eval_run import CachingEmbedder, load_passages
from agent.app.eval_score import _recall
from agent.modules.identity_access.service import IdentityService
from agent.modules.knowledge.service import KnowledgeService
from agent.modules.model_integration.gemini_embedding import GeminiEmbeddingModel
from agent.shared.clock import FixedClock
from agent.shared.db import make_engine
from agent.shared.settings import Settings

CANDIDATES = 40
BUDGET = 4000
SHARE = 3000  # 검색당 몫(D-72, 0.75)
RRF_K = 60
_WORD = re.compile(r"[0-9A-Za-z가-힣]+")


def bigrams(text: str) -> list[str]:
    """한국어 키워드 토큰: 단어마다 글자 두 개씩(조사가 붙어도 앞 글자들이 맞는다). 한 글자 단어는 그대로."""
    out: list[str] = []
    for word in _WORD.findall(text.lower()):
        out += [word] if len(word) == 1 else [word[i : i + 2] for i in range(len(word) - 1)]
    return out


def bm25_scores(query: str, docs: list[str], k1: float = 1.2, b: float = 0.75) -> list[float]:
    tokens = [bigrams(d) for d in docs]
    n = len(tokens)
    avg = sum(map(len, tokens)) / n if n else 0
    df = Counter(t for toks in tokens for t in set(toks))
    q = Counter(bigrams(query))
    scores = []
    for toks in tokens:
        tf = Counter(toks)
        s = 0.0
        for term in q:
            if term not in tf:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            s += idf * tf[term] * (k1 + 1) / (tf[term] + k1 * (1 - b + b * len(toks) / (avg or 1)))
        scores.append(s)
    return scores


def ranked(order: list[int]) -> dict[int, int]:
    return {idx: rank for rank, idx in enumerate(order, start=1)}


def orders(passages, query: str) -> dict[str, list[int]]:
    """설정별 후보 순서(passage 색인 목록)."""
    n = len(passages)
    dense = sorted(range(n), key=lambda i: (passages[i].distance, passages[i].passage_id))
    bm = bm25_scores(query, [p.text for p in passages])
    keyword = sorted(range(n), key=lambda i: (-bm[i], passages[i].distance))
    rd, rk = ranked(dense), ranked(keyword)
    rrf = sorted(range(n), key=lambda i: -(1 / (RRF_K + rd[i]) + 1 / (RRF_K + rk[i])))
    # 점수 결합: 코사인 유사도와 BM25를 각각 0~1로 맞춰 평균
    sims = [1 - (p.distance or 0) for p in passages]

    def scale(values):
        lo, hi = min(values), max(values)
        return [(v - lo) / (hi - lo) if hi > lo else 0.0 for v in values]

    s, k = scale(sims), scale(bm)
    fused = sorted(range(n), key=lambda i: -(0.5 * s[i] + 0.5 * k[i]))
    fused_dense_heavy = sorted(range(n), key=lambda i: -(0.7 * s[i] + 0.3 * k[i]))
    return {
        "dense(현재)": dense,
        "keyword(BM25)": keyword,
        "hybrid RRF": rrf,
        "점수 결합 0.5": fused,
        "점수 결합 0.7/0.3": fused_dense_heavy,
    }


async def groups_in_order(knowledge, actor, hits):
    """후보 순서를 지키며 support_group으로 묶는다(운영 _groups는 거리 순으로 다시 정렬하므로 따로 묶는다)."""
    seen, groups = set(), []
    for hit in hits:
        gid = f"{hit.artifact_id}:{hit.support_group}"
        if gid in seen:
            continue
        seen.add(gid)
        members = await knowledge.support_group(actor, hit)
        if members:
            groups.append(members)
    return groups


def pack(groups):
    kept, spent = [], 0
    for index, members in enumerate(groups):
        cost = sum(p.token_estimate for p in members)
        if index == 0:
            if cost > BUDGET:
                break
        elif spent + cost > SHARE:
            break
        spent += cost
        kept.append(members)
    return kept, spent


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("splits", nargs="+")
    parser.add_argument("--out")
    parser.add_argument("--limit", type=int, help="앞 N문항만(확인용)")
    args = parser.parse_args()
    settings = Settings()
    engine = make_engine(settings.database_url, settings.db_connect_timeout_s)
    key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None
    embedder = CachingEmbedder(GeminiEmbeddingModel(api_key=key), QUERY_CACHE)
    cases = []
    for split in args.splits:
        for line in (CASES_DIR / f"{split}.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                case = json.loads(line)
                if case["evidence_sets"]:
                    cases.append(case)
    if args.limit:
        cases = cases[: args.limit]
    asked = datetime.fromisoformat(cases[0]["asked_at"])
    knowledge = KnowledgeService(
        engine, FixedClock(asked), embedder, embedding_model=settings.embedding_model
    )
    identity = IdentityService(engine, FixedClock(asked), settings.session_ttl_s)
    snapshot = await knowledge.current_snapshot()
    rows = []
    try:
        for case in cases:
            actor = await identity.resolve_eval_actor(case["actor"])
            query = " ".join(case["turns"])
            vector = await knowledge.embed_query(query)
            as_of = date.fromisoformat(case["as_of_date"]) if case.get("as_of_date") else asked.date()
            universe = await knowledge.search(
                actor, snapshot, vector, knowledge_as_of=asked, as_of_date=as_of, limit=100_000
            )
            per = {}
            for name, order in orders(universe, query).items():
                hits = [universe[i] for i in order[:CANDIDATES]]
                groups = await groups_in_order(knowledge, actor, hits)
                kept, tokens = pack(groups)
                ids_pool = {p.passage_id for g in groups for p in g}
                ids_kept = {p.passage_id for g in kept for p in g}
                texts = await load_passages(engine, ids_pool)
                pool = [texts[i] for i in ids_pool if i in texts]
                packed = [texts[i] for i in ids_kept if i in texts]
                per[name] = {
                    "recall_pool": _recall(case["evidence_sets"], pool)[0],
                    "recall_budget": _recall(case["evidence_sets"], packed)[0],
                    "tokens": tokens,
                }
            rows.append({"case_id": case["case_id"], "category": case["category"], **{"by": per}})
            print(case["case_id"], {k: round(v["recall_budget"], 2) for k, v in per.items()}, file=sys.stderr)
    finally:
        await engine.dispose()
    names = list(rows[0]["by"])
    base = names[0]
    summary = {}
    for name in names:
        vals = [r["by"][name] for r in rows]
        better = sum(r["by"][name]["recall_budget"] > r["by"][base]["recall_budget"] + 1e-9 for r in rows)
        worse = sum(r["by"][name]["recall_budget"] < r["by"][base]["recall_budget"] - 1e-9 for r in rows)
        summary[name] = {
            "cases": len(vals),
            "recall_pool": round(sum(v["recall_pool"] for v in vals) / len(vals), 3),
            "recall_budget": round(sum(v["recall_budget"] for v in vals) / len(vals), 3),
            "all_evidence_in_budget": sum(v["recall_budget"] == 1.0 for v in vals),
            "mean_tokens": round(sum(v["tokens"] for v in vals) / len(vals)),
            "vs_dense_better_worse": [better, worse],
        }
    result = {
        "splits": args.splits,
        "summary": summary,
        "query_cache": {"hits": embedder.hits, "misses": embedder.misses},
        "rows": rows,
    }
    if args.out:
        Path(args.out).write_text(  # noqa: ASYNC240 - 실험 스크립트 끝에 한 번 쓴다
            json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
