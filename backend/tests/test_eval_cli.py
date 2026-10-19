"""평가 CLI의 실패·이어하기 경로(APP-04, 독립 검증 지적 회귀). 과금 없음(가짜 judge·임베더)."""

import argparse
import json

import pytest

from agent.app import eval_cli
from agent.app.eval_run import CachingEmbedder
from agent.modules.model_integration.ports import (
    EmbeddingConfig,
    ModelCallError,
    ModelFailure,
    ModelResponse,
    Usage,
)
from tests.conftest import make_settings
from tests.knowledge_fixtures import BigramEmbedder

CASE = {
    "case_id": "EV-N-001",
    "split": "dev",
    "category": "no_evidence",
    "actor": "emp-sales",
    "asked_at": "2026-10-16T10:00:00+09:00",
    "turns": ["사내 주차 요금은?"],
    "expected_outcome": "insufficient_evidence",
    "required_facts": [],
    "required_exceptions": [],
    "forbidden_claims": ["월 5만 원"],
    "evidence_sets": [],
    "hard_negative_anchors": [],
}


def _result(case_id, strategy, answer):
    return {
        "case_id": case_id,
        "split": "dev",
        "category": "no_evidence",
        "strategy": strategy,
        "strict": True,
        "config": {"budget": 4000},
        "turns": [{"status": 200, "outcome": "insufficient_evidence", "answer": answer, "citations": []}],
        "runs": [],
        "tools": [],
    }


class Judge:
    """첫 호출들은 한도 초과, 그 뒤로는 정상 판정."""

    calls = 0
    fail_first = 1

    def __init__(self, api_key=None):
        pass

    async def complete_once(self, request):
        Judge.calls += 1
        Judge.max_output_tokens = request.model_config.max_output_tokens
        if Judge.calls <= Judge.fail_first:
            raise ModelCallError(ModelFailure.RATE_LIMITED)
        verdict = {
            "facts": [],
            "exceptions": [],
            "forbidden_violated": False,
            "unsupported_claim": False,
            "abstained": True,
            "verdict": "correct",
            "reason": "기권",
        }
        return ModelResponse((), verdict, "gemini-test", "eval_judge", "judge-v1", Usage(10, 5, True))

    async def aclose(self):
        pass


@pytest.fixture
def paths(tmp_path, monkeypatch):
    cases = tmp_path / "cases"
    cases.mkdir()
    (cases / "dev.jsonl").write_text(json.dumps(CASE, ensure_ascii=False) + "\n", encoding="utf-8")
    (cases / "holdout.jsonl").write_text("", encoding="utf-8")
    monkeypatch.setattr(eval_cli, "CASES_DIR", cases)
    monkeypatch.setattr(eval_cli, "RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr(eval_cli, "FREEZE", tmp_path / "results" / "freeze.json")
    monkeypatch.setattr("agent.modules.model_integration.gemini_chat.GeminiJudgeModel", Judge)
    Judge.calls = 0
    return tmp_path


async def test_judge_retries_failed_rows_and_keeps_ids_stable_across_inputs(paths, migrated):
    settings = make_settings(database_url=migrated, judge_model="gemini-test")
    a = paths / "a.jsonl"
    a.write_text(
        json.dumps(_result("EV-N-001", "raw", "근거가 없습니다."), ensure_ascii=False) + "\n", "utf-8"
    )
    b = paths / "b.jsonl"
    b.write_text(
        json.dumps(_result("EV-N-001", "wiki_assisted", "확인할 수 없습니다."), ensure_ascii=False) + "\n",
        "utf-8",
    )
    out = paths / "judge.jsonl"
    args = argparse.Namespace(results=[str(a), str(b)], seed=7, out=str(out), live=True)
    await eval_cli.eval_judge(args, settings)  # 첫 판정은 한도 초과로 멈춘다
    rows = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1 and rows[0]["judge_error"] == "rate_limited"
    # 입력 순서를 바꿔 다시 실행해도 같은 답은 같은 ID이고, 실패했던 답도 다시 판정한다.
    await eval_cli.eval_judge(
        argparse.Namespace(results=[str(b), str(a)], seed=7, out=str(out), live=True), settings
    )
    rows = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    mapping = json.loads(out.with_suffix(".mapping.json").read_text(encoding="utf-8"))
    ok = {mapping[r["answer_id"]]["label"] for r in rows if "judge_error" not in r}
    assert ok == {"raw|strict|b4000", "wiki_assisted|strict|b4000"} and len(mapping) == 2
    merged = eval_cli._judge_by_answer([str(out)])
    assert all("judge_error" not in v for v in merged.values()) and len(merged) == 2
    assert Judge.max_output_tokens >= 4096  # 사고 token까지 담는 상한(1024에서는 판정 JSON이 잘렸다)


async def test_holdout_requires_a_recorded_freeze_with_the_same_budget(paths, migrated):
    settings = make_settings(database_url=migrated)
    run = argparse.Namespace(
        strategy="raw",
        split="holdout",
        budget=8000,
        operational=False,
        cases=None,
        resume=False,
        out=None,
        live=False,
    )
    with pytest.raises(SystemExit, match="동결"):
        await eval_cli.eval_run(run, settings)
    await eval_cli.eval_freeze(argparse.Namespace(budget=4000, reason="dev", force=False), settings)
    with pytest.raises(SystemExit, match="동결"):
        await eval_cli.eval_run(run, settings)  # 동결 예산과 다르다
    with pytest.raises(SystemExit, match="이미 동결"):
        await eval_cli.eval_freeze(argparse.Namespace(budget=8000, reason="바꿈", force=False), settings)


async def test_holdout2_also_requires_the_frozen_budget(paths, migrated):
    settings = make_settings(database_url=migrated)
    run = argparse.Namespace(
        strategy="raw",
        split="holdout2",
        budget=8000,
        operational=False,
        cases=None,
        resume=False,
        out=None,
        live=False,
    )
    with pytest.raises(SystemExit, match="동결"):
        await eval_cli.eval_run(run, settings)


async def test_full_context_baseline_runs_holdout_only_at_the_d50_budget(paths, migrated):
    settings = make_settings(database_url=migrated)
    await eval_cli.eval_freeze(argparse.Namespace(budget=4000, reason="dev", force=False), settings)
    run = argparse.Namespace(
        strategy="full_context_reference",
        split="holdout",
        budget=4000,
        operational=False,
        cases=None,
        resume=False,
        out=None,
        live=False,
    )
    with pytest.raises(SystemExit, match="D-50"):
        await eval_cli.eval_run(run, settings)  # A/B 동결 예산이 아니라 기준선 예산
    run.budget = eval_cli.FULL_CONTEXT_BUDGET
    with pytest.raises(
        SystemExit, match="질문 시각"
    ):  # 동결 검사를 지나 문항 읽기까지 간다(시험 holdout은 비어 있음)
        await eval_cli.eval_run(run, settings)


async def test_run_refuses_to_overwrite_and_resume_skips_only_successful_cases(paths, migrated, capsys):
    settings = make_settings(database_url=migrated)
    out = paths / "r.jsonl"
    out.write_text(
        json.dumps({**_result("EV-N-001", "raw", "x"), "error": "run_exception:X"}) + "\n", "utf-8"
    )
    args = argparse.Namespace(
        strategy="raw",
        split="dev",
        budget=4000,
        operational=False,
        cases=None,
        resume=False,
        out=str(out),
        live=False,
    )
    with pytest.raises(SystemExit, match="덮어쓰지"):
        await eval_cli.eval_run(args, settings)
    args.resume = True
    await eval_cli.eval_run(args, settings)
    assert json.loads(capsys.readouterr().out)["cases"] == 1  # 실패한 문항은 다시 실행 대상이다


async def test_resume_retries_provider_failures_and_moves_them_out_of_the_results(paths, migrated, capsys):
    settings = make_settings(database_url=migrated)
    out = paths / "r.jsonl"
    upstream = {**_result("EV-N-001", "raw", None), "runs": [{"error_code": "MODEL_UPSTREAM_ERROR"}]}
    answered = {**_result("EV-N-002", "raw", "x"), "runs": str([{"error_code": None}])}
    out.write_text("".join(json.dumps(r) + "\n" for r in (upstream, answered)), "utf-8")
    args = argparse.Namespace(
        strategy="raw",
        split="dev",
        budget=4000,
        operational=False,
        cases="EV-N-001,EV-N-002",
        resume=True,
        out=str(out),
        live=False,
    )
    await eval_cli.eval_run(args, settings)
    assert json.loads(capsys.readouterr().out)["cases"] == 1  # 공급자 실패만 다시 돈다
    assert [r["case_id"] for r in eval_cli._read_jsonl(out)] == ["EV-N-002"]
    retried = out.with_name("r.retried.jsonl")
    assert [r["case_id"] for r in eval_cli._read_jsonl(retried)] == ["EV-N-001"]


async def test_query_cache_reuses_vectors_and_keys_include_model_dimension_and_task(tmp_path):
    inner = BigramEmbedder()
    cache = CachingEmbedder(inner, tmp_path / "q.jsonl")
    query = EmbeddingConfig("gemini-embedding-2", 1536, "query")
    first = await cache.embed_once(("외부교육 한도",), query, 10)
    again = CachingEmbedder(inner, tmp_path / "q.jsonl")  # 디스크에서 다시 읽는다
    second = await again.embed_once(("외부교육 한도",), query, 10)
    assert first.vectors == second.vectors and again.hits == 1 and again.misses == 0
    other = await again.embed_once(
        ("외부교육 한도",), EmbeddingConfig("gemini-embedding-2", 1536, "document"), 10
    )
    assert again.misses == 1 and other.vectors  # 작업(task)이 다르면 다시 임베딩한다
