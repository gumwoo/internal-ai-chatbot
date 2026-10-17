"""MOD-01 공개 작업: Create/List/GetConversation, AcceptMessage+RunConversation, Finalize/Fail/Expire,
ListMessages, GetRun, RecoverExpiredRuns(docs/contracts/01-run-lifecycle.md).

핵심 규칙
- 수락: 대화 행을 잠근 한 트랜잭션에서 만료 회수 → receipt 확인 → 활성 run 확인 → 메시지·run·receipt·활성
  소유권을 함께 저장한다. 모델·도구 호출 중에는 DB 잠금을 잡지 않는다.
- 완료: run ID·running·deadline을 조건으로 한 번만 종료한다. 늦게 온 결과는 덮어쓰지 못한다.
  활성 소유권은 자기 run일 때만 해제한다(이전 run의 해제가 새 run을 지우지 않게).
- 응답: 최초 응답과 재전송 응답을 같은 함수(_respond)가 저장된 상태에서 만든다.
"""

import asyncio
import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from agent.modules.agent_runtime.contracts import (
    ConversationSnapshot,
    ExecutionResult,
    HistoryMessage,
)
from agent.modules.agent_runtime.runtime import AgentRuntime
from agent.modules.conversation.records import DbExecutionObserver, verified_cache, verified_training_pairs
from agent.modules.conversation.tables import (
    agent_runs,
    conversations,
    message_receipts,
    messages,
    tool_calls,
)
from agent.shared.actor import ActorContext
from agent.shared.clock import KST, Clock
from agent.shared.contracts import ExecutionContext, ExecutionPolicy, RetrievalContext
from agent.shared.errors import AppError, ErrorCode

logger = logging.getLogger(__name__)

RETRIEVAL_STRATEGY = "disabled"  # M1~M2: 문서 미게시 구간(knowledge_enabled=false)
_REDACTED_TEXT = "이 답변은 현재 권한으로 볼 수 없어 가렸습니다."
# 동시 수락 경쟁에서만 나는 제약 위반: 대화당 running 하나, 같은 키 receipt 하나.
_BUSY_CONSTRAINTS = frozenset({"ux_agent_runs_one_running", "message_receipts_pkey"})


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MessageResponse:
    """POST messages 결과. status_code 200(완료) 또는 202(실행 중). 실패·만료는 AppError로 던진다."""

    status_code: int
    body: dict[str, Any]


@dataclass(frozen=True)
class _Accepted:
    run_id: UUID
    user_message_id: UUID
    accepted_at: datetime
    deadline_monotonic: float


def _iso(value: datetime | None) -> str | None:
    """응답 시각은 모두 KST 오프셋으로 낸다. DB에서 읽은 값은 세션 시간대(UTC)라 바꿔야 한다."""
    return value.astimezone(KST).isoformat() if value else None


def _can_view_trainings(actor: ActorContext) -> bool:
    """CP-05 ResourceVisibility의 M2 형태. 교육 fixture는 training.read가 있는 직원에게 공개다.

    M3에서 문서, M5에서 티켓 자원의 현재 권한 검사를 같은 자리에 붙인다.
    """
    return "training.read" in actor.capabilities


def _can_view(actor: ActorContext, message: Any) -> bool:
    """답변을 지금 보여 줘도 되는가. 답에 적힌 참조가 아니라 모델 문맥에 들어간 의존 자원 전체로 판정한다.

    모델이 인용을 생략해도 접근 검사를 피하지 못하게 하려는 것이다(CT-03).
    """
    if message.visibility != "visible":
        return False
    return not message.dependency_ids or _can_view_trainings(actor)


class ConversationService:
    def __init__(
        self,
        engine: AsyncEngine,
        clock: Clock,
        runtime: AgentRuntime,
        *,
        model_name: str,
        prompt_version: str,
        policy: ExecutionPolicy | None = None,
    ) -> None:
        self._engine = engine
        self._clock = clock
        self._runtime = runtime
        self._model_name = model_name
        self._prompt_version = prompt_version
        self._policy = policy or ExecutionPolicy()
        self._tasks: set[asyncio.Task] = set()

    # --- 대화 ---

    async def create_conversation(self, actor: ActorContext, title: str | None) -> dict[str, Any]:
        now = self._clock.now()
        row = {
            "id": uuid.uuid4(),
            "owner_user_id": actor.user_id,
            "title": title,
            "retrieval_strategy": RETRIEVAL_STRATEGY,
            "active_run_id": None,
            "business_state": {},
            "created_at": now,
            "updated_at": now,
        }
        async with self._write() as conn:
            await conn.execute(conversations.insert().values(row))
        return {"id": str(row["id"]), "title": title, "created_at": _iso(now)}

    async def list_conversations(self, actor: ActorContext, limit: int, offset: int) -> dict[str, Any]:
        # 목록의 active_run_id가 이미 만료된 run을 가리키지 않도록 먼저 회수한다.
        await self.recover_expired()
        owned = conversations.c.owner_user_id == actor.user_id
        async with self._read() as conn:
            total = await conn.scalar(select(func.count()).select_from(conversations).where(owned))
            rows = (
                await conn.execute(
                    select(conversations)
                    .where(owned)
                    .order_by(conversations.c.created_at.desc(), conversations.c.id)
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
        items = [
            {
                "id": str(r.id),
                "title": r.title,
                "created_at": _iso(r.created_at),
                "active_run_id": str(r.active_run_id) if r.active_run_id else None,
            }
            for r in rows
        ]
        total = int(total or 0)
        return {
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(items) < total,
        }

    async def get_conversation(self, actor: ActorContext, conversation_id: UUID) -> dict[str, Any]:
        await self.recover_expired(conversation_id=conversation_id)
        async with self._read() as conn:
            row = await self._owned(conn, actor, conversation_id)
        return {
            "id": str(row.id),
            "title": row.title,
            "created_at": _iso(row.created_at),
            "active_run_id": str(row.active_run_id) if row.active_run_id else None,
        }

    async def list_messages(
        self, actor: ActorContext, conversation_id: UUID, limit: int, offset: int
    ) -> dict[str, Any]:
        async with self._read() as conn:
            await self._owned(conn, actor, conversation_id)
            where = messages.c.conversation_id == conversation_id
            total = await conn.scalar(select(func.count()).select_from(messages).where(where))
            rows = (
                await conn.execute(
                    select(messages).where(where).order_by(messages.c.seq).limit(limit).offset(offset)
                )
            ).all()
        items = []
        for r in rows:
            visible = r.role == "user" or _can_view(actor, r)
            items.append(
                {
                    "id": str(r.id),
                    "role": r.role,
                    "visibility": "visible" if visible else "redacted",
                    # 가린 답변은 원래 본문·참조를 넣지 않고 일반 안내만 둔다.
                    "content": r.content if visible else _REDACTED_TEXT,
                    "outcome": r.outcome if visible else None,
                    "training_refs": r.training_refs if visible else [],
                    "run_id": str(r.run_id) if r.run_id else None,
                    "created_at": _iso(r.created_at),
                }
            )
        total = int(total or 0)
        return {
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(items) < total,
        }

    async def get_run(self, actor: ActorContext, run_id: UUID) -> dict[str, Any]:
        await self.recover_expired(run_id=run_id)
        async with self._read() as conn:
            run = (await conn.execute(select(agent_runs).where(agent_runs.c.id == run_id))).first()
            owner = None
            if run is not None:
                owner = await conn.scalar(
                    select(conversations.c.owner_user_id).where(conversations.c.id == run.conversation_id)
                )
            if run is None or owner != actor.user_id:
                raise AppError(ErrorCode.RUN_NOT_FOUND)
            calls = (
                await conn.execute(
                    select(tool_calls)
                    .where(tool_calls.c.run_id == run_id)
                    .order_by(tool_calls.c.ordinal, tool_calls.c.attempt)
                )
            ).all()
        return {
            "run_id": str(run.id),
            "conversation_id": str(run.conversation_id),
            "status": run.status,
            "outcome": run.outcome,
            "error_code": run.error_code,
            "accepted_at": _iso(run.accepted_at),
            "deadline_at": _iso(run.deadline_at),
            "finished_at": _iso(run.finished_at),
            "usage": run.usage,
            # 도구 안전 요약: 인자 값·결과 본문·내부 원인은 넣지 않는다.
            "tools": [
                {
                    "ordinal": c.ordinal,
                    "name": c.name,
                    "attempt": c.attempt,
                    "ok": c.ok,
                    "error_code": c.error_code,
                }
                for c in calls
            ],
        }

    # --- 메시지 수락·실행 ---

    async def post_message(
        self, actor: ActorContext, conversation_id: UUID, content: str, idempotency_key: UUID, request_id: str
    ) -> MessageResponse:
        accepted = await self._accept(actor, conversation_id, content, idempotency_key, request_id)
        if not isinstance(accepted, _Accepted):
            return await self._respond(actor, accepted)
        # 실행은 별도 task로 돌린다. HTTP 연결이 끊기거나 요청이 취소돼도 실행·완료 commit은 계속된다.
        task = asyncio.create_task(self._execute(actor, conversation_id, content, accepted, request_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        finished = await asyncio.shield(task)
        if not finished:
            # 최종 commit 실패: 성공도 "실행 중"도 아니다. run은 deadline 뒤 회수된다(T-03).
            raise AppError(ErrorCode.PERSISTENCE_FAILED, retryable=True, run_id=str(accepted.run_id))
        return await self._respond(actor, accepted.run_id)

    async def _accept(
        self, actor: ActorContext, conversation_id: UUID, content: str, key: UUID, request_id: str
    ) -> _Accepted | UUID:
        """새 실행을 수락하면 _Accepted, 같은 키의 재전송이면 기존 run ID를 돌려준다."""
        digest = content_hash(content)
        try:
            async with self._write() as conn:
                conv = (
                    await conn.execute(
                        select(conversations).where(conversations.c.id == conversation_id).with_for_update()
                    )
                ).first()
                if conv is None or conv.owner_user_id != actor.user_id:
                    raise AppError(ErrorCode.CONVERSATION_NOT_FOUND)
                # 잠금을 얻은 뒤 시각을 잡는다. 영속 deadline과 단조 deadline을 같은 시점에서 계산해,
                # 잠금 대기만큼 실행이 영속 deadline을 넘겨 "늦은 완료"로 버려지지 않게 한다.
                now = self._clock.now()
                monotonic_now = self._clock.monotonic()
                await self._expire_runs(conn, now, conversation_id=conversation_id)

                receipt = (
                    await conn.execute(
                        select(message_receipts).where(
                            message_receipts.c.actor_id == actor.user_id,
                            message_receipts.c.conversation_id == conversation_id,
                            message_receipts.c.idempotency_key == key,
                        )
                    )
                ).first()
                if receipt is not None:
                    if receipt.content_hash != digest:
                        raise AppError(ErrorCode.MESSAGE_IDEMPOTENCY_CONFLICT)
                    return receipt.run_id

                active = await conn.scalar(
                    select(conversations.c.active_run_id).where(conversations.c.id == conversation_id)
                )
                if active is not None:
                    raise AppError(ErrorCode.CONVERSATION_BUSY)

                run_id, message_id = uuid.uuid4(), uuid.uuid4()
                await conn.execute(
                    messages.insert().values(
                        id=message_id,
                        conversation_id=conversation_id,
                        role="user",
                        content=content,
                        run_id=run_id,
                        training_refs=[],
                        dependency_ids=[],
                        visibility="visible",
                        created_at=now,
                    )
                )
                await conn.execute(
                    agent_runs.insert().values(
                        id=run_id,
                        conversation_id=conversation_id,
                        request_id=request_id,
                        user_message_id=message_id,
                        status="running",
                        accepted_at=now,
                        deadline_at=now + timedelta(seconds=self._policy.run_timeout_s),
                        prompt_version=self._prompt_version,
                        model=self._model_name,
                        retrieval_context={"knowledge_enabled": False, "corpus_snapshot_id": None},
                    )
                )
                await conn.execute(
                    message_receipts.insert().values(
                        actor_id=actor.user_id,
                        conversation_id=conversation_id,
                        idempotency_key=key,
                        content_hash=digest,
                        user_message_id=message_id,
                        run_id=run_id,
                        created_at=now,
                    )
                )
                await conn.execute(
                    update(conversations)
                    .where(conversations.c.id == conversation_id)
                    .values(active_run_id=run_id, updated_at=now)
                )
        except IntegrityError as exc:
            # 행 잠금을 피해 간 경쟁이 있어도 부분 유일 인덱스가 두 번째 running run을 거절한다.
            # 그 밖의 무결성 오류는 "다른 실행 중"이 아니라 저장 실패다.
            constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            if constraint in _BUSY_CONSTRAINTS:
                raise AppError(ErrorCode.CONVERSATION_BUSY) from exc
            raise AppError(ErrorCode.PERSISTENCE_FAILED, retryable=True) from exc
        return _Accepted(run_id, message_id, now, monotonic_now + self._policy.run_timeout_s)

    async def _execute(
        self, actor: ActorContext, conversation_id: UUID, content: str, accepted: _Accepted, request_id: str
    ) -> bool:
        """실행하고 종료 상태를 저장한다. 종료 저장에 성공하면 True."""
        try:
            snapshot = await self._snapshot(actor, conversation_id, accepted.user_message_id)
            context = ExecutionContext(
                request_id=request_id,
                conversation_id=str(conversation_id),
                run_id=str(accepted.run_id),
                actor=actor,
                current_time=accepted.accepted_at,
                deadline_monotonic=accepted.deadline_monotonic,
                deadline_at=accepted.accepted_at + timedelta(seconds=self._policy.run_timeout_s),
                policy=self._policy,
                retrieval_context=RetrievalContext(),
            )
            result = await self._runtime.execute(
                context, snapshot, content, DbExecutionObserver(self._engine)
            )
        except Exception as exc:
            # 실행 준비 중 예기치 못한 오류. 예외 메시지에는 입력·본문이 실릴 수 있어 종류만 남긴다(T-03).
            logger.error("실행 준비 실패 run_id=%s error=%s", accepted.run_id, _error_kind(exc))
            # 이력·사본을 읽다 난 DB 오류는 저장소 장애(PERSISTENCE_FAILED)로 남긴다.
            failure = exc if isinstance(exc, AppError) else AppError(ErrorCode.SERVICE_UNAVAILABLE)
            return await self._finish(conversation_id, accepted.run_id, None, failure)
        return await self._finish(conversation_id, accepted.run_id, result, result.error)

    async def _snapshot(
        self, actor: ActorContext, conversation_id: UUID, user_message_id: UUID
    ) -> ConversationSnapshot:
        """CT-03: 이번 질문 전의 최근 메시지(가린 답변 제외)와 receipt로 검증한 업무 상태."""
        async with self._read() as conn:
            current_seq = await conn.scalar(select(messages.c.seq).where(messages.c.id == user_message_id))
            rows = (
                await conn.execute(
                    select(messages)
                    .where(messages.c.conversation_id == conversation_id, messages.c.seq < current_seq)
                    .order_by(messages.c.seq.desc())
                    .limit(self._policy.history_messages)
                )
            ).all()
            state = await conn.scalar(
                select(conversations.c.business_state).where(conversations.c.id == conversation_id)
            )
            pairs = await verified_training_pairs(conn, conversation_id)
        history = [
            HistoryMessage(r.role, r.content)
            for r in reversed(rows)
            if r.role == "user" or _can_view(actor, r)
        ]
        # 창이 잘리거나 답이 가려져 첫 메시지가 assistant가 되면 그 앞을 버린다(대화는 user로 시작한다).
        while history and history[0].role == "assistant":
            history.pop(0)
        state = state or {}
        # receipt로 검증한 사본도 지금 볼 수 없는 자원이면 모델 문맥에 넣지 않는다(CT-03 현재 권한 재검증).
        cache = verified_cache(state, pairs) if _can_view_trainings(actor) else {}
        selected = state.get("selected_training_id")
        return ConversationSnapshot(
            messages=tuple(history),
            training_cache=cache,
            last_training_ids=tuple(i for i in state.get("last_training_ids", []) if i in cache),
            selected_training_id=selected if selected in cache else None,
        )

    async def _finish(
        self, conversation_id: UUID, run_id: UUID, result: ExecutionResult | None, error: AppError | None
    ) -> bool:
        """Finalize(완료) 또는 Fail/Expire. 저장에 성공하면 True. 예외를 밖으로 던지지 않는다."""
        try:
            async with self._write() as conn:
                # 잠금 순서: 모든 쓰기 경로가 대화 행 → run 순서로 잠근다(수락과 교착하지 않게).
                await self._lock_conversation(conn, conversation_id)
                now = self._clock.now()  # 잠금을 얻은 뒤의 시각으로 deadline을 비교한다
                if result is not None and result.status == "completed":
                    done = await self._complete(conn, conversation_id, run_id, result, now)
                    if not done:
                        # deadline 이후 도착한 결과: 덮어쓰지 않고 만료로 회수한다.
                        logger.info("늦은 완료 무시 run_id=%s", run_id)
                        await self._expire_runs(conn, now, run_id=run_id)
                else:
                    await self._fail(conn, conversation_id, run_id, result, error, now)
        except (AppError, SQLAlchemyError, OSError) as exc:
            # 최종 commit 실패: 성공으로 응답하지 않는다. run은 running으로 남고 deadline 뒤 회수된다.
            # 예외 메시지·traceback에는 답변 본문이 실릴 수 있어 종류만 남긴다(T-03).
            logger.error("실행 종료 저장 실패 run_id=%s error=%s", run_id, _error_kind(exc))
            return False
        return True

    async def _complete(
        self,
        conn: AsyncConnection,
        conversation_id: UUID,
        run_id: UUID,
        result: ExecutionResult,
        now: datetime,
    ) -> bool:
        message_id = uuid.uuid4()
        claimed = await conn.scalar(
            update(agent_runs)
            .where(
                agent_runs.c.id == run_id, agent_runs.c.status == "running", agent_runs.c.deadline_at > now
            )
            .values(
                status="completed",
                finished_at=now,
                outcome=result.outcome.value if result.outcome else None,
                usage=_usage(result),
                model_ids=list(result.model_ids),
                assistant_message_id=message_id,
            )
            .returning(agent_runs.c.id)
        )
        if claimed is None:
            return False
        refs = [
            {"id": r.get("id"), "code": r.get("code"), "title": r.get("title")} for r in result.training_refs
        ]
        await conn.execute(
            messages.insert().values(
                id=message_id,
                conversation_id=conversation_id,
                role="assistant",
                # PostgreSQL text는 NUL을 저장하지 못한다. 모델 답에 섞여도 저장 실패가 되지 않게 지운다.
                content=(result.answer or "").replace("\x00", ""),
                run_id=run_id,
                outcome=result.outcome.value if result.outcome else None,
                training_refs=refs,
                # 모델 문맥에 들어간 교육(답에서 가리킨 것 + 이번 결과)의 ID. 접근 재검사 대상이다.
                dependency_ids=sorted(
                    {*(r["id"] for r in refs), *(result.context_candidate or {}).get("training_cache", {})}
                ),
                visibility="visible",
                created_at=now,
            )
        )
        await conn.execute(
            update(conversations)
            .where(conversations.c.id == conversation_id, conversations.c.active_run_id == run_id)
            .values(active_run_id=None, business_state=result.context_candidate or {}, updated_at=now)
        )
        return True

    async def _fail(
        self,
        conn: AsyncConnection,
        conversation_id: UUID,
        run_id: UUID,
        result: ExecutionResult | None,
        error: AppError | None,
        now: datetime,
    ) -> None:
        error = error or AppError(ErrorCode.SERVICE_UNAVAILABLE)
        deadline = await conn.scalar(select(agent_runs.c.deadline_at).where(agent_runs.c.id == run_id))
        # 전체 시간 초과이거나 이미 deadline이 지났으면 expired, 그 전의 개별 실패면 failed(01-run-lifecycle).
        expired = error.code is ErrorCode.RUN_TIMEOUT or (deadline is not None and now >= deadline)
        claimed = await conn.scalar(
            update(agent_runs)
            .where(agent_runs.c.id == run_id, agent_runs.c.status == "running")
            .values(
                status="expired" if expired else "failed",
                finished_at=now,
                error_code=ErrorCode.RUN_TIMEOUT.value if expired else error.code.value,
                # 만료는 회수 경로와 같은 값(재시도로 같은 run이 살아나지 않음)으로 저장한다.
                error_retryable=False if expired else error.retryable,
                usage=_usage(result) if result else None,
                model_ids=list(result.model_ids) if result else None,
            )
            .returning(agent_runs.c.id)
        )
        if claimed is not None:
            # 실패·만료에서는 업무 상태 후보를 적용하지 않고 활성 소유권만 해제한다.
            await conn.execute(
                update(conversations)
                .where(conversations.c.id == conversation_id, conversations.c.active_run_id == run_id)
                .values(active_run_id=None, updated_at=now)
            )

    async def _respond(self, actor: ActorContext, run_id: UUID) -> MessageResponse:
        """저장된 run 상태로 응답을 만든다. 최초 응답과 같은 키 재전송이 같은 경로를 쓴다."""
        await self.recover_expired(run_id=run_id)
        async with self._read() as conn:
            run = (await conn.execute(select(agent_runs).where(agent_runs.c.id == run_id))).one()
            # 재전송에서도 현재 소유권을 다시 확인한다.
            await self._owned(conn, actor, run.conversation_id)
            if run.status == "running":
                return MessageResponse(
                    202,
                    {
                        "conversation_id": str(run.conversation_id),
                        "user_message_id": str(run.user_message_id),
                        "run_id": str(run.id),
                        "status": "running",
                    },
                )
            if run.status != "completed":
                code = ErrorCode(run.error_code or ErrorCode.SERVICE_UNAVAILABLE.value)
                # 04-api-spec: 실제 오류는 오류 envelope와 가능한 run_id를 포함하고 failed/expired를 보존한다.
                raise AppError(code, retryable=bool(run.error_retryable), run_id=str(run.id))
            message = (
                await conn.execute(select(messages).where(messages.c.id == run.assistant_message_id))
            ).one()
        visible = _can_view(actor, message)
        return MessageResponse(
            200,
            {
                "conversation_id": str(run.conversation_id),
                "run_id": str(run.id),
                "message_id": str(message.id),
                "status": "completed",
                # 현재 권한으로 볼 수 없게 됐으면 일반 안내로 가린다(04-api-spec 이력 가림 규칙).
                "outcome": message.outcome if visible else "insufficient_evidence",
                "answer": message.content if visible else _REDACTED_TEXT,
                "training_refs": message.training_refs if visible else [],
                "ticket_refs": [],
                "citations": [],
                "action_preview": None,
                "error": None,
            },
        )

    # --- 만료 회수 ---

    async def recover_expired(
        self, *, conversation_id: UUID | None = None, run_id: UUID | None = None
    ) -> int:
        """deadline 지난 running을 expired로 끝내고 활성 소유권을 푼다. 미래 deadline은 그대로 둔다."""
        now = self._clock.now()
        async with self._write() as conn:
            return await self._expire_runs(conn, now, conversation_id=conversation_id, run_id=run_id)

    async def _expire_runs(
        self,
        conn: AsyncConnection,
        now: datetime,
        *,
        conversation_id: UUID | None = None,
        run_id: UUID | None = None,
    ) -> int:
        """deadline 지난 running을 expired로 끝낸다. 대화 행을 먼저 잠그고(대화 ID 순) run을 갱신한다.

        수락·완료와 같은 잠금 순서(대화 → run)를 지켜 교착을 막는다.
        """
        if conversation_id is not None:
            conversation_ids = [conversation_id]
        else:
            due = select(agent_runs.c.conversation_id).where(
                agent_runs.c.status == "running", agent_runs.c.deadline_at <= now
            )
            if run_id is not None:
                due = due.where(agent_runs.c.id == run_id)
            rows = await conn.execute(due.distinct().order_by(agent_runs.c.conversation_id))
            conversation_ids = [row[0] for row in rows]
        count = 0
        for conv_id in conversation_ids:
            await self._lock_conversation(conn, conv_id)
            condition = [
                agent_runs.c.conversation_id == conv_id,
                agent_runs.c.status == "running",
                agent_runs.c.deadline_at <= now,
            ]
            if run_id is not None:
                condition.append(agent_runs.c.id == run_id)
            expired_ids = (
                await conn.scalars(
                    update(agent_runs)
                    .where(*condition)
                    .values(
                        status="expired",
                        finished_at=now,
                        error_code=ErrorCode.RUN_TIMEOUT.value,
                        error_retryable=False,
                    )
                    .returning(agent_runs.c.id)
                )
            ).all()
            if expired_ids:
                await conn.execute(
                    update(conversations)
                    .where(conversations.c.id == conv_id, conversations.c.active_run_id.in_(expired_ids))
                    .values(active_run_id=None, updated_at=now)
                )
            count += len(expired_ids)
        return count

    async def _lock_conversation(self, conn: AsyncConnection, conversation_id: UUID) -> None:
        """대화 행 잠금. 같은 트랜잭션에서 다시 잡으면 그대로 통과한다."""
        await conn.execute(
            select(conversations.c.id).where(conversations.c.id == conversation_id).with_for_update()
        )

    # --- 공통 ---

    async def _owned(self, conn: AsyncConnection, actor: ActorContext, conversation_id: UUID) -> Any:
        row = (await conn.execute(select(conversations).where(conversations.c.id == conversation_id))).first()
        if row is None or row.owner_user_id != actor.user_id:
            # 미존재와 타인 대화를 같은 404로 정규화한다.
            raise AppError(ErrorCode.CONVERSATION_NOT_FOUND)
        return row

    def _write(self):
        return _db(self._engine.begin())

    def _read(self):
        return _db(self._engine.connect())

    async def drain(self) -> None:
        """종료 시 진행 중인 실행을 기다린다(테스트·lifespan용)."""
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)


class _db:
    """DB 오류를 PERSISTENCE_FAILED로 바꾸는 연결 컨텍스트. AppError는 그대로 통과시킨다."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    async def __aenter__(self) -> AsyncConnection:
        try:
            return await self._inner.__aenter__()
        except (SQLAlchemyError, OSError) as exc:
            raise AppError(ErrorCode.PERSISTENCE_FAILED, retryable=True) from exc

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        try:
            await self._inner.__aexit__(exc_type, exc, tb)
        except IntegrityError:
            raise
        except (SQLAlchemyError, OSError) as commit_error:
            raise AppError(ErrorCode.PERSISTENCE_FAILED, retryable=True) from commit_error
        if (
            exc is not None
            and isinstance(exc, (SQLAlchemyError, OSError))
            and not isinstance(exc, IntegrityError)
        ):
            raise AppError(ErrorCode.PERSISTENCE_FAILED, retryable=True) from exc
        return False


def _error_kind(exc: BaseException) -> str:
    """로그용 오류 종류. 메시지 본문은 넣지 않고 예외 클래스(원인 포함)만 남긴다."""
    cause = exc.__cause__
    return f"{type(exc).__name__}<-{type(cause).__name__}" if cause else type(exc).__name__


def _usage(result: ExecutionResult) -> dict[str, Any]:
    usage = result.usage
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "complete": usage.complete,
        "model_attempts": usage.model_attempts,
    }
