"""IT 지원 HTTP(docs/04-api-spec.md MOD-12 절). 수정·확인·취소는 인증·CSRF를 통과한 화면 요청만 받는다.

응답은 모두 Cache-Control: private, no-store. 미존재·불허는 같은 404다(서비스가 판정).
"""

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from agent.app.deps import current_actor
from agent.shared.actor import ActorContext

router = APIRouter(tags=["it-support"])

Actor = Annotated[ActorContext, Depends(current_actor)]
_NO_STORE = {"Cache-Control": "private, no-store"}


class TicketPaging(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["open"] | None = None
    limit: int = Field(default=10, ge=1, le=20)
    offset: int = Field(default=0, ge=0)


class ReviseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    fields: dict[str, Any]


class VersionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)


def _json(body: dict[str, Any], status_code: int = 200) -> JSONResponse:
    return JSONResponse(body, status_code=status_code, headers=_NO_STORE)


@router.get("/it-tickets")
async def list_tickets(
    request: Request, actor: Actor, paging: Annotated[TicketPaging, Query()]
) -> JSONResponse:
    page = await request.app.state.tickets.list_tickets(
        actor, status=paging.status, limit=paging.limit, offset=paging.offset
    )
    return _json(page)


@router.get("/it-tickets/{ticket_id}")
async def get_ticket(request: Request, actor: Actor, ticket_id: str) -> JSONResponse:
    return _json(await request.app.state.tickets.get_ticket(actor, ticket_id))


@router.get("/ticket-actions/{action_id}")
async def get_action(request: Request, actor: Actor, action_id: str) -> JSONResponse:
    return _json(await request.app.state.tickets.get_action(actor, action_id))


@router.post("/ticket-actions/{action_id}/revise")
async def revise(
    request: Request,
    actor: Actor,
    action_id: str,
    body: ReviseBody,
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> JSONResponse:
    outcome = await request.app.state.tickets.revise(
        actor, action_id, version=body.version, fields=body.fields, key=idempotency_key
    )
    return _json(outcome.body, outcome.status_code)


@router.post("/ticket-actions/{action_id}/confirm")
async def confirm(
    request: Request,
    actor: Actor,
    action_id: str,
    body: VersionBody,
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> JSONResponse:
    outcome = await request.app.state.tickets.confirm(
        actor, action_id, version=body.version, key=idempotency_key
    )
    return _json(outcome.body, outcome.status_code)


@router.post("/ticket-actions/{action_id}/cancel")
async def cancel(request: Request, actor: Actor, action_id: str, body: VersionBody) -> JSONResponse:
    outcome = await request.app.state.tickets.cancel(actor, action_id, version=body.version)
    return _json(outcome.body, outcome.status_code)
