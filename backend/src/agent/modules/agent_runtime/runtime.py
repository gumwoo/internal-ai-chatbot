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
from dataclasses import dataclass, field, replace
from datetime import date
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
from agent.modules.agent_runtime.dates import verify_event_date
from agent.modules.agent_runtime.prompt import (
    EMPTY_ANSWER_RETRY,
    PROMPT_VERSION,
    conversation_data,
    neutralize,
    system_prompt,
    user_turn,
)
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
from agent.shared.clock import KST, Clock
from agent.shared.contracts import (
    ConversationEvidenceReader,
    ExecutionContext,
    ExecutionObserver,
    ProgressStage,
    RequiredRecordError,
    ToolCallProposal,
    ToolCallRecord,
    ToolExecutionInput,
    ToolResult,
)
from agent.shared.errors import AppError, ErrorCode
from agent.shared.ticket_origins import FREE_TEXT_FIELDS, locate

logger = logging.getLogger(__name__)

# 재시도해도 남은 도구 장애. 모델에 되돌려 보정할 대상이 아니라 실행 실패다.
_INFRA_TOOL_ERRORS = frozenset({ErrorCode.TOOL_EXECUTION_FAILED, ErrorCode.TOOL_TIMEOUT})
_TRAINING_SUMMARY_KEYS = ("id", "code", "title", "starts_at", "ends_at", "location", "status")
# 도구 이름 → 진행 단계. 목록에 없는 이름(미등록 도구 제안)은 단계를 남기지 않는다.
_TOOL_STAGES = {
    "list_trainings": ProgressStage.TRAINING_LOOKUP,
    "get_training": ProgressStage.TRAINING_LOOKUP,
    "search_documents": ProgressStage.DOCUMENT_SEARCH,
    "list_it_tickets": ProgressStage.TICKET_LOOKUP,
    "get_it_ticket": ProgressStage.TICKET_LOOKUP,
    "prepare_it_ticket": ProgressStage.TICKET_PREPARE,
}
# 모델에 보여 줄 원문 passage 필드. 서버 내부 값(passage_id·token_estimate·snapshot)은 넣지 않는다.
_PASSAGE_VIEW_KEYS = (
    "citation_id",
    "title",
    "version",
    "document_type",
    "source_role",
    "document_role",
    "edition_state",
    "effective_from",
    "effective_to",
    "heading",
    "section_path",
    "text",
)


@dataclass
class _Run:
    context: ExecutionContext
    snapshot: ConversationSnapshot
    observer: ExecutionObserver
    model_attempts: int = 0
    empty_answer_retries: int = 0
    # M5: 이번 run에서 조회한 티켓(답의 의존 자원)과 준비한 root draft 미리보기(action_id → preview).
    ticket_refs: dict[str, dict[str, Any]] = field(default_factory=dict)
    prepared: dict[str, dict[str, Any]] = field(default_factory=dict)
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
    # 근거 원장: 이번 실행에서 모델 문맥에 실제로 들어간 원문 passage(citation_id → 서버 값).
    citations: dict[str, dict[str, Any]] = field(default_factory=dict)
    evidence_tokens: int = 0
    # 예산 때문에 넣지 못한 support_group ID(내부 trace, evidence_budget_exceeded).
    dropped_group_ids: list[str] = field(default_factory=list)
    # 어떤 검색의 대표 그룹이 예산 때문에 빠졌는가(그 결론은 기권 대상).
    required_group_missing: bool = False
    # 대표 그룹이 빠진 검색 호출의 citation 접두어(c{순번}). 그 호출의 결론은 기권 대상이다.
    missing_required_calls: set[str] = field(default_factory=set)
    # 적용 원규정 판본이 없는 사건 문맥(event_key, date_basis, as_of_date)(T-17).
    # 검색 호출이 아니라 사건 단위다.
    normative_gap_contexts: set[tuple] = field(default_factory=set)
    # 이미 문맥에 넣은 (그룹, 사건, 날짜 기준, 날짜) → 그때 붙인 citation_id. 같은 사건의 같은 검색 반복만
    # 재사용한다. 사건·날짜가 다르면 근거 연결을 합치지 않는다(05-retrieval-assembly 3항).
    seen_groups: dict[tuple, list[str]] = field(default_factory=dict)
    # 현재 사용자 질문(사건 날짜 인용 대조용).
    message: str = ""
    # 검색 호출별 resolution·되묻기·미지원(서버 결론 매핑에 쓴다).
    search_results: list[dict[str, Any]] = field(default_factory=list)

    def add_usage(self, usage: Usage) -> None:
        self.input_tokens += usage.input_tokens or 0
        self.output_tokens += usage.output_tokens or 0
        if not usage.complete or usage.input_tokens is None or usage.output_tokens is None:
            self.usage_complete = False

    def usage(self) -> RunUsage:
        return RunUsage(
            self.input_tokens,
            self.output_tokens,
            self.usage_complete,
            self.model_attempts,
            self.empty_answer_retries,
        )

    def allowed_trainings(self) -> dict[str, dict[str, Any]]:
        return {**self.snapshot.training_cache, **self.ledger}

    def evidence_trace(self) -> dict[str, Any] | None:
        if not self.citations and not self.dropped_group_ids:
            return None
        return {
            "context_token_limit": self.context.policy.final_context_token_limit,
            "evidence_tokens": self.evidence_tokens,
            "packed": [
                {
                    "citation_id": cid,
                    "passage_id": c.get("passage_id"),
                    "source_file_id": c.get("source_file_id"),
                }
                for cid, c in self.citations.items()
            ],
            "dropped_group_ids": list(self.dropped_group_ids),
            "required_group_missing": self.required_group_missing,
        }

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
            evidence_trace=self.evidence_trace(),
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


async def _stage(run: _Run, stage: ProgressStage) -> None:
    """진행 단계를 남긴다. 필수 기록이 아니라 실패해도 실행을 계속한다(진단 로그만)."""
    try:
        await run.observer.record_stage(run.context.run_id, stage)
    except Exception as exc:
        logger.warning("진행 단계 기록 실패 run_id=%s error=%s", run.context.run_id, type(exc).__name__)


# 모델이 되묻기 판단만 하고 질문 문장을 비운 경우 쓰는 일반 문구(TS-19). 특정 교육을 지어내지 않는다.
CLARIFICATION_FALLBACK = (
    "어떤 교육을 말씀하시는지 알려 주시겠어요? 교육 이름이나 기간을 알려 주시면 찾아보겠습니다."
)


def _empty_first_answer(run: _Run, response: ModelResponse, tools) -> bool:
    """도구를 하나도 부르지 않은 첫 응답이 빈 answer인가.

    D-52: 빈 되묻기도 포함한다. 도구 없이 낸 빈 되묻기는 질문 문장이 없어 무엇을 물을지 모르는 상태다
    (2026-10-18 실제 모델: 날짜가 있는 규정 질문에 검색 없이 빈 되묻기 → 교육 되묻기 서버 문구가 나감).
    강제 재호출(D-41) 뒤에도 빈 되묻기면 그때 서버 일반 문구로 채운다(TS-19).
    """
    candidate = response.final_candidate
    if not tools or run.tool_proposals or run.empty_answer_retries or not isinstance(candidate, dict):
        return False
    answer = candidate.get("answer")
    return isinstance(answer, str) and not answer.strip()


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
    def __init__(
        self,
        chat: ChatModel,
        tools: ToolExecutor,
        clock: Clock,
        model: ModelConfig,
        evidence_reader: ConversationEvidenceReader | None = None,
    ) -> None:
        self._chat = chat
        self._tools = tools
        self._clock = clock
        self._model = model
        self._evidence_reader = evidence_reader

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
                run.snapshot = await self._reverify(run)
                return await self._loop(run, message)
        except TimeoutError:
            return run.failed(AppError(ErrorCode.RUN_TIMEOUT))
        except RequiredRecordError:
            return run.failed(AppError(ErrorCode.PERSISTENCE_FAILED))
        except AppError as error:
            return run.failed(error)

    async def _reverify(self, run: _Run) -> ConversationSnapshot:
        """CP-07(P-12 B): 대화 사본을 실행 시점의 실제 receipt와 다시 대조한다.

        MOD-01이 snapshot을 만들 때 거른 것이 첫 겹이고, 이것이 둘째 겹이다.
        """
        snapshot = run.snapshot
        if self._evidence_reader is None or not snapshot.training_cache:
            return snapshot
        try:
            pairs = await self._evidence_reader.verified_training_pairs(run.context.conversation_id)
        except Exception as exc:
            raise RequiredRecordError("대화 사본 대조 실패") from exc
        cache = {
            training_id: summary
            for training_id, summary in snapshot.training_cache.items()
            if (training_id, str(summary.get("starts_at"))) in pairs
        }
        if len(cache) != len(snapshot.training_cache):
            logger.info(
                "대화 사본 재대조로 제외 run_id=%s count=%d",
                run.context.run_id,
                len(snapshot.training_cache) - len(cache),
            )
        return replace(
            snapshot,
            training_cache=cache,
            last_training_ids=tuple(i for i in snapshot.last_training_ids if i in cache),
            selected_training_id=snapshot.selected_training_id
            if snapshot.selected_training_id in cache
            else None,
        )

    def _remaining(self, context: ExecutionContext) -> float:
        return context.deadline_monotonic - self._clock.monotonic()

    async def _loop(self, run: _Run, message: str) -> ExecutionResult:
        policy = run.context.policy
        run.message = message
        history = _visible_history(run)
        # 이력의 사용자 메시지도 서버 표시 문자열을 무력화한다(현재 턴과 같은 규칙).
        messages = [
            ModelMessage(role=m.role, text=neutralize(m.text) if m.role == "user" else m.text)
            for m in history
        ]
        snapshot = run.snapshot
        data = conversation_data(
            snapshot.training_cache, snapshot.last_training_ids, snapshot.selected_training_id
        )
        messages.append(ModelMessage(role="user", text=user_turn(message, data)))
        tools = self._tools.describe_allowed_tools(run.context)
        names = {tool.name for tool in tools}
        system = system_prompt(
            run.context.current_time,
            documents="search_documents" in names,
            tickets=bool(names & {"prepare_it_ticket", "list_it_tickets"}),
        )

        tool_choice = "auto"
        while True:
            response = await self._call_model(run, tuple(messages), tools, system, tool_choice)
            tool_choice = "auto"
            if not response.wants_tools and _empty_first_answer(run, response, tools):
                # D-37(P-16 B): 아무 도구도 부르지 않은 첫 응답의 빈 답만 한 번 다시 부른다
                # (모델 시도 상한 안). D-41: 다시 부를 때는 도구 호출을 강제한다.
                run.empty_answer_retries += 1
                logger.info("빈 첫 답 재호출 run_id=%s", run.context.run_id)
                messages.append(response.as_assistant_message())
                messages.append(ModelMessage(role="user", text=EMPTY_ANSWER_RETRY))
                tool_choice = "any"  # D-41: 다시 부를 때는 도구 호출을 강제한다(P-16 C의 일부)
                continue
            if not response.wants_tools:
                return await self._finish(run, response)
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
                view = (
                    _search_view(run, result) if proposal.name == "search_documents" and result.ok else result
                )
                results.append(
                    ToolResultContent(proposal.provider_call_id, _model_view(view), is_error=not result.ok)
                )
            messages.append(response.as_assistant_message())
            messages.append(ModelMessage(role="tool_result", tool_results=tuple(results)))

    async def _call_model(
        self, run: _Run, messages: tuple[ModelMessage, ...], tools, system: str, tool_choice: str = "auto"
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
            await _stage(run, ProgressStage.MODEL_WAITING)
            request = ModelRequest(
                purpose="agent_answer",
                messages=messages,
                tools=tools,
                output_contract=FINAL_OUTPUT_SCHEMA,
                timeout_s=timeout,
                model_config=self._model,
                system=system,
                tool_choice=tool_choice if tools else "auto",
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
        stage = _TOOL_STAGES.get(proposal.name)
        if stage is not None:
            await _stage(run, stage)
        while True:
            attempt += 1
            started = self._clock.monotonic()
            result = await self._tools.execute_once(
                run.context,
                ToolExecutionInput(
                    proposal=proposal,
                    call_ordinal=ordinal,
                    observer=run.observer,
                    field_origins=_field_origins(run, proposal),
                ),
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
                retrieval_trace=result.trace,
            )
            try:
                await run.observer.record_tool_call(record)
            except RequiredRecordError:
                raise
            except Exception as exc:
                raise RequiredRecordError("도구 호출 기록 저장 실패") from exc
            run.records.append(record)

            if result.ok and proposal.name in ("list_it_tickets", "get_it_ticket"):
                items = result.data.get("items") if proposal.name == "list_it_tickets" else [result.data]
                for ticket in items or []:
                    run.ticket_refs[ticket["id"]] = {
                        "id": ticket["id"],
                        "subject": ticket["subject"],
                        "status": ticket["status"],
                    }
            if result.ok and proposal.name == "prepare_it_ticket":
                run.prepared[result.data["action_id"]] = dict(result.data)
            if result.ok:
                # 교육 원장은 교육 도구 결과로만 채운다(티켓·문서 결과의 id를 교육으로 보지 않는다).
                for summary in (
                    _summaries(result) if proposal.name in ("list_trainings", "get_training") else []
                ):
                    run.ledger.pop(summary["id"], None)  # 다시 조회한 교육은 가장 최근 위치로 옮긴다
                    run.ledger[summary["id"]] = summary
                if proposal.name in ("list_trainings", "list_it_tickets"):
                    # 0건 답(no_results)의 근거가 되는 목록 조회(교육·티켓).
                    run.successful_list_lookups += 1
                return result
            assert result.error is not None  # noqa: S101 - ToolResult 계약
            if result.error.retryable and attempt <= policy.max_retries_per_call:
                continue
            if result.error.code in _INFRA_TOOL_ERRORS:
                raise result.error
            return result

    async def _finish(self, run: _Run, response: ModelResponse) -> ExecutionResult:
        if response.final_candidate is None:
            raise _output_invalid(run, "final candidate missing")
        await _stage(run, ProgressStage.VERIFYING)
        candidate, answer_source = _fill_empty_clarification(run, response.final_candidate)
        try:
            final = FinalCandidate.model_validate(candidate)
        except ValidationError as exc:
            problems = sorted({f"{'.'.join(map(str, e['loc']))}:{e['type']}" for e in exc.errors()})
            raise _output_invalid(run, f"schema {problems}") from exc
        if final.action_id is not None and final.action_id not in run.prepared:
            # 이번 실행에서 준비하지 않은 action을 가리키면 지어낸 것으로 본다.
            raise _output_invalid(run, "action id not prepared in this run")
        if final.outcome is Outcome.ACTION_PENDING and final.action_id is None:
            raise _output_invalid(run, "action_pending without action id")
        unknown_tickets = [t for t in final.ticket_ids if t not in run.ticket_refs]
        if unknown_tickets:
            raise _output_invalid(run, f"{len(unknown_tickets)} ticket id(s) not in ledger")
        allowed = run.allowed_trainings()
        training_ids = list(dict.fromkeys(final.training_ids))
        selected = final.selected_training_id
        if final.outcome is Outcome.NO_RESULTS:
            # 0건 답은 이번 실행에서 실제로 목록을 조회했을 때만 인정한다(조회 실패·미조회는 0건이 아니다).
            if run.successful_list_lookups == 0:
                raise _output_invalid(run, "no_results without successful list lookup")
            if training_ids:
                raise _output_invalid(run, "no_results with training ids")
        citation_ids = list(dict.fromkeys(final.citation_ids))
        unknown_citations = [c for c in citation_ids if c not in run.citations]
        if unknown_citations:
            # 이번 실행 문맥에 없던 인용 ID는 지어낸 것으로 보고 실패시킨다(T-07).
            raise _output_invalid(run, f"{len(unknown_citations)} citation id(s) not in ledger")
        if final.outcome in (Outcome.NEEDS_CLARIFICATION, Outcome.NO_RESULTS):
            citation_ids = []
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
        outcome, answer = final.outcome, final.answer
        mapped = _server_outcome(run, final, citation_ids, training_ids)
        if mapped is not None:
            logger.info("결론 서버 매핑 run_id=%s %s->%s", run.context.run_id, outcome.value, mapped[0].value)
            (outcome, answer), answer_source = mapped, "server_mapping"

        return ExecutionResult(
            status="completed",
            outcome=outcome,
            answer=answer,
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
            citations=tuple(_citation_dto(run.citations[c]) for c in citation_ids),
            document_keys=tuple(sorted({c["document_key"] for c in run.citations.values()})),
            ticket_refs=tuple(run.ticket_refs[t] for t in dict.fromkeys(final.ticket_ids)),
            # 모델이 action_id로 가리킨 이번 실행의 draft만 채택한다(MOD-01이 저장하면 UI에 공개).
            action_preview=run.prepared.get(final.action_id) if final.action_id else None,
            ticket_dependency_ids=tuple(sorted(run.ticket_refs)),
            evidence_trace=run.evidence_trace(),
        )


def _visible_history(run: _Run) -> tuple:
    """모델에 보내는 이력 창. 사건 날짜 인용도 모델이 본 메시지 안에서만 찾는다."""
    limit = run.context.policy.history_messages
    return tuple(run.snapshot.messages[-limit:]) if limit else ()


def _field_origins(run: _Run, proposal: ToolCallProposal) -> dict[str, Any] | None:
    """search_documents의 사건 날짜를 사용자 메시지 인용으로 검증한 정규 값(CT-06 field_origins).

    모델 인자의 as_of_date·date_quote는 후보일 뿐이다. 서버가 인용을 본인 메시지와 대조하고 날짜를 정규화한다.
    경과조항 조건용 other_events(D-40)도 사건마다 같은 규칙으로 검증한다(키 other_events[i]).
    """
    if proposal.name == "prepare_it_ticket":
        return {"ticket_fields": _ticket_origins(run, proposal)}
    if proposal.name != "search_documents":
        return None
    arguments = proposal.arguments if isinstance(proposal.arguments, dict) else {}
    origins: dict[str, Any] = {}
    if arguments.get("date_basis", "current") != "current":
        origins["as_of_date"] = _verify_event(run, arguments)
    others = arguments.get("other_events")
    for index, event in enumerate(others if isinstance(others, list) else []):
        if isinstance(event, dict):
            origins[f"other_events[{index}]"] = _verify_event(run, event)
    return origins or None


def _ticket_origins(run: _Run, proposal: ToolCallProposal) -> list[dict[str, Any]]:
    """prepare_it_ticket의 origin_candidates → 정규 field_origins(04-field-origins).

    quote는 이번 run 문맥의 본인 user 메시지(수락한 질문 먼저, 그다음 모델에 보낸 이력 창)에서 정확히 한 번
    있어야 하고, 서버가 code point 구간을 계산한다. 모델의 message_id·구간은 받지 않는다. 찾지 못한 후보는
    버린다(MOD-12가 출처 없는 필드로 거절한다). 템플릿은 서버 registry의 ID만 넘긴다.
    """
    arguments = proposal.arguments if isinstance(proposal.arguments, dict) else {}
    candidates = arguments.get("origin_candidates")
    sources: list[tuple[str, str]] = []
    if run.context.user_message_id:
        sources.append((run.context.user_message_id, run.message))
    sources.extend(
        (m.message_id, m.text) for m in reversed(_visible_history(run)) if m.role == "user" and m.message_id
    )
    out: list[dict[str, Any]] = []
    for candidate in candidates if isinstance(candidates, list) else []:
        if not isinstance(candidate, dict) or not isinstance(candidate.get("field"), str):
            continue
        name = candidate["field"]
        if candidate.get("template_id"):
            out.append({"field": name, "kind": "template", "template_id": str(candidate["template_id"])})
            continue
        quote = candidate.get("quote")
        if not isinstance(quote, str) or not quote:
            continue
        hits = [(mid, text, at) for mid, text in sources if (at := locate(text, quote)) is not None]
        current = [h for h in hits if h[0] == run.context.user_message_id]
        chosen = current[0] if current else (hits[0] if len(hits) == 1 else None)
        if chosen is None:
            continue
        mid, _, start = chosen
        end = start + len(quote)
        value = arguments.get(name)
        if name in FREE_TEXT_FIELDS and isinstance(value, str) and value and value != quote.strip():
            # 값이 인용 구간 안에 정확히 한 번 있으면 그 부분으로 구간을 좁힌다(여전히 사용자 원문 그대로).
            inner = locate(quote, value)
            if inner is not None:
                start, end = start + inner, start + inner + len(value)
                quote = value
        out.append(
            {
                "field": name,
                "kind": "user_quote",
                "source_message_id": mid,
                "span_start": start,
                "span_end": end,
                "normalization": _normalization_for(name, value, quote),
            }
        )
    return out


def _normalization_for(name: str, value: Any, quote: str) -> str:
    if name == "occurred_at":
        return "iso_kst_datetime"
    if name in ("category", "request_type"):
        return "canonical_category"
    if name == "urgent_work":
        return "user_boolean"
    return "identity" if value == quote else "trim"


def _verify_event(run: _Run, arguments: dict[str, Any]) -> dict[str, Any]:
    raw_date = arguments.get("as_of_date")
    try:
        model_date = date.fromisoformat(raw_date) if isinstance(raw_date, str) else None
    except ValueError:
        model_date = None
    quote = arguments.get("date_quote")
    origin = verify_event_date(
        quote if isinstance(quote, str) else None,
        model_date,
        run.message,
        tuple(m.text for m in _visible_history(run) if m.role == "user"),
        run.context.current_time.astimezone(KST).date(),
        date_basis=arguments.get("date_basis"),
    )
    if not origin.verified:
        logger.info(
            "사건 날짜 근원 확인 실패 run_id=%s problem=%s",
            run.context.run_id,
            origin.evidence.get("problem"),
        )
    return origin.as_field_origin()


def _search_view(run: _Run, result: ToolResult) -> ToolResult:
    """검색 결과를 근거 예산에 맞춰 support_group 단위로 채택하고, 채택한 passage만 원장에 올린다.

    - 그룹은 MOD-11이 정한 순서(대표 후보의 거리 순)대로 앞에서부터 넣는다. 그룹 하나를 끊어 넣지 않는다.
    - 실행 전체에서 final_context_token_limit(초기 4000)을 넘기지 않는다. 처음으로 들어가지 않는 그룹에서
      멈춘다. 예산 밖 후보를 순서를 바꿔 다시 넣지 않는다(05-retrieval-assembly 7항).
    - 대표 그룹(첫 그룹)이 들어가지 않으면 그 검색의 필수 근거가 빠진 것이다(6항).
      표시하고 기권 대상으로 남긴다.
    - 같은 실행에서 이미 문맥에 넣은 그룹은 비용을 다시 세지 않고 처음 받은 citation_id를 그대로 쓴다.
    - 모델에는 인용에 필요한 출처 값과 원문만 보낸다.
    """
    data = dict(result.data or {})
    run.search_results.append(
        {
            "resolution": data.get("resolution"),
            "clarification": data.get("clarification"),
            "unsupported": data.get("unsupported"),
            "normative_gap": data.get("normative_gap"),
            "event_key": data.get("event_key"),
            "date_basis": data.get("date_basis"),
            "transition_pending": data.get("transition_pending"),
        }
    )
    limit = run.context.policy.final_context_token_limit
    groups = data.get("groups", [])
    kept_groups: list[dict[str, Any]] = []
    dropped_ids: list[str] = []
    context_key = (data.get("event_key"), data.get("date_basis"), data.get("as_of_date"))
    if data.get("normative_gap"):
        run.normative_gap_contexts.add(context_key)
    for index, group in enumerate(groups):
        group_id = group.get("group_id")
        passages = group.get("passages", [])
        key = (group_id, *context_key)
        if key in run.seen_groups:
            ids = run.seen_groups[key]
            kept_groups.append(
                {
                    "group_id": group_id,
                    "passages": [
                        {**{k: p.get(k) for k in _PASSAGE_VIEW_KEYS}, "citation_id": cid}
                        for p, cid in zip(passages, ids, strict=False)
                    ],
                }
            )
            continue
        cost = sum(int(p.get("token_estimate", 0)) for p in passages)
        if run.evidence_tokens + cost > limit:
            dropped_ids = [
                g.get("group_id")
                for g in groups[index:]
                if (g.get("group_id"), *context_key) not in run.seen_groups
            ]
            if index == 0:
                run.required_group_missing = True
                first = passages[0]["citation_id"] if passages else ""
                run.missing_required_calls.add(first.split("-", 1)[0])
            break
        run.evidence_tokens += cost
        for passage in passages:
            run.citations[passage["citation_id"]] = {
                **passage,
                "as_of_date": data.get("as_of_date"),
                "date_basis": data.get("date_basis"),
                "event_key": data.get("event_key"),
                "prospective": data.get("prospective"),
                "date_evidence": data.get("date_evidence") or {},
                "knowledge_as_of": run.context.current_time.isoformat(),
            }
        run.seen_groups[key] = [p["citation_id"] for p in passages]
        kept_groups.append(
            {
                "group_id": group_id,
                "passages": [{k: p.get(k) for k in _PASSAGE_VIEW_KEYS} for p in passages],
            }
        )
    if dropped_ids:
        run.dropped_group_ids.extend(dropped_ids)
        logger.info(
            "근거 예산 초과로 제외 run_id=%s groups=%s evidence_budget_exceeded=true",
            run.context.run_id,
            dropped_ids,
        )
    view = {
        **{k: data.get(k) for k in ("resolution", "date_basis", "as_of_date", "event_key", "prospective")},
        "year_inferred": bool((data.get("date_evidence") or {}).get("year_inferred")),
        "clarification": data.get("clarification"),
        "unsupported": data.get("unsupported"),
        "normative_gap": data.get("normative_gap"),
        "authority_relations": data.get("authority_relations") or [],
        "transition_pending": data.get("transition_pending"),
        "groups": kept_groups,
    }
    if dropped_ids:
        view["evidence_budget_exceeded"] = True
    return ToolResult.success(view, result.resource_ids)


def _server_outcome(run: _Run, final: FinalCandidate, citation_ids: list[str], training_ids: list[str]):
    """검색 결과에 맞지 않는 결론을 서버가 바로잡는다(CT-14 → CT-10 매핑). 바꿀 것이 없으면 None.

    - 규범 공백 사건을 안내로 결론 냈으면(answered·insufficient_evidence의 모델 문장) 서버 문구로 보류한다.
    아래는 근거(인용·교육) 없이 answered로 끝냈을 때만 본다.
    - 이번 실행의 검색이 모두 needs_clarification/unsupported였다면: 되묻기가 있으면 되묻기, 아니면 근거 부족.
    - 대표 근거 그룹이 예산 때문에 빠졌다면: 근거 부족(불완전한 조건으로 단정하지 않음).
    답 문장은 서버 문구로 바꾼다(모델이 근거 없이 쓴 금액·조건을 내보내지 않게).
    """
    gap_message = _normative_gap_withhold(run, citation_ids)
    if gap_message is not None and final.outcome in (Outcome.ANSWERED, Outcome.INSUFFICIENT_EVIDENCE):
        logger.info(
            "규범 공백으로 결론 보류 run_id=%s reason=normative_gap contexts=%d",
            run.context.run_id,
            len(run.normative_gap_contexts),
        )
        return Outcome.INSUFFICIENT_EVIDENCE, _with_pending(run, gap_message)
    if final.outcome is not Outcome.ANSWERED or not run.search_results:
        return None
    # 대표 근거가 예산 때문에 빠진 검색이 있는데 그 검색의 원문을 하나도 인용하지 않았다면, 다른 근거를
    # 인용했더라도 그 사건의 결론을 낼 수 없다(05-retrieval-assembly 6항).
    cited_calls = {c.split("-", 1)[0] for c in citation_ids}
    if run.missing_required_calls - cited_calls:
        return Outcome.INSUFFICIENT_EVIDENCE, _with_pending(run, _BUDGET_ABSTAIN)
    if citation_ids or training_ids:
        # D-39(P-18 B): 확인된 사건은 답하고, 날짜를 확인하지 못한 사건의 되묻기 문구를 서버가 덧붙인다.
        pending = [p for p in _pending_clarifications(run) if p not in final.answer]
        if pending:
            return Outcome.ANSWERED, "\n\n".join([final.answer, *pending])
        return None
    resolutions = [r["resolution"] for r in run.search_results]
    if all(r != "resolved" for r in resolutions):
        clarification = next((r["clarification"] for r in run.search_results if r["clarification"]), None)
        if clarification is not None:
            return Outcome.NEEDS_CLARIFICATION, clarification["prompt"]
        unsupported = next((r["unsupported"] for r in run.search_results if r["unsupported"]), None)
        return Outcome.INSUFFICIENT_EVIDENCE, (unsupported or {}).get("safe_message") or _BUDGET_ABSTAIN


def _normative_gap_withhold(run: _Run, citation_ids: list[str]) -> str | None:
    """규범 공백 사건의 결론을 보류할지(05-retrieval-assembly). 보류하면 서버 문구, 아니면 None.

    공백 사건 문맥의 원문을 인용했는데 그중 그날 유효한 규범이 없으면(안내로 결론), 또는 공백 사건 말고는
    인용이 없으면 보류한다. 같은 사건을 다른 질의로 검색해 받은 인용(재사용 ID 포함)도 사건 문맥으로 본다.
    """
    if not run.normative_gap_contexts:
        return None
    cited = [run.citations[c] for c in citation_ids]
    in_gap = [p for p in cited if _citation_context(p) in run.normative_gap_contexts]
    if any(p.get("document_role") == "normative" for p in in_gap):
        return None
    if in_gap or not cited:
        return next(r["normative_gap"]["safe_message"] for r in run.search_results if r.get("normative_gap"))
    return None


def _pending_clarifications(run: _Run) -> list[str]:
    """끝내 날짜를 확인하지 못한 사건의 되묻기 문구(중복 없이).

    사건은 (event_key, date_basis)로 구분한다. event_key를 비우거나 같은 key로 current 검색을 해도 그 사건의
    날짜가 확인된 것으로 보지 않는다. 경과조항 조건에 빠진 사건 날짜(transition_pending)도 포함한다.
    """
    resolved = {
        (r.get("event_key"), r.get("date_basis")) for r in run.search_results if r["resolution"] == "resolved"
    }
    prompts: list[str] = []
    for r in run.search_results:
        clarification = r.get("clarification")
        unresolved = (r.get("event_key"), r.get("date_basis")) not in resolved
        for item in (
            clarification if r["resolution"] == "needs_clarification" and unresolved else None,
            r.get("transition_pending"),
        ):
            if item and item["prompt"] not in prompts:
                prompts.append(item["prompt"])
    return prompts


def _with_pending(run: _Run, text: str) -> str:
    pending = [p for p in _pending_clarifications(run) if p not in text]
    return "\n\n".join([text, *pending])


def _citation_context(passage: dict[str, Any]) -> tuple:
    return (passage.get("event_key"), passage.get("date_basis"), passage.get("as_of_date"))


_BUDGET_ABSTAIN = (
    "필요한 규정 원문을 모두 확인하지 못해 결론을 드릴 수 없습니다. 질문을 나눠 다시 물어 주세요."
)


def _citation_dto(passage: dict[str, Any]) -> dict[str, Any]:
    """인용 DTO(04-api-spec). 제목·페이지·URL은 서버 값으로만 만든다."""
    spans = passage.get("page_spans") or []
    first_page = spans[0]["page"] if spans else 1
    text = passage.get("text") or ""
    return {
        "citation_id": passage["citation_id"],
        "passage_id": passage["passage_id"],
        "document_key": passage["document_key"],
        "source_file_id": passage["source_file_id"],
        "version": passage["version"],
        "title": passage["title"],
        "document_role": passage["document_role"],
        "available_from": passage.get("available_from"),
        "knowledge_as_of": passage.get("knowledge_as_of"),
        "prospective": bool(passage.get("prospective")),
        "effective_from": passage.get("effective_from"),
        "effective_to": passage.get("effective_to"),
        "edition_state": passage.get("edition_state"),
        "as_of_date": passage.get("as_of_date"),
        "date_basis": passage.get("date_basis"),
        "event_key": passage.get("event_key"),
        "source_role": passage.get("source_role") or "base",
        "year_inferred": bool((passage.get("date_evidence") or {}).get("year_inferred")),
        "page_spans": spans,
        "quote": text if len(text) <= 300 else text[:300] + "…",
        "evidence_url": f"/api/v1/evidence/{passage['passage_id']}",
        "pdf_url": f"/api/v1/source-files/{passage['source_file_id']}/pdf#page={first_page}",
    }
