"""MOD-03 도구 실행. T-09 미등록 도구·무효 인자·위조 필드, T-10 단일 분배·receipt."""

import asyncio
import time

import pytest

from agent.modules.tool_execution.executor import ToolExecutor
from agent.modules.training.service import TrainingService
from agent.shared.actor import ActorContext
from agent.shared.clock import FixedClock
from agent.shared.contracts import (
    ExecutionContext,
    ExecutionPolicy,
    RequiredRecordError,
    ToolCallProposal,
    ToolCallRecord,
    ToolExecutionInput,
    TrainingResultReceipt,
)
from agent.shared.errors import ErrorCode

SEC_ID = "11111111-1111-4111-8111-111111111101"
ACTOR = ActorContext("test-a", ("d",), ("employee",), frozenset({"training.read"}), 1, "test_stub")


class RecordingObserver:
    def __init__(self, fail: bool = False) -> None:
        self.receipts: list[TrainingResultReceipt] = []
        self.fail = fail

    async def record_tool_call(self, record: ToolCallRecord) -> None:  # pragma: no cover - MOD-02가 쓴다
        pass

    async def record_training_result(self, receipt: TrainingResultReceipt) -> None:
        if self.fail:
            raise ConnectionError("저장소 장애")
        self.receipts.append(receipt)


def _context(clock: FixedClock, actor: ActorContext = ACTOR) -> ExecutionContext:
    return ExecutionContext(
        request_id="req",
        conversation_id="conv",
        run_id="run-1",
        actor=actor,
        current_time=clock.now(),
        deadline_monotonic=clock.monotonic() + 60,
    )


def _call(name: str, arguments: dict, observer, ordinal: int = 1) -> ToolExecutionInput:
    return ToolExecutionInput(
        proposal=ToolCallProposal(name=name, arguments=arguments, provider_call_id=f"toolu_{ordinal}"),
        call_ordinal=ordinal,
        observer=observer,
    )


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock()


# --- DB 없이 거절되는 경우 ---


def _executor_without_db(clock) -> ToolExecutor:
    return ToolExecutor(TrainingService(engine=None), clock)  # type: ignore[arg-type]


def test_tool_specs_are_only_two_training_tools_without_server_fields(clock):
    specs = _executor_without_db(clock).describe_allowed_tools(_context(clock))
    assert [s.name for s in specs] == ["list_trainings", "get_training"]
    for spec in specs:
        text = str(spec.input_schema)
        for forbidden in ("user_id", "admin", "approved", "field_origins", "observer", "strategy"):
            assert forbidden not in text
        assert "description" not in spec.input_schema  # 인자 모델 docstring(개발용)은 보내지 않는다


def test_no_tools_without_capability(clock):
    actor = ActorContext("x", (), (), frozenset(), 1, "test_stub")
    assert _executor_without_db(clock).describe_allowed_tools(_context(clock, actor)) == ()


@pytest.mark.parametrize(
    ("name", "arguments", "code", "fields"),
    [
        ("create_ticket", {}, ErrorCode.TOOL_NOT_REGISTERED, None),
        ("run_sql", {"sql": "DROP TABLE trainings"}, ErrorCode.TOOL_NOT_REGISTERED, None),
        ("list_trainings", {"user_id": "test-b"}, ErrorCode.TOOL_ARGUMENT_INVALID, ["user_id"]),
        (
            "list_trainings",
            {"admin": True, "approved": True},
            ErrorCode.TOOL_ARGUMENT_INVALID,
            ["admin", "approved"],
        ),
        ("list_trainings", {"limit": 500}, ErrorCode.TOOL_ARGUMENT_INVALID, ["limit"]),
        ("list_trainings", {"date_preset": "last_year"}, ErrorCode.TOOL_ARGUMENT_INVALID, ["date_preset"]),
        ("get_training", {"training_id": "TR-SEC-001"}, ErrorCode.TOOL_ARGUMENT_INVALID, ["training_id"]),
        ("get_training", {}, ErrorCode.TOOL_ARGUMENT_INVALID, ["training_id"]),
    ],
)
async def test_rejected_before_execution(clock, name, arguments, code, fields):
    observer = RecordingObserver()
    result = await _executor_without_db(clock).execute_once(_context(clock), _call(name, arguments, observer))
    assert (result.ok, result.data) == (False, None)
    assert result.error.code is code
    assert result.error.details == ({"field_names": fields} if fields else None)
    assert observer.receipts == []


async def test_tool_without_capability_is_treated_as_unregistered(clock):
    actor = ActorContext("x", (), (), frozenset(), 1, "test_stub")
    result = await _executor_without_db(clock).execute_once(
        _context(clock, actor), _call("list_trainings", {}, RecordingObserver())
    )
    assert result.error.code is ErrorCode.TOOL_NOT_REGISTERED


async def test_expired_deadline_is_timeout(clock):
    context = _context(clock)
    clock.advance(61)
    result = await _executor_without_db(clock).execute_once(
        context, _call("list_trainings", {}, RecordingObserver())
    )
    assert result.error.code is ErrorCode.TOOL_TIMEOUT


# --- DB 사용 ---


async def test_list_dispatches_once_and_records_receipt(seeded_engine, clock):
    observer = RecordingObserver()
    executor = ToolExecutor(TrainingService(seeded_engine), clock)
    result = await executor.execute_once(
        _context(clock), _call("list_trainings", {"date_preset": "next_week"}, observer, ordinal=3)
    )
    assert result.ok and result.error is None
    assert [i["code"] for i in result.data["items"]] == ["TR-SEC-001", "TR-COLLAB-001"]
    assert result.resource_ids[0] == SEC_ID
    assert len(observer.receipts) == 1
    receipt = observer.receipts[0]
    assert (receipt.run_id, receipt.ordinal) == ("run-1", 3)
    assert receipt.training_starts[0] == (SEC_ID, "2026-10-20T14:00:00+09:00")
    assert len(receipt.result_hash) == 64


async def test_empty_list_is_success(seeded_engine, clock):
    executor = ToolExecutor(TrainingService(seeded_engine), clock)
    result = await executor.execute_once(
        _context(clock), _call("list_trainings", {"query": "존재하지 않는 교육"}, RecordingObserver())
    )
    assert result.ok and result.data["items"] == [] and result.data["total"] == 0


async def test_range_error_from_training_module_becomes_argument_error(seeded_engine, clock):
    executor = ToolExecutor(TrainingService(seeded_engine), clock)
    result = await executor.execute_once(
        _context(clock),
        _call(
            "list_trainings",
            {"date_preset": "custom", "start_date": "2026-10-01", "end_date_exclusive": "2027-03-01"},
            RecordingObserver(),
        ),
    )
    assert result.error.code is ErrorCode.TOOL_ARGUMENT_INVALID
    assert result.error.details == {"field_names": ["end_date_exclusive", "start_date"]}


async def test_get_detail_and_not_found(seeded_engine, clock):
    executor = ToolExecutor(TrainingService(seeded_engine), clock)
    found = await executor.execute_once(
        _context(clock), _call("get_training", {"training_id": SEC_ID}, RecordingObserver())
    )
    missing = await executor.execute_once(
        _context(clock),
        _call("get_training", {"training_id": "11111111-1111-4111-8111-999999999999"}, RecordingObserver()),
    )
    assert found.data["location"] == "3층 교육장"
    assert missing.error.code is ErrorCode.TRAINING_NOT_FOUND


async def test_receipt_failure_stops_execution(seeded_engine, clock):
    executor = ToolExecutor(TrainingService(seeded_engine), clock)
    with pytest.raises(RequiredRecordError):
        await executor.execute_once(
            _context(clock), _call("list_trainings", {}, RecordingObserver(fail=True))
        )


async def test_database_failure_is_execution_error_not_empty(clock, migrated):
    from agent.shared.db import make_engine

    broken = make_engine("postgresql+psycopg://u:p@127.0.0.1:1/none_test", connect_timeout_s=2)
    try:
        executor = ToolExecutor(TrainingService(broken), clock)
        result = await executor.execute_once(
            _context(clock), _call("list_trainings", {}, RecordingObserver())
        )
    finally:
        await broken.dispose()
    assert result.ok is False
    assert (result.error.code, result.error.retryable) == (ErrorCode.TOOL_EXECUTION_FAILED, True)


async def test_remaining_deadline_shorter_than_tool_limit_is_used(clock):
    """남은 실행 시간(0.2초)이 도구 상한(10초)보다 짧으면 남은 시간에서 끊는다."""

    class SlowTrainings:
        async def list_trainings(self, search, now):
            await asyncio.sleep(5)

    context = _context(clock)
    clock.advance(59.8)
    started = time.monotonic()
    result = await ToolExecutor(SlowTrainings(), clock).execute_once(  # type: ignore[arg-type]
        context, _call("list_trainings", {}, RecordingObserver())
    )
    assert (result.error.code, result.error.retryable) == (ErrorCode.TOOL_TIMEOUT, True)
    assert time.monotonic() - started < 2


async def test_slow_receipt_is_not_turned_into_tool_timeout(seeded_engine, clock):
    """M1 검증 P2-8: 필수 기록은 도구 시간 제한 밖에서 한다. 느린 기록이 TOOL_TIMEOUT으로 바뀌면 안 된다."""

    class SlowObserver(RecordingObserver):
        async def record_training_result(self, receipt):
            await asyncio.sleep(0.3)
            await super().record_training_result(receipt)

    observer = SlowObserver()
    context = _context(clock)
    context = ExecutionContext(
        request_id=context.request_id,
        conversation_id=context.conversation_id,
        run_id=context.run_id,
        actor=context.actor,
        current_time=context.current_time,
        deadline_monotonic=context.deadline_monotonic,
        policy=ExecutionPolicy(tool_timeout_s=0.1),
    )
    result = await ToolExecutor(TrainingService(seeded_engine), clock).execute_once(
        context, _call("list_trainings", {}, observer)
    )
    assert result.ok, result.error
    assert len(observer.receipts) == 1


async def test_tool_limit_cuts_slow_lookup_even_with_long_deadline(clock):
    """도구 상한(policy)이 남은 실행 시간보다 짧으면 상한에서 끊는다(남은 시간 60초, 상한 0.2초)."""

    class SlowTrainings:
        async def list_trainings(self, search, now):
            await asyncio.sleep(5)

    context = _context(clock)
    context = ExecutionContext(
        request_id="r",
        conversation_id="c",
        run_id="run-1",
        actor=ACTOR,
        current_time=clock.now(),
        deadline_monotonic=clock.monotonic() + 60,
        policy=ExecutionPolicy(tool_timeout_s=0.2),
    )
    started = time.monotonic()
    result = await ToolExecutor(SlowTrainings(), clock).execute_once(  # type: ignore[arg-type]
        context, _call("list_trainings", {}, RecordingObserver())
    )
    assert result.error.code is ErrorCode.TOOL_TIMEOUT
    assert time.monotonic() - started < 2


def test_tool_description_states_limit_range(clock):
    spec = _executor_without_db(clock).describe_allowed_tools(_context(clock))[0]
    assert "1~20" in spec.description


def test_null_arguments_mean_not_given_and_keep_defaults():
    """strict 스키마에서 모델은 선택 인자를 null로 보낸다(MOD-07). 기본값을 null로 덮지 않는다."""
    from agent.modules.tool_execution.executor import ListTicketsArgs, SearchDocumentsArgs, _drop_nulls

    args = SearchDocumentsArgs.model_validate(
        _drop_nulls(
            {
                "query": "q",
                "top_k": None,
                "date_basis": None,
                "as_of_date": None,
                "date_quote": None,
                "event_key": None,
                "other_events": [{"date_basis": "trip_start", "as_of_date": None, "date_quote": None}],
            }
        )
    )
    assert args.date_basis == "current" and args.top_k is None and args.other_events[0].as_of_date is None
    assert (
        ListTicketsArgs.model_validate(_drop_nulls({"status": None, "limit": None, "offset": None})).limit
        == 10
    )
