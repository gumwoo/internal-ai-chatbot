"""CP-02 CurrentActor의 local_session 구현.

세션 cookie로 actor를 만들고, 상태 변경 요청은 CSRF 토큰을 확인한다.

- cookie 이름 agent_session(HttpOnly·SameSite=Strict, production에서 Secure).
- 상태 변경(GET/HEAD/OPTIONS 외) 요청은 X-CSRF-Token이 세션 토큰의 HMAC과 같아야 한다(403 CSRF_FAILED).
  Origin 검사는 앞단 미들웨어가 따로 한다.
- 요청 헤더·본문·쿼리의 user_id·역할은 읽지 않는다.
"""

import hmac

from starlette.requests import Request

from agent.modules.identity_access.service import csrf_token_for
from agent.shared.actor import ActorContext
from agent.shared.errors import AppError, ErrorCode

SESSION_COOKIE = "agent_session"
CSRF_HEADER = "X-CSRF-Token"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def check_csrf(request: Request, token: str) -> None:
    if request.method in _SAFE_METHODS:
        return
    sent = request.headers.get(CSRF_HEADER)
    # bytes로 비교한다. ASCII가 아닌 헤더 값도 비교 오류(503) 없이 403이 된다.
    if not sent or not hmac.compare_digest(sent.encode("utf-8"), csrf_token_for(token).encode("ascii")):
        raise AppError(ErrorCode.CSRF_FAILED)


class SessionCurrentActor:
    """앱 lifespan이 만든 IdentityService(app.state.identity)로 해석한다."""

    async def resolve(self, request: Request) -> ActorContext:
        token = request.cookies.get(SESSION_COOKIE)
        actor = await request.app.state.identity.resolve_actor(token)
        assert token is not None  # noqa: S101 - resolve_actor가 빈 토큰을 거절한다
        check_csrf(request, token)
        return actor
