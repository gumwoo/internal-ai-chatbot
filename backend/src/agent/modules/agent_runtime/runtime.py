"""Execute(context, snapshot, message, observer) → ExecutionResult(MOD-02).

도구 선택 → 인자 검증(MOD-03) → 결과 확인 → 다음 행동/되묻기/완료를 제어한다.
- 상한: 05-agent-execution.md 표(ExecutionPolicy). 시간은 단조 시계와 영속 deadline으로 잰다.
- 재시도: 모델·읽기 도구의 일시 오류만 논리 호출당 1회. SDK 재시도는 MOD-07에서 꺼져 있다.
- 근거 원장: 최종 training_ids는 이번 실행의 도구 결과 또는 검증된 대화 사본에 있던 것만 허용한다.
- 도구 장애(실행 실패·시간 초과)는 재시도 후에도 남으면 실행 실패다. 0건으로 바꾸지 않는다.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from agent.modules.agent_runtime.contracts import (
    FINAL_OUTPUT_SCHEMA,
    ConversationSnapshot,
    ExecutionResult,
    FinalCandidate,
    Outcome,
    RunUsage,
)
from agent.modules.agent_runtime.prompt import PROMPT_VERSION, system_prompt
from agent.modules.model_integration.ports import (
    ChatModel,
    ModelCallError,
    ModelConfig,
    ModelFailure,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolResultContent,
    Usage,
)
from agent.modules.tool_execution.executor import ToolExecutor
from agent.shared.clock import Clock
from agent.shared.contracts import (
    ExecutionContext,
    ExecutionObserver,
    RequiredRecordError,
    ToolCallProposal,
    ToolCallRecord,
    ToolExecutionInput,
    ToolResult,
)
from agent.shared.errors import AppError, ErrorCode

logger = logging.getLogger(__name__)

# 재시도해도 남은 도구 장애. 모델에 되돌려 보정할 대상이 아니라 실행 실패다.
_INFRA_TOOL_ERRORS = frozenset({ErrorCode.TOOL_EXECUTION_FAILED, ErrorCode.TOOL_TIMEOUT})
_TRAINING_SUMMARY_KEYS = ("id", "code", "title", "starts_at", "ends_at", "location", "status")


@dataclass
class _Run:
    context: ExecutionContext
    snapshot: ConversationSnapshot
    observer: ExecutionObserver
    model_attempts: int = 0
    tool_proposals: int = 0
    ordinal: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    usage_complete: bool = True
    model_ids: list[str] = field(default_factory=list)
    records: list[ToolCallRecord] = field(default_factory=list)
    # 이번 실행에서 실제로 조회한 교육(id → 요약). 대화 사본보다 우선한다.
    ledger: dict[str, dict[str, Any]] = field(default_factory=dict)
    # 성공한 교육 목록 조회 수. no_results는 실제 조회가 있었을 때만 인정한다.
    successful_list_lookups: int = 0

    def add_usage(self, usage: Usage) -> None:
        self.input_tokens += usage.input_tokens or 0
        self.output_tokens += usage.output_tokens or 0
        if not usage.complete or usage.input_tokens is None or usage.output_tokens is None:
            self.usage_complete = False

    def usage(self) -> RunUsage:
        return RunUsage(self.input_tokens, self.output_tokens, self.usage_complete, self.model_attempts)

    def allowed_trainings(self) -> dict[str, dict[str, Any]]:
        return {**self.snapshot.training_cache, **self.ledger}

    def failed(self, error: AppError) -> ExecutionResult:
        return ExecutionResult(
            status="failed",
            outcome=None,
            answer=None,
            training_refs=(),
            context_candidate=None,  # 실패에는 상태 후보를 적용하지 않는다(CT-10).
            usage=self.usage(),
            tool_summary=tuple(self.records),
            error=error,
            model_ids=tuple(self.model_ids),
        )


def _model_view(result: ToolResult) -> str:
    """모델에 보여 줄 도구 결과. 오류는 코드·안전 문구·재시도 여부·허용 details만 넣는다."""
    if result.ok:
        payload: dict[str, Any] = {"ok": True, "data": result.data}
    else:
        error = result.error
        assert error is not None  # noqa: S101 - ToolResult 계약상 실패에는 error가 있다
        payload = {
            "ok": False,
            "error": {
                "code": error.code.value,
                "message": error.safe_message,
                "retryable": error.retryable,
                "details": error.details,
            },
        }
    return json.dumps(payload, ensure_ascii=False)


def _next_cache(
    run: _Run, allowed: dict[str, dict[str, Any]], referenced: list[str]
) -> dict[str, dict[str, Any]]:
    """다음 턴에 넘길 검증 사본(최대 N건). 옛 사본 → 이번 결과 → 답이 가리킨 교육 순으로 쌓아 뒤에서 자른다.

    그래서 이번에 다시 조회했거나 답에서 가리킨 교육은 잘려 나가지 않는다.
    """
    order = [i for i in run.snapshot.training_cache if i not in run.ledger and i not in referenced]
    order += [i for i in run.ledger if i not in referenced]
    order += referenced
    keep = order[-run.context.policy.training_cache_size :]
    return {i: allowed[i] for i in keep}


# 모델이 되묻기 판단만 하고 질문 문장을 비운 경우 쓰는 일반 문구(TS-19). 특정 교육을 지어내지 않는다.
CLARIFICATION_FALLBACK = (
    "어떤 교육을 말씀하시는지 알려 주시겠어요? 교육 이름이나 기간을 알려 주시면 찾아보겠습니다."
)


def _fill_empty_clarification(run: _Run, candidate: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """outcome=needs_clarification인데 answer가 비었으면 서버 일반 문구로 채운다.

    다른 outcome의 빈 답은 그대로 둔다(무효 출력으로 실패). 되묻기는 질문 내용이 정해져 있지 않아도
    "어느 교육인지"를 묻는 것으로 충분하지만, 답·0건·근거 부족은 서버가 대신 쓸 수 없다.
    """
    answer = candidate.get("answer")
    if candidate.get("outcome") == "needs_clarification" and isinstance(answer, str) and not answer.strip():
        logger.info("빈 되묻기 답을 서버 문구로 채움 run_id=%s", run.context.run_id)
        return {**candidate, "answer": CLARIFICATION_FALLBACK}, "server_fallback"
    return candidate, "model"


def _output_invalid(run: _Run, reason: str) -> AppError:
    """무효 출력의 이유는 내부 기록(로그·예외 note)에만 남긴다. 사용자 응답에는 안전 문구만 나간다."""
    logger.warning("최종 출력 무효 run_id=%s reason=%s", run.context.run_id, reason)
    error = AppError(ErrorCode.MODEL_OUTPUT_INVALID)
    error.add_note(reason)
    return error


def _arguments_summary(proposal: ToolCallProposal) -> dict[str, Any]:
    # 인자 값은 남기지 않고 키 이름만 남긴다(위조 시도 흔적은 키로 충분하다).
    return {"keys": sorted(str(k) for k in proposal.arguments)[:10]}


def _summaries(result: ToolResult) -> list[dict[str, Any]]:
    data = result.data or {}
    items = data.get("items") if "items" in data else [data]
    return [{k: item[k] for k in _TRAINING_SUMMARY_KEYS} for item in items or [] if "id" in item]


class AgentRuntime:
    def __init__(self, chat: ChatModel, tools: ToolExecutor, clock: Clock, model: ModelConfig) -> None:
        self._chat = chat
        self._tools = tools
        self._clock = clock
        self._model = model

    async def execute(
        self,
        context: ExecutionContext,
        snapshot: ConversationSnapshot,
        message: str,
        observer: ExecutionObserver,
    ) -> ExecutionResult:
        run = _Run(context=context, snapshot=snapshot, observer=observer)
        remaining = self._remaining(context)
        if remaining <= 0:
            return run.failed(AppError(ErrorCode.RUN_TIMEOUT))
        try:
            async with asyncio.timeout(remaining):
                return await self._loop(run, message)
        except TimeoutError:
            return run.failed(AppError(ErrorCode.RUN_TIMEOUT))
        except RequiredRecordError:
            return run.failed(AppError(ErrorCode.PERSISTENCE_FAILED))
        except AppError as error:
            return run.failed(error)

    def _remaining(self, context: ExecutionContext) -> float:
        return context.deadline_monotonic - self._clock.monotonic()

    async def _loop(self, run: _Run, message: str) -> ExecutionResult:
        policy = run.context.policy
        history = run.snapshot.messages[-policy.history_messages :] if policy.history_messages else ()
        messages = [ModelMessage(role=m.role, text=m.text) for m in history]
        messages.append(ModelMessage(role="user", text=message))
        tools = self._tools.describe_allowed_tools(run.context)
        snapshot = run.snapshot
        system = system_prompt(
            run.context.current_time,
            snapshot.training_cache,
            snapshot.last_training_ids,
            snapshot.selected_training_id,
        )

        while True:
            response = await self._call_model(run, tuple(messages), tools, system)
            if not response.wants_tools:
                return self._finish(run, response)
            results: list[ToolResultContent] = []
            for proposal in response.tool_proposals:
                # 무효 인자·미등록 도구도 제안 수에 포함한다(T-09).
                run.tool_proposals += 1
                if run.tool_proposals > policy.max_tool_proposals:
                    raise AppError(ErrorCode.AGENT_LIMIT_EXCEEDED)
                if self._remaining(run.context) <= 0:
                    # 모델 응답 뒤 실행 시간이 다 됐다. 도구 시간 초과가 아니라 실행 시간 초과다.
                    raise AppError(ErrorCode.RUN_TIMEOUT)
                run.ordinal += 1
                result = await self._call_tool(run, proposal, run.ordinal)
                results.append(
                    ToolResultContent(proposal.provider_call_id, _model_view(result), is_error=not result.ok)
                )
            messages.append(response.as_assistant_message())
            messages.append(ModelMessage(role="tool_result", tool_results=tuple(results)))

    async def _call_model(
        self, run: _Run, messages: tuple[ModelMessage, ...], tools, system: str
    ) -> ModelResponse:
        policy = run.context.policy
        retries = 0
        while True:
            if run.model_attempts >= policy.max_model_attempts:
                raise AppError(ErrorCode.AGENT_LIMIT_EXCEEDED)
            remaining = self._remaining(run.context)
            if remaining <= 0:
                raise AppError(ErrorCode.RUN_TIMEOUT)
            timeout = min(policy.model_timeout_s, remaining)
            run.model_attempts += 1
            request = ModelRequest(
                purpose="agent_answer",
                messages=messages,
                tools=tools,
                output_contract=FINAL_OUTPUT_SCHEMA,
                timeout_s=timeout,
                model_config=self._model,
                system=system,
            )
            try:
                async with asyncio.timeout(timeout):
                    response = await self._chat.complete_once(request)
            except TimeoutError:
                error = ModelCallError(ModelFailure.TIMEOUT)
            except ModelCallError as exc:
                error = exc
            else:
                run.add_usage(response.usage)
                run.model_ids.append(response.model_id)
                return response
            run.add_usage(error.usage)
            if error.retryable and retries < policy.max_retries_per_call:
                retries += 1
                continue
            raise error

    async def _call_tool(self, run: _Run, proposal: ToolCallProposal, ordinal: int) -> ToolResult:
        policy = run.context.policy
        attempt = 0
        while True:
            attempt += 1
            started = self._clock.monotonic()
            result = await self._tools.execute_once(
                run.context,
                ToolExecutionInput(proposal=proposal, call_ordinal=ordinal, observer=run.observer),
            )
            record = ToolCallRecord(
                run_id=run.context.run_id,
                ordinal=ordinal,
                name=proposal.name,
                attempt=attempt,
                arguments_summary=_arguments_summary(proposal),
                duration_ms=int((self._clock.monotonic() - started) * 1000),
                ok=result.ok,
                error_code=result.error.code.value if result.error else None,
                error_stage=result.error.stage.value if result.error else None,
                resource_ids=result.resource_ids,
            )
            try:
                await run.observer.record_tool_call(record)
            except RequiredRecordError:
                raise
            except Exception as exc:
                raise RequiredRecordError("도구 호출 기록 저장 실패") from exc
            run.records.append(record)

            if result.ok:
                for summary in _summaries(result):
                    run.ledger.pop(summary["id"], None)  # 다시 조회한 교육은 가장 최근 위치로 옮긴다
                    run.ledger[summary["id"]] = summary
                if proposal.name == "list_trainings":
                    run.successful_list_lookups += 1
                return result
            assert result.error is not None  # noqa: S101 - ToolResult 계약
            if result.error.retryable and attempt <= policy.max_retries_per_call:
                continue
            if result.error.code in _INFRA_TOOL_ERRORS:
                raise result.error
            return result

    def _finish(self, run: _Run, response: ModelResponse) -> ExecutionResult:
        if response.final_candidate is None:
            raise _output_invalid(run, "final candidate missing")
        candidate, answer_source = _fill_empty_clarification(run, response.final_candidate)
        try:
            final = FinalCandidate.model_validate(candidate)
        except ValidationError as exc:
            problems = sorted({f"{'.'.join(map(str, e['loc']))}:{e['type']}" for e in exc.errors()})
            raise _output_invalid(run, f"schema {problems}") from exc
        if final.outcome is Outcome.ACTION_PENDING:
            # 이 구간에는 준비 도구가 없어 확인 대기 상태가 있을 수 없다.
            raise _output_invalid(run, "action_pending without action tool")
        allowed = run.allowed_trainings()
        training_ids = list(dict.fromkeys(final.training_ids))
        selected = final.selected_training_id
        if final.outcome is Outcome.NO_RESULTS:
            # 0건 답은 이번 실행에서 실제로 목록을 조회했을 때만 인정한다(조회 실패·미조회는 0건이 아니다).
            if run.successful_list_lookups == 0:
                raise _output_invalid(run, "no_results without successful list lookup")
            if training_ids:
                raise _output_invalid(run, "no_results with training ids")
        if final.outcome in (Outcome.NEEDS_CLARIFICATION, Outcome.NO_RESULTS) and selected is not None:
            # 되묻는 중이거나 결과가 없으면 선택 상태를 저장하지 않는다(임의 선택 저장 금지).
            logger.info("선택 후보 무시 run_id=%s outcome=%s", run.context.run_id, final.outcome.value)
            selected = None
        # 답의 목록과 선택이 같은 교육을 가리킬 수 있으니 중복을 없앤다(사본 크기 계산이 틀어지지 않게).
        referenced = list(dict.fromkeys([*training_ids, *([selected] if selected else [])]))
        unknown = [training_id for training_id in referenced if training_id not in allowed]
        if unknown:
            # 원장에 없는 교육을 말하면 지어낸 것으로 보고 실패시킨다.
            raise _output_invalid(run, f"{len(unknown)} training id(s) not in ledger")

        return ExecutionResult(
            status="completed",
            outcome=final.outcome,
            answer=final.answer,
            training_refs=tuple(allowed[i] for i in training_ids),
            context_candidate={
                "schema_version": 2,
                "last_training_ids": training_ids,
                "selected_training_id": selected,
                "training_cache": _next_cache(run, allowed, referenced),
                "prompt_version": PROMPT_VERSION,
            },
            usage=run.usage(),
            tool_summary=tuple(run.records),
            error=None,
            model_ids=tuple(run.model_ids),
            answer_source=answer_source,
        )
