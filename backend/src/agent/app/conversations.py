"""대화·메시지·run HTTP(docs/04-api-spec.md MOD-01 절). 응답은 모두 Cache-Control: private, no-store."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent.app.deps import current_actor
from agent.shared.actor import ActorContext
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
) -> JSONResponse:
    """최초 동기 완료 200, 같은 키 실행 중 202, 다른 실행 중 409, 같은 키·다른 내용 409(01-run-lifecycle)."""
    result = await request.app.state.conversations.post_message(
        actor, conversation_id, body.content, idempotency_key, request_id_of(request.scope)
    )
    return _json(result.body, result.status_code)


@router.get("/runs/{run_id}")
async def get_run(request: Request, actor: Actor, run_id: UUID) -> JSONResponse:
    return _json(await request.app.state.conversations.get_run(actor, run_id))
