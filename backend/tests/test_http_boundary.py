"""HTTP 경계: request_id, Origin 검사, 오류 envelope, test_stub actor(DB 없이)."""

import time
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import Depends
from pydantic import BaseModel, ConfigDict

from agent.app.deps import current_actor
from agent.app.main import create_app
from agent.shared.actor import ActorContext
from tests.conftest import make_settings

ORIGIN = "http://localhost:5190"


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str


def _app(**settings_overrides):
    app = create_app(make_settings(allowed_origins=ORIGIN, **settings_overrides))

    # 테스트 전용 라우트. 실제 업무 라우트는 M1부터 붙는다.
    @app.get("/api/v1/_test/whoami")
    async def whoami(actor: Annotated[ActorContext, Depends(current_actor)]) -> dict[str, str]:
        return {"user_id": actor.user_id, "source": actor.source}

    @app.post("/api/v1/_test/echo")
    async def echo(body: _Body) -> dict[str, str]:
        return {"title": body.title}

    return app


@asynccontextmanager
async def _client(app):
    async with app.router.lifespan_context(app):
        # Starlette는 500 계열 응답을 보낸 뒤 서버 로그용으로 예외를 다시 던진다. 응답만 검사한다.
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


def _assert_envelope(response: httpx.Response, status: int, code: str, stage: str) -> dict:
    assert response.status_code == status
    body = response.json()
    assert body["error"]["code"] == code
    assert body["error"]["stage"] == stage
    assert set(body["error"]) == {"code", "message", "stage", "retryable", "details"}
    assert body["request_id"] == response.headers["x-request-id"]
    assert response.headers["cache-control"] == "private, no-store"
    return body


async def test_live_and_request_id_is_server_generated():
    async with _client(_app()) as client:
        response = await client.get("/api/v1/health/live", headers={"X-Request-Id": "client-chosen"})
    assert response.status_code == 200
    assert response.json() == {"status": "live"}
    assert response.headers["x-request-id"] not in ("", "client-chosen")


async def test_post_without_origin_is_csrf_failed():
    async with _client(_app()) as client:
        response = await client.post("/api/v1/_test/echo", json={"title": "x"})
    _assert_envelope(response, 403, "CSRF_FAILED", "auth")


async def test_post_from_other_origin_is_csrf_failed():
    async with _client(_app()) as client:
        response = await client.post(
            "/api/v1/_test/echo", json={"title": "x"}, headers={"Origin": "http://evil.test"}
        )
    _assert_envelope(response, 403, "CSRF_FAILED", "auth")


async def test_post_from_allowed_origin_passes():
    async with _client(_app()) as client:
        response = await client.post("/api/v1/_test/echo", json={"title": "x"}, headers={"Origin": ORIGIN})
    assert response.status_code == 200
    assert response.json() == {"title": "x"}


async def test_unknown_field_is_rejected_with_field_names_only():
    async with _client(_app()) as client:
        response = await client.post(
            "/api/v1/_test/echo",
            json={"title": "x", "user_id": "admin-secret"},
            headers={"Origin": ORIGIN},
        )
    body = _assert_envelope(response, 422, "INVALID_REQUEST", "validation")
    assert body["error"]["details"] == {"field_names": ["user_id"]}
    assert "admin-secret" not in response.text


async def test_unknown_route_is_resource_not_found():
    async with _client(_app()) as client:
        response = await client.get("/api/v1/nope")
    _assert_envelope(response, 404, "RESOURCE_NOT_FOUND", "auth")


async def test_actor_is_fixed_by_server_settings():
    async with _client(_app(test_actor_id="test-b")) as client:
        response = await client.get(
            "/api/v1/_test/whoami", headers={"X-User-Id": "test-a", "X-Actor-Id": "test-a"}
        )
    assert response.json() == {"user_id": "test-b", "source": "test_stub"}


async def test_missing_current_actor_is_default_deny():
    app = _app()
    app.state.current_actor = None
    async with _client(app) as client:
        response = await client.get("/api/v1/_test/whoami")
    _assert_envelope(response, 401, "AUTHENTICATION_REQUIRED", "auth")


async def test_unhandled_error_hides_cause():
    app = _app()

    @app.get("/api/v1/_test/boom")
    async def boom() -> None:
        raise RuntimeError("db password is hunter2")

    async with _client(app) as client:
        response = await client.get("/api/v1/_test/boom")
    _assert_envelope(response, 503, "SERVICE_UNAVAILABLE", "execution")
    assert "hunter2" not in response.text


async def test_ready_without_database_is_service_unavailable():
    # 127.0.0.1:1에는 아무것도 없다. 시간 제한 안에 503으로 끝나야 한다.
    started = time.monotonic()
    async with _client(_app(db_connect_timeout_s=1.0)) as client:
        response = await client.get("/api/v1/health/ready")
    body = _assert_envelope(response, 503, "SERVICE_UNAVAILABLE", "execution")
    assert body["error"]["retryable"] is True
    assert time.monotonic() - started < 10
