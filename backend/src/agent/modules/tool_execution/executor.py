"""DescribeAllowedTools / ExecuteOnce(MOD-03).

- 등록된 이름만 실행하고 정의되지 않은 인자 필드는 거절한다(user_id·admin·approved 위조 포함).
- 한 번만 시도한다. 재시도 판단은 MOD-02가 한다.
- 교육 결과는 모델에 넘기기 전에 observer로 receipt를 남긴다(CT-11). 그 기록이 실패하면 RequiredRecordError.
"""

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy.exc import SQLAlchemyError

from agent.modules.training.models import TrainingPage, TrainingSearchInput
from agent.modules.training.service import TrainingService
from agent.shared.clock import Clock
from agent.shared.contracts import (
    ExecutionContext,
    RequiredRecordError,
    ToolExecutionInput,
    ToolResult,
    ToolSpec,
    TrainingResultReceipt,
)
from agent.shared.errors import AppError, ErrorCode


class GetTrainingArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    training_id: UUID


@dataclass(frozen=True)
class _Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    capability: str


# 첫 구간에 허용된 도구는 교육 두 개뿐이다(docs/12-first-milestone-spec.md).
_TOOLS: dict[str, _Tool] = {
    "list_trainings": _Tool(
        name="list_trainings",
        description=(
            "사내 교육 일정 목록을 조회한다. 기간은 date_preset(today, this_week, next_week, next_30_days, "
            "custom)으로 고르고, custom일 때만 start_date와 end_date_exclusive(YYYY-MM-DD, 종료일 미포함, "
            "최대 90일)를 함께 넣는다. 주는 월요일에 시작한다. query는 교육 제목의 일부(최대 100자)다. "
            "기본 목록은 예정(scheduled) 교육만 돌려준다. 결과의 장소·시간을 그대로 쓴다."
        ),
        args_model=TrainingSearchInput,
        capability="training.read",
    ),
    "get_training": _Tool(
        name="get_training",
        description=(
            "교육 한 건의 상세(설명 포함)를 training_id(UUID)로 조회한다. training_id는 이전 조회 결과에 "
            "있던 값만 쓴다. 취소·완료된 교육도 실제 상태를 돌려준다."
        ),
        args_model=GetTrainingArgs,
        capability="training.read",
    ),
}


def _field_names(exc: ValidationError) -> list[str]:
    return sorted({str(err["loc"][0]) for err in exc.errors() if err.get("loc")})


def _receipt(context: ExecutionContext, ordinal: int, items: list[Any]) -> TrainingResultReceipt:
    starts = tuple((str(item.id), item.starts_at.isoformat()) for item in items)
    canonical = json.dumps(
        [item.model_dump(mode="json") for item in items], ensure_ascii=False, sort_keys=True
    )
    return TrainingResultReceipt(
        run_id=context.run_id,
        ordinal=ordinal,
        training_starts=starts,
        result_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )


def _input_schema(tool: _Tool) -> dict[str, Any]:
    # 인자 모델의 docstring은 개발용 설명이라 모델에 보내지 않는다. 도구 설명은 description에 따로 둔다.
    schema = tool.args_model.model_json_schema()
    schema.pop("description", None)
    return schema


class ToolExecutor:
    def __init__(self, trainings: TrainingService, clock: Clock) -> None:
        self._trainings = trainings
        self._clock = clock

    def describe_allowed_tools(self, context: ExecutionContext) -> tuple[ToolSpec, ...]:
        """actor capability로 명세를 제한한다. 실행할 때도 다시 확인한다."""
        return tuple(
            ToolSpec(name=tool.name, description=tool.description, input_schema=_input_schema(tool))
            for tool in _TOOLS.values()
            if tool.capability in context.actor.capabilities
        )

    async def execute_once(self, context: ExecutionContext, call: ToolExecutionInput) -> ToolResult:
        tool = _TOOLS.get(call.proposal.name)
        if tool is None or tool.capability not in context.actor.capabilities:
            # 허용되지 않은 도구는 존재 여부를 따로 알리지 않고 미등록으로 다룬다.
            return ToolResult.failure(AppError(ErrorCode.TOOL_NOT_REGISTERED))
        try:
            args = tool.args_model.model_validate(call.proposal.arguments)
        except ValidationError as exc:
            return ToolResult.failure(
                AppError(ErrorCode.TOOL_ARGUMENT_INVALID, details={"field_names": _field_names(exc)})
            )

        remaining = context.deadline_monotonic - self._clock.monotonic()
        timeout = min(context.policy.tool_timeout_s, remaining)
        if timeout <= 0:
            return ToolResult.failure(AppError(ErrorCode.TOOL_TIMEOUT))
        handler = self._list if tool.name == "list_trainings" else self._get
        try:
            async with asyncio.timeout(timeout):
                return await handler(context, call, args)
        except TimeoutError:
            return ToolResult.failure(AppError(ErrorCode.TOOL_TIMEOUT, retryable=True))
        except AppError as exc:
            if exc.code is ErrorCode.INVALID_REQUEST:
                # MOD-04의 날짜 범위 검증 실패는 도구 인자 오류로 돌려준다(필드 이름만 유지).
                return ToolResult.failure(AppError(ErrorCode.TOOL_ARGUMENT_INVALID, details=exc.details))
            return ToolResult.failure(exc)
        except (SQLAlchemyError, OSError):
            return ToolResult.failure(AppError(ErrorCode.TOOL_EXECUTION_FAILED, retryable=True))

    async def _list(self, context: ExecutionContext, call: ToolExecutionInput, args: Any) -> ToolResult:
        page: TrainingPage = await self._trainings.list_trainings(args, context.current_time)
        await self._record(context, call, page.items)
        return ToolResult.success(page.model_dump(mode="json"), tuple(str(i.id) for i in page.items))

    async def _get(self, context: ExecutionContext, call: ToolExecutionInput, args: Any) -> ToolResult:
        detail = await self._trainings.get_training(args.training_id)
        await self._record(context, call, [detail])
        return ToolResult.success(detail.model_dump(mode="json"), (str(detail.id),))

    async def _record(self, context: ExecutionContext, call: ToolExecutionInput, items: list[Any]) -> None:
        try:
            await call.observer.record_training_result(_receipt(context, call.call_ordinal, items))
        except RequiredRecordError:
            raise
        except Exception as exc:
            raise RequiredRecordError("교육 결과 receipt 저장 실패") from exc
