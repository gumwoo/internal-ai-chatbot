"""APP-02 조립. 테스트는 create_app에 설정·CurrentActor를 직접 넘긴다."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from agent.app import error_handlers
from agent.app.health import router as health_router
from agent.modules.identity_access.test_stub import TestStubCurrentActor
from agent.shared.actor import CurrentActor
from agent.shared.db import make_engine, make_session_factory
from agent.shared.origin import OriginCheckMiddleware
from agent.shared.request_id import RequestIdMiddleware
from agent.shared.settings import Settings

API_PREFIX = "/api/v1"


def _default_actor(settings: Settings) -> CurrentActor:
    # Settings 검증이 test_stub을 local/test로 제한하고 actor id를 강제한다. 여기서 한 번 더 막는다.
    if settings.auth_mode != "test_stub" or settings.test_actor_id is None:
        raise RuntimeError("지금 구현된 CurrentActor는 test_stub뿐이다")
    return TestStubCurrentActor(settings.test_actor_id)


def create_app(settings: Settings | None = None, current_actor: CurrentActor | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = make_engine(settings.database_url, settings.db_connect_timeout_s)
        app.state.engine = engine
        app.state.session_factory = make_session_factory(engine)
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(title="사내 업무 도우미 API", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.current_actor = current_actor or _default_actor(settings)

    error_handlers.install(app)
    app.include_router(health_router, prefix=API_PREFIX)

    # 바깥부터 RequestId → Origin 순서로 실행된다.
    app.add_middleware(OriginCheckMiddleware, allowed_origins=settings.allowed_origin_set)
    app.add_middleware(RequestIdMiddleware)
    return app
