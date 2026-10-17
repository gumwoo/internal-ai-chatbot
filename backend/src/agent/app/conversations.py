"""대화·메시지·run HTTP(docs/04-api-spec.md MOD-01 절). 응답은 모두 Cache-Control: private, no-store."""

import json
from collections.abc import AsyncIterator
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent.app.deps import current_actor
from agent.modules.conversation.service import MessageResponse
from agent.shared.actor import ActorContext
from agent.shared.errors import AppError
from agent.shared.request_id import request_id_of

router = APIRouter(tags=["conversations"])

Actor = Annotated[ActorContext, Depends(current_actor)]
_NO_STORE = {"Cache-Control": "private, no-store"}


def _no_nul(value: str | None) -> str | None:
    # PostgreSQL text는 NUL을 저장하지 못한다. 저장 실패(재시도 가능 503)가 아니라 입력 오류(422)로 거절한다.
    if value is not None and "\x00" in value:
        raise ValueError("NUL 문자는 쓸 수 없다")
    return value


class CreateConversation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=100)

    _check_title = field_validator("title")(_no_nul)


class PostMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=4000)

    _check_content = field_validator("content")(_no_nul)


class Paging(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=20, ge=1, le=50)
    offset: int = Field(default=0, ge=0)


def _json(body: dict, status_code: int = 200) -> JSONResponse:
    return JSONResponse(body, status_code=status_code, headers=_NO_STORE)


@router.post("/conversations")
async def create_conversation(
    request: Request, actor: Actor, body: CreateConversation | None = None
) -> JSONResponse:
    created = await request.app.state.conversations.create_conversation(actor, body.title if body else None)
    return _json(created, 201)


@router.get("/conversations")
async def list_conversations(
    request: Request, actor: Actor, paging: Annotated[Paging, Query()]
) -> JSONResponse:
    return _json(await request.app.state.conversations.list_conversations(actor, paging.limit, paging.offset))


@router.get("/conversations/{conversation_id}")
async def get_conversation(request: Request, actor: Actor, conversation_id: UUID) -> JSONResponse:
    return _json(await request.app.state.conversations.get_conversation(actor, conversation_id))


@router.get("/conversations/{conversation_id}/messages")
async def list_messages(
    request: Request, actor: Actor, conversation_id: UUID, paging: Annotated[Paging, Query()]
) -> JSONResponse:
    service = request.app.state.conversations
    return _json(await service.list_messages(actor, conversation_id, paging.limit, paging.offset))


@router.post("/conversations/{conversation_id}/messages")
async def post_message(
    request: Request,
    actor: Actor,
    conversation_id: UUID,
    body: PostMessage,
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    accept: Annotated[str | None, Header()] = None,
) -> Response:
    """최초 동기 완료 200, 같은 키 실행 중 202, 다른 실행 중 409, 같은 키·다른 내용 409(01-run-lifecycle).

    `Accept: text/event-stream`이면 새로 수락한 실행만 SSE로 진행 단계와 최종 결과를 보낸다(D-29).
    """
    service = request.app.state.conversations
    request_id = request_id_of(request.scope)
    if not _wants_stream(accept):
        result = await service.post_message(actor, conversation_id, body.content, idempotency_key, request_id)
        return _json(result.body, result.status_code)
    outcome = await service.stream_message(actor, conversation_id, body.content, idempotency_key, request_id)
    if isinstance(outcome, MessageResponse):
        # 같은 키 재전송: SSE를 다시 열지 않는다(실행 중 202, 종료 200).
        return _json(outcome.body, outcome.status_code)
    return StreamingResponse(
        _sse(outcome, request_id),
        media_type="text/event-stream",
        headers={**_NO_STORE, "X-Accel-Buffering": "no", "X-Request-Id": request_id},
    )


def _wants_stream(accept: str | None) -> bool:
    """Accept에 text/event-stream이 있고 q=0(거부)이 아니면 SSE."""
    if accept is None:
        return False
    for part in accept.split(","):
        media, *params = (piece.strip().lower() for piece in part.split(";"))
        if media != "text/event-stream":
            continue
        q = next((p.split("=", 1)[1].strip() for p in params if p.startswith("q=")), "1")
        try:
            return float(q) > 0
        except ValueError:
            return False
    return False


async def _sse(events: AsyncIterator[tuple[str, Any]], request_id: str) -> AsyncIterator[str]:
    """SSE 직렬화. heartbeat는 주석 줄, 종료 이벤트(result·error)는 정확히 하나."""
    async for kind, payload in events:
        if kind == "heartbeat":
            yield ": heartbeat\n\n"
            continue
        if kind == "error":
            assert isinstance(payload, AppError)  # noqa: S101 - 서비스 계약
            payload = payload.to_envelope(request_id)
        yield f"event: {kind}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.get("/runs/{run_id}")
async def get_run(request: Request, actor: Actor, run_id: UUID) -> JSONResponse:
    return _json(await request.app.state.conversations.get_run(actor, run_id))
