"""상태 변경 요청의 Origin 검사(M0부터, docs/08-development-plan.md).

Origin이 없거나 허용 목록 밖이면 403 CSRF_FAILED. CSRF 토큰은 M3 세션과 함께 붙인다.
"""

from starlette.types import ASGIApp, Receive, Scope, Send

from agent.shared.errors import AppError, ErrorCode
from agent.shared.request_id import request_id_of, send_error

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class OriginCheckMiddleware:
    def __init__(self, app: ASGIApp, allowed_origins: frozenset[str]) -> None:
        self.app = app
        self.allowed = allowed_origins

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in SAFE_METHODS:
            await self.app(scope, receive, send)
            return
        origin = dict(scope["headers"]).get(b"origin")
        if origin is None or origin.decode("latin-1") not in self.allowed:
            await send_error(send, AppError(ErrorCode.CSRF_FAILED), request_id_of(scope))
            return
        await self.app(scope, receive, send)
