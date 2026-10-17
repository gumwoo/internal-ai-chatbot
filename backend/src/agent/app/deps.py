"""라우터가 쓰는 의존성. actor는 앱 조립 시 주입된 CurrentActor로만 해석한다(기본 거부)."""

from collections.abc import Awaitable, Callable

from fastapi import Request

from agent.shared.actor import ActorContext, CurrentActor
from agent.shared.errors import AppError, ErrorCode


async def current_actor(request: Request) -> ActorContext:
    resolver: CurrentActor | None = getattr(request.app.state, "current_actor", None)
    if resolver is None:
        raise AppError(ErrorCode.AUTHENTICATION_REQUIRED)
    return await resolver.resolve(request)


def require_capability(capability: str) -> Callable[[Request], Awaitable[ActorContext]]:
    """현재 actor가 capability를 가졌는지 확인한다. 없으면 403 ACTION_NOT_ALLOWED."""

    async def dependency(request: Request) -> ActorContext:
        actor = await current_actor(request)
        if capability not in actor.capabilities:
            raise AppError(ErrorCode.ACTION_NOT_ALLOWED)
        return actor

    return dependency
