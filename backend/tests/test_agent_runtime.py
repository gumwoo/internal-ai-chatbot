"""MOD-02 Agent 실행(가짜 모델, 실제 MOD-03/04). 과금 없음.

T-05 도구 선택·다단계·모호성(교육 범위), T-06 deadline·재시도 상한, T-09 무효 인자 상한 포함,
T-10 단일 분배, 근거 원장(지어낸 교육 ID 거절), 필수 기록 실패.
"""

import asyncio
import json

import pytest

from agent.modules.agent_runtime.contracts import ConversationSnapshot, HistoryMessage, Outcome
from agent.modules.agent_runtime.observer import InMemoryObserver
from agent.modules.agent_runtime.runtime import AgentRuntime
from agent.modules.model_integration.fake import FakeModelClient
from agent.modules.model_integration.ports import (
    ModelCallError,
    ModelConfig,
    ModelFailure,
    ModelResponse,
    Usage,
)
from agent.modules.tool_execution.executor import ToolExecutor
from agent.modules.training.service import TrainingService
from agent.shared.actor import ActorContext
from agent.shared.clock import FixedClock
from agent.shared.contracts import (
    ExecutionContext,
    ExecutionPolicy,
    ToolCallProposal,
    ToolResult,
)
from agent.shared.errors import AppError, ErrorCode

SEC = "11111111-1111-4111-8111-111111111101"
COLLAB = "11111111-1111-4111-8111-111111111102"
ACTOR = ActorContext("test-a", ("d",), ("employee",), frozenset({"training.read"}), 1, "test_stub")
MODEL = ModelConfig(model="fake", max_output_tokens=512, config_version="test")
USAGE = Usage(input_tokens=100, output_tokens=10, complete=True)


def tool_turn(*calls: tuple[str, dict]) -> ModelResponse:
    proposals = tuple(
        ToolCallProposal(name=name, arguments=args, provider_call_id=f"toolu_{i}")
        for i, (name, args) in enumerate(calls)
    )
    return ModelResponse(proposals, None, "fake", "agent_answer", "test", USAGE)


def final(answer="답", outcome="answered", ids=(), selected=None) -> ModelResponse:
    candidate = {
        "answer": answer,
        "outcome": outcome,
        "training_ids": list(ids),
        "selected_training_id": selected,
    }
    return ModelResponse((), candidate, "fake", "agent_answer", "test", USAGE)


def _context(
    clock: FixedClock, seconds: float = 60, policy: ExecutionPolicy | None = None
) -> ExecutionContext:
    return ExecutionContext(
        request_id="req",
        conversation_id="conv",
        run_id="run-1",
        actor=ACTOR,
        current_time=clock.now(),
        deadline_monotonic=clock.monotonic() + seconds,
        policy=policy or ExecutionPolicy(),
    )


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock()


def _runtime(script, engine, clock, tools=None) -> tuple[AgentRuntime, FakeModelClient]:
    model = FakeModelClient(script)
    executor = tools or ToolExecutor(TrainingService(engine), clock)
    return AgentRuntime(model, executor, clock, MODEL), model


async def _run(runtime, clock, message="다음 주 교육 알려줘", snapshot=None, observer=None, **context_kwargs):
    return await runtime.execute(
        _context(clock, **context_kwargs),
        snapshot or ConversationSnapshot(),
        message,
        observer or InMemoryObserver(),
    )


# --- 정상 흐름 ---


async def test_next_week_uses_real_tool_result(seeded_engine, clock):
    runtime, model = _runtime(
        [
            tool_turn(("list_trainings", {"date_preset": "next_week"})),
            final("두 건입니다", ids=(SEC, COLLAB)),
        ],
        seeded_engine,
        clock,
    )
    observer = InMemoryObserver()
    result = await _run(runtime, clock, observer=observer)
    assert result.status == "completed" and result.outcome is Outcome.ANSWERED
    assert [r["code"] for r in result.training_refs] == ["TR-SEC-001", "TR-COLLAB-001"]
    assert result.training_refs[0]["location"] == "3층 교육장"
    assert len(observer.training_results) == 1 and len(observer.tool_calls) == 1
    assert (result.usage.input_tokens, result.usage.output_tokens, result.usage.model_attempts) == (
        200,
        20,
        2,
    )
    assert result.context_candidate["last_training_ids"] == [SEC, COLLAB]
    # 두 번째 모델 호출은 도구 결과를 실제로 받았다.
    tool_message = model.requests[1].messages[-1]
    payload = json.loads(tool_message.tool_results[0].content)
    assert payload["ok"] is True and payload["data"]["total"] == 2


async def test_multi_step_list_then_detail(seeded_engine, clock):
    runtime, _ = _runtime(
        [
            tool_turn(("list_trainings", {"query": "보안"})),
            tool_turn(("get_training", {"training_id": SEC})),
            final("3층 교육장에서 열립니다", ids=(SEC,), selected=SEC),
        ],
        seeded_engine,
        clock,
    )
    result = await _run(runtime, clock, "보안 교육 설명이랑 장소 알려줘")
    assert result.status == "completed"
    assert [r.ordinal for r in result.tool_summary] == [1, 2]
    assert result.context_candidate["selected_training_id"] == SEC


async def test_ambiguous_reference_from_cache_asks_back_without_tools(seeded_engine, clock):
    snapshot = ConversationSnapshot(
        messages=(
            HistoryMessage("user", "다음 주 교육 알려줘"),
            HistoryMessage("assistant", "보안 교육과 협업 도구 교육이 있습니다."),
        ),
        training_cache={SEC: {"id": SEC, "title": "보안"}, COLLAB: {"id": COLLAB, "title": "협업"}},
        last_training_ids=(SEC, COLLAB),
    )
    runtime, model = _runtime(
        [final("어느 교육을 말씀하시나요?", outcome="needs_clarification", ids=(SEC, COLLAB))],
        seeded_engine,
        clock,
    )
    result = await _run(runtime, clock, "그 교육 장소 어디야?", snapshot=snapshot)
    assert result.outcome is Outcome.NEEDS_CLARIFICATION
    assert result.context_candidate["selected_training_id"] is None
    assert [m.role for m in model.requests[0].messages] == ["user", "assistant", "user"]


async def test_no_results_is_normal_outcome(seeded_engine, clock):
    runtime, _ = _runtime(
        [tool_turn(("list_trainings", {"query": "없는 교육"})), final("없습니다", outcome="no_results")],
        seeded_engine,
        clock,
    )
    result = await _run(runtime, clock, "없는 교육 일정 있어?")
    assert (result.status, result.outcome, result.error) == ("completed", Outcome.NO_RESULTS, None)


async def test_history_is_trimmed_to_policy(seeded_engine, clock):
    snapshot = ConversationSnapshot(messages=tuple(HistoryMessage("user", f"m{i}") for i in range(30)))
    runtime, model = _runtime([final()], seeded_engine, clock)
    await _run(runtime, clock, "안녕", snapshot=snapshot)
    texts = [m.text for m in model.requests[0].messages]
    # 현재 사용자 턴은 자료 블록 뒤에 질문이 온다(P-13 B).
    assert len(texts) == 13 and texts[0] == "m18" and texts[-1].endswith("[사용자 질문]\n안녕")


async def test_prompt_carries_server_time_and_only_allowed_tools(seeded_engine, clock):
    runtime, model = _runtime([final()], seeded_engine, clock)
    await _run(runtime, clock, "안녕")
    request = model.requests[0]
    assert "2026-10-16T10:00+09:00" in request.system and "금요일" in request.system
    # smoke 0건 시나리오 대응 규칙(m1-training-2): 조회 전 최종 답 금지, 중간 안내를 최종 답으로 쓰지 않음.
    assert "조회를 마치기 전에는 최종 답을 내지 않는다" in request.system
    assert "12월 25일" not in request.system  # 시험 문항을 프롬프트 예시로 넣지 않는다
    assert [t.name for t in request.tools] == ["list_trainings", "get_training"]
    assert request.output_contract["required"] == [
        "answer",
        "outcome",
        "training_ids",
        "selected_training_id",
        "citation_ids",
    ]


# --- 근거 원장과 출력 검증 ---


@pytest.mark.parametrize(
    "bad_final",
    [
        final("지어낸 교육", ids=("11111111-1111-4111-8111-999999999999",)),
        final("선택만 지어냄", selected="11111111-1111-4111-8111-999999999999"),
        final("확인 대기", outcome="action_pending"),
        ModelResponse((), {"answer": "필드 누락"}, "fake", "agent_answer", "test", USAGE),
        ModelResponse(
            (),
            {"answer": "", "outcome": "answered", "training_ids": [], "selected_training_id": None},
            "fake",
            "agent_answer",
            "test",
            USAGE,
        ),  # noqa: E501
        ModelResponse((), None, "fake", "agent_answer", "test", USAGE),
    ],
)
async def test_invalid_final_fails_without_context(seeded_engine, clock, bad_final):
    runtime, _ = _runtime([bad_final], seeded_engine, clock)
    result = await _run(runtime, clock)
    assert result.status == "failed"
    assert result.error.code is ErrorCode.MODEL_OUTPUT_INVALID
    assert (result.answer, result.context_candidate) == (None, None)
    # 무효 이유는 내부 note로 남고 사용자용 오류 응답에는 들어가지 않는다.
    assert result.error.__notes__
    envelope = str(result.error.to_envelope("req"))
    for note in result.error.__notes__:
        assert note not in envelope


# --- 상한·재시도 ---


async def test_invalid_arguments_count_toward_tool_limit(seeded_engine, clock):
    forged = ("list_trainings", {"user_id": "test-b", "admin": True})
    runtime, model = _runtime(
        [tool_turn(forged, forged), tool_turn(forged, forged), tool_turn(forged)], seeded_engine, clock
    )
    result = await _run(runtime, clock)
    assert result.status == "failed" and result.error.code is ErrorCode.AGENT_LIMIT_EXCEEDED
    assert len(result.tool_summary) == 4
    assert all(r.error_code == "TOOL_ARGUMENT_INVALID" for r in result.tool_summary)
    assert result.tool_summary[0].arguments_summary == {"keys": ["admin", "user_id"]}
    # 거절 결과는 모델에 오류로 되돌아갔다.
    returned = json.loads(model.requests[1].messages[-1].tool_results[0].content)
    assert returned["error"]["code"] == "TOOL_ARGUMENT_INVALID"


async def test_forged_argument_then_corrected_call_completes(seeded_engine, clock):
    runtime, _ = _runtime(
        [
            tool_turn(("list_trainings", {"date_preset": "next_week", "approved": True})),
            tool_turn(("list_trainings", {"date_preset": "next_week"})),
            final("두 건", ids=(SEC, COLLAB)),
        ],
        seeded_engine,
        clock,
    )
    result = await _run(runtime, clock)
    assert result.status == "completed"
    assert [r.ok for r in result.tool_summary] == [False, True]


async def test_model_attempt_limit(seeded_engine, clock):
    turns = [tool_turn(("list_trainings", {})) for _ in range(3)]
    policy = ExecutionPolicy(max_model_attempts=3, max_tool_proposals=10)
    runtime, model = _runtime(turns, seeded_engine, clock)
    result = await _run(runtime, clock, policy=policy)
    assert result.error.code is ErrorCode.AGENT_LIMIT_EXCEEDED
    assert len(model.requests) == 3


async def test_retryable_model_error_retried_once_then_succeeds(seeded_engine, clock):
    runtime, model = _runtime([ModelCallError(ModelFailure.RATE_LIMITED), final()], seeded_engine, clock)
    result = await _run(runtime, clock, "안녕")
    assert result.status == "completed" and len(model.requests) == 2
    assert result.usage.complete is False  # 실패한 시도의 사용량은 모른다


async def test_retryable_model_error_not_retried_twice(seeded_engine, clock):
    errors = [ModelCallError(ModelFailure.UPSTREAM_UNAVAILABLE) for _ in range(3)]
    runtime, model = _runtime(errors, seeded_engine, clock)
    result = await _run(runtime, clock, "안녕")
    assert result.error.code is ErrorCode.MODEL_UPSTREAM_ERROR and len(model.requests) == 2


async def test_non_retryable_model_error_fails_immediately(seeded_engine, clock):
    runtime, model = _runtime([ModelCallError(ModelFailure.NOT_CONFIGURED)], seeded_engine, clock)
    result = await _run(runtime, clock, "안녕")
    assert result.error.code is ErrorCode.MODEL_NOT_CONFIGURED and len(model.requests) == 1


class _ScriptedTools:
    """도구 결과를 미리 정한 실행기. 장애·재시도 경로만 본다."""

    def __init__(self, results: list[ToolResult]) -> None:
        self.results = results
        self.calls = 0

    def describe_allowed_tools(self, context):
        return ()

    async def execute_once(self, context, call):
        self.calls += 1
        return self.results.pop(0)


async def test_tool_infra_failure_after_retry_fails_run_not_zero_results(seeded_engine, clock):
    failing = ToolResult.failure(AppError(ErrorCode.TOOL_EXECUTION_FAILED, retryable=True))
    tools = _ScriptedTools([failing, failing])
    runtime, model = _runtime([tool_turn(("list_trainings", {}))], seeded_engine, clock, tools=tools)
    result = await _run(runtime, clock)
    assert result.status == "failed" and result.error.code is ErrorCode.TOOL_EXECUTION_FAILED
    assert tools.calls == 2 and [r.attempt for r in result.tool_summary] == [1, 2]
    assert len(model.requests) == 1  # 실패를 모델에 넘겨 "0건"으로 포장하지 않는다


async def test_tool_retry_success_keeps_same_ordinal(seeded_engine, clock):
    failing = ToolResult.failure(AppError(ErrorCode.TOOL_TIMEOUT, retryable=True))
    ok = ToolResult.success({"items": [], "total": 0})
    tools = _ScriptedTools([failing, ok])
    runtime, _ = _runtime(
        [tool_turn(("list_trainings", {})), final(outcome="no_results")], seeded_engine, clock, tools=tools
    )
    result = await _run(runtime, clock)
    assert result.status == "completed"
    assert [(r.ordinal, r.attempt, r.ok) for r in result.tool_summary] == [(1, 1, False), (1, 2, True)]


async def test_required_record_failure_stops_further_calls(seeded_engine, clock):
    class BrokenObserver(InMemoryObserver):
        async def record_tool_call(self, record):
            raise ConnectionError("기록 저장소 장애")

    runtime, model = _runtime([tool_turn(("list_trainings", {})), final()], seeded_engine, clock)
    result = await _run(runtime, clock, observer=BrokenObserver())
    assert result.error.code is ErrorCode.PERSISTENCE_FAILED
    assert len(model.requests) == 1


async def test_expired_deadline_fails_before_any_call(seeded_engine, clock):
    runtime, model = _runtime([final()], seeded_engine, clock)
    result = await _run(runtime, clock, seconds=0)
    assert result.error.code is ErrorCode.RUN_TIMEOUT and model.requests == []


async def test_hanging_model_ends_at_run_deadline(seeded_engine, clock):
    class HangingModel:
        async def complete_once(self, request):
            await asyncio.sleep(30)

    runtime = AgentRuntime(HangingModel(), ToolExecutor(TrainingService(seeded_engine), clock), clock, MODEL)
    started = asyncio.get_running_loop().time()
    result = await runtime.execute(
        _context(clock, seconds=0.3), ConversationSnapshot(), "안녕", InMemoryObserver()
    )
    assert result.error.code is ErrorCode.RUN_TIMEOUT
    assert asyncio.get_running_loop().time() - started < 3


# --- M1 검증 보강: 서버 쪽 강제(가짜 모델이 문제 값을 직접 낸다) ---


async def test_clarification_never_stores_selection_even_if_model_sends_one(seeded_engine, clock):
    snapshot = ConversationSnapshot(training_cache={SEC: {"id": SEC}, COLLAB: {"id": COLLAB}})
    runtime, _ = _runtime(
        [final("어느 교육인가요?", outcome="needs_clarification", ids=(SEC, COLLAB), selected=SEC)],
        seeded_engine,
        clock,
    )
    result = await _run(runtime, clock, "그 교육 어디야?", snapshot=snapshot)
    assert result.status == "completed"
    assert result.context_candidate["selected_training_id"] is None


@pytest.mark.parametrize(
    ("script", "reason"),
    [
        ([final("없습니다", outcome="no_results")], "without successful list lookup"),
        (
            [tool_turn(("list_trainings", {"limit": 99})), final("없습니다", outcome="no_results")],
            "without successful list lookup",
        ),
        (
            [
                tool_turn(("list_trainings", {"date_preset": "next_week"})),
                final("없음", outcome="no_results", ids=(SEC,)),
            ],
            "no_results with training ids",
        ),
    ],
)
async def test_no_results_requires_a_real_lookup(seeded_engine, clock, script, reason):
    runtime, _ = _runtime(script, seeded_engine, clock)
    result = await _run(runtime, clock)
    assert result.status == "failed" and result.error.code is ErrorCode.MODEL_OUTPUT_INVALID
    assert any(reason in note for note in result.error.__notes__)


async def test_relooked_and_referenced_trainings_stay_in_cache(seeded_engine, clock):
    """사본이 20건으로 꽉 찬 상태에서 첫 사본(SEC)을 다시 조회해 답하면 SEC가 사본에 남아야 한다."""
    cache = {SEC: {"id": SEC}} | {f"old-{i}": {"id": f"old-{i}"} for i in range(19)}
    snapshot = ConversationSnapshot(training_cache=cache)
    runtime, _ = _runtime(
        [
            tool_turn(("list_trainings", {"date_preset": "next_week"})),
            final("보안 교육", ids=(SEC,), selected=SEC),
        ],
        seeded_engine,
        clock,
    )
    result = await _run(runtime, clock, snapshot=snapshot)
    kept = result.context_candidate["training_cache"]
    assert len(kept) == 20
    assert SEC in kept and COLLAB in kept  # 다시 조회한 SEC, 새로 조회한 COLLAB 모두 유지
    assert list(kept)[-1] == SEC  # 답이 가리킨 교육이 가장 최근
    # 21건(옛 사본 20 + 새 COLLAB 1) 중 가장 오래된 1건만 빠진다.
    assert "old-0" not in kept and "old-1" in kept


async def test_deadline_exhausted_after_model_reply_is_run_timeout(seeded_engine, clock):
    class SlowThinkingModel(FakeModelClient):
        async def complete_once(self, request):
            clock.advance(61)  # 모델 응답 사이에 실행 시간이 다 됐다
            return await super().complete_once(request)

    model = SlowThinkingModel([tool_turn(("list_trainings", {}))])
    runtime = AgentRuntime(model, ToolExecutor(TrainingService(seeded_engine), clock), clock, MODEL)
    result = await runtime.execute(_context(clock), ConversationSnapshot(), "질문", InMemoryObserver())
    assert result.error.code is ErrorCode.RUN_TIMEOUT
    assert result.tool_summary == ()


def test_default_policy_matches_spec_table():
    """05-agent-execution.md 실행 상한 표의 초기값."""
    policy = ExecutionPolicy()
    assert (policy.run_timeout_s, policy.max_model_attempts, policy.max_tool_proposals) == (60, 6, 4)
    assert (policy.max_retries_per_call, policy.model_timeout_s, policy.tool_timeout_s) == (1, 20, 10)
    assert (policy.history_messages, policy.training_cache_size) == (12, 20)


async def test_model_timeout_is_min_of_limit_and_remaining(seeded_engine, clock):
    runtime, model = _runtime([final()], seeded_engine, clock)
    await _run(runtime, clock, "안녕")
    assert model.requests[0].timeout_s == 20  # 남은 시간 60초 > 상한 20초
    runtime, model = _runtime([final()], seeded_engine, clock)
    await _run(runtime, clock, "안녕", seconds=5)
    assert model.requests[0].timeout_s == 5  # 남은 시간이 더 짧으면 남은 시간


async def test_model_limit_cuts_hanging_model_even_with_long_deadline(seeded_engine, clock):
    class HangingModel:
        calls = 0

        async def complete_once(self, request):
            HangingModel.calls += 1
            await asyncio.sleep(30)

    policy = ExecutionPolicy(model_timeout_s=0.2)
    runtime = AgentRuntime(HangingModel(), ToolExecutor(TrainingService(seeded_engine), clock), clock, MODEL)
    started = asyncio.get_running_loop().time()
    result = await runtime.execute(
        _context(clock, policy=policy), ConversationSnapshot(), "안녕", InMemoryObserver()
    )
    assert result.error.code is ErrorCode.MODEL_UPSTREAM_ERROR  # 모델 시간 초과(재시도 1회 후)
    assert HangingModel.calls == 2
    assert asyncio.get_running_loop().time() - started < 3


def test_output_schema_does_not_offer_action_pending():
    from agent.modules.agent_runtime.contracts import FINAL_OUTPUT_SCHEMA

    assert "action_pending" not in FINAL_OUTPUT_SCHEMA["properties"]["outcome"]["enum"]


# --- TS-19: 되묻기에서 질문을 비운 모델 출력 ---


@pytest.mark.parametrize("empty", ["", "   "])
async def test_empty_clarification_is_filled_by_server(seeded_engine, clock, empty):
    from agent.modules.agent_runtime.runtime import CLARIFICATION_FALLBACK

    runtime, _ = _runtime([final(empty, outcome="needs_clarification")], seeded_engine, clock)
    result = await _run(runtime, clock, "그 교육 장소가 어디였지?")
    assert result.status == "completed" and result.outcome is Outcome.NEEDS_CLARIFICATION
    assert result.answer == CLARIFICATION_FALLBACK
    assert result.answer_source == "server_fallback"
    assert result.training_refs == ()


@pytest.mark.parametrize("outcome", ["answered", "no_results", "insufficient_evidence"])
async def test_empty_answer_for_other_outcomes_still_fails(seeded_engine, clock, outcome):
    tools = [tool_turn(("list_trainings", {}))] if outcome == "no_results" else []
    runtime, _ = _runtime([*tools, final("", outcome=outcome)], seeded_engine, clock)
    result = await _run(runtime, clock)
    assert result.status == "failed" and result.error.code is ErrorCode.MODEL_OUTPUT_INVALID


async def test_model_written_clarification_is_kept(seeded_engine, clock):
    runtime, _ = _runtime([final("어느 교육인가요?", outcome="needs_clarification")], seeded_engine, clock)
    result = await _run(runtime, clock, "그 교육?")
    assert (result.answer, result.answer_source) == ("어느 교육인가요?", "model")


def test_prompt_requires_question_text_for_clarification():
    from agent.modules.agent_runtime.prompt import PROMPT_VERSION, system_prompt
    from agent.shared.clock import FIXTURE_NOW

    prompt = system_prompt(FIXTURE_NOW)
    assert PROMPT_VERSION == "m3-docs-5"
    assert "되묻는 경우에도 answer에는 사용자에게 할 질문을 한국어 문장으로 쓴다" in prompt
    assert "어떤 outcome이든 비워 두지 않는다" in prompt


# --- P-12 B: CP-07 재대조 ---


class _Reader:
    def __init__(self, pairs=None, fail=False):
        self.pairs, self.fail, self.calls = pairs or set(), fail, 0

    async def verified_training_pairs(self, conversation_id):
        self.calls += 1
        if self.fail:
            raise RuntimeError("db down")
        return self.pairs


def _snapshot_with_copy():
    from agent.modules.agent_runtime.contracts import ConversationSnapshot

    summary = {"id": "t1", "code": "TR-1", "title": "보안", "starts_at": "2026-10-20T14:00:00+09:00"}
    return ConversationSnapshot(
        training_cache={"t1": summary}, last_training_ids=("t1",), selected_training_id="t1"
    )


async def test_runtime_reverifies_copy_with_cp07_reader(seeded_engine, clock):
    model = FakeModelClient([final()])
    reader = _Reader(pairs=set())
    runtime = AgentRuntime(
        model, ToolExecutor(TrainingService(seeded_engine), clock), clock, MODEL, evidence_reader=reader
    )
    await _run(runtime, clock, "그 교육?", snapshot=_snapshot_with_copy())
    assert reader.calls == 1
    turn = model.requests[0].messages[-1].text
    assert "TR-1" not in turn and turn.startswith("[대화 자료] 없음")
    kept = _Reader(pairs={("t1", "2026-10-20T14:00:00+09:00")})
    model = FakeModelClient([final()])
    runtime = AgentRuntime(
        model, ToolExecutor(TrainingService(seeded_engine), clock), clock, MODEL, evidence_reader=kept
    )
    await _run(runtime, clock, "그 교육?", snapshot=_snapshot_with_copy())
    assert "TR-1" in model.requests[0].messages[-1].text


async def test_cp07_reader_failure_fails_run(seeded_engine, clock):
    model = FakeModelClient([final()])
    runtime = AgentRuntime(
        model,
        ToolExecutor(TrainingService(seeded_engine), clock),
        clock,
        MODEL,
        evidence_reader=_Reader(fail=True),
    )
    result = await _run(runtime, clock, "그 교육?", snapshot=_snapshot_with_copy())
    assert result.status == "failed" and result.error.code.value == "PERSISTENCE_FAILED"
    assert model.requests == []
