# ruff: noqa: F811  (pytest fixture를 다른 시험 모듈에서 가져와 인자로 쓴다)
"""APP-04 평가 실행기(T-27·T-35 일부). 과금 없음(가짜 모델·글자 2-gram 임베딩).

같은 앱 경로로 문항을 실행하고, 계정 권한·전략 고정·검색 경로·실제 문맥 기록이 결과에 남는지 본다.
"""

import json

from agent.app.eval_run import load_cases, run_cases
from agent.shared.clock import FixedClock
from tests.conftest import make_settings
from tests.knowledge_fixtures import BigramEmbedder
from tests.test_document_agent import ORIGIN, Capturing, final, tool_turn
from tests.test_wiki import _published_wiki, _search, org  # noqa: F401

CASES = [
    {
        "case_id": "EV-T-001",
        "split": "dev",
        "category": "revision",
        "actor": "emp-sales",
        "turns": ["9월 29일에 시작한 외부교육 한도는?"],
    },
    {
        "case_id": "EV-T-002",
        "split": "dev",
        "category": "access",
        "actor": "hr-staff",
        "turns": ["9월 29일에 시작한 외부교육 한도는?"],
    },
]


async def test_runner_records_answers_traces_and_packed_context_per_strategy(org, migrated, tmp_path):
    engine, *_ = await _published_wiki(org)
    out = tmp_path / "results.jsonl"
    settings = make_settings(database_url=migrated, allowed_origins=ORIGIN)
    for strategy in ("raw", "wiki_assisted"):
        model = Capturing([tool_turn(_search()), final("종전 기준입니다.", citations=["c1-1"])] * len(CASES))
        results = await run_cases(
            CASES,
            settings=settings,
            clock=FixedClock(),
            strategy=strategy,
            strict=True,
            out=out,
            chat_model=model,
            embedding_model=BigramEmbedder(),
        )
        assert [r["case_id"] for r in results] == ["EV-T-001", "EV-T-002"]
        for result in results:
            (turn,) = result["turns"]
            assert turn["status"] == 200 and turn["outcome"] == "answered" and turn["citations"]
            (run,) = result["runs"]
            assert (
                run["retrieval_context"]["strategy"] == strategy
                and run["retrieval_context"]["strict"] is True
            )
            (tool,) = result["tools"]
            assert tool["trace"]["effective_strategy"] == strategy and tool["trace"]["pool"]
            assert run["usage"]["input_tokens"] > 0
    lines = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 4 and {x["strategy"] for x in lines} == {"raw", "wiki_assisted"}
    # 문항 계정으로 실행한다(웹 세션과 같은 업무 권한, 평가 출처).
    async with engine.connect() as conn:
        from sqlalchemy import text

        owners = (
            (await conn.execute(text("SELECT DISTINCT owner_user_id FROM conversations"))).scalars().all()
        )
    assert set(owners) == {"emp-sales", "hr-staff"}


def test_load_cases_reads_jsonl_files(tmp_path):
    path = tmp_path / "c.jsonl"
    path.write_text(json.dumps(CASES[0], ensure_ascii=False) + "\n\n", encoding="utf-8")
    assert load_cases([path]) == [CASES[0]]
