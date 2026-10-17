"""요청마다 서버가 만든 request_id를 붙인다. 클라이언트가 보낸 값은 쓰지 않는다."""

import json
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from agent.shared.errors import AppError

HEADER = b"x-request-id"


def request_id_of(scope: Scope) -> str:
    return scope.setdefault("state", {}).setdefault("request_id", str(uuid.uuid4()))


async def send_error(send: Send, error: AppError, request_id: str) -> None:
    """미들웨어 단계에서 라우터를 거치지 않고 오류 envelope를 보낸다."""
    body = json.dumps(error.to_envelope(request_id), ensure_ascii=False).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": error.http_status,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
                (b"cache-control", b"private, no-store"),
                (HEADER, request_id.encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = request_id_of(scope)

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != HEADER]
                headers.append((HEADER, request_id.encode()))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_id)
