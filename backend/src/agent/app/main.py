"""APP-02 조립. 테스트는 create_app에 설정·CurrentActor·Clock·채팅 모델을 직접 넘긴다."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from agent.app import error_handlers
from agent.app.conversations import router as conversations_router
from agent.app.health import router as health_router
from agent.app.session import router as session_router
from agent.app.trainings import router as trainings_router
from agent.modules.agent_runtime.prompt import PROMPT_VERSION
from agent.modules.agent_runtime.runtime import AgentRuntime
from agent.modules.conversation.service import ConversationService
from agent.modules.identity_access.service import IdentityService
from agent.modules.identity_access.session_actor import SessionCurrentActor
from agent.modules.identity_access.test_stub import TestStubCurrentActor
from agent.modules.model_integration.anthropic_chat import AnthropicChatModel
from agent.modules.model_integration.ports import ChatModel, ModelConfig
from agent.modules.tool_execution.executor import ToolExecutor
from agent.modules.training.service import TrainingService
from agent.shared.actor import CurrentActor
from agent.shared.clock import Clock, SystemClock
from agent.shared.db import make_engine, make_session_factory
from agent.shared.origin import OriginCheckMiddleware
from agent.shared.request_id import RequestIdMiddleware
from agent.shared.settings import Settings

API_PREFIX = "/api/v1"
logger = logging.getLogger(__name__)


def _default_actor(settings: Settings) -> CurrentActor:
    if settings.auth_mode == "local_session":
        return SessionCurrentActor()
    # Settings 검증이 test_stub을 local/test로 제한하고 actor id를 강제한다. 여기서 한 번 더 막는다.
    if settings.auth_mode != "test_stub" or settings.test_actor_id is None:
        raise RuntimeError("test_stub actor에는 TEST_ACTOR_ID가 필요하다")
    return TestStubCurrentActor(settings.test_actor_id)


async def _recover_on_startup(service: ConversationService) -> None:
    try:
        recovered = await service.recover_expired()
    except Exception:
        logger.warning("시작 시 만료 회수 실패(다음 진입에서 다시 시도)", exc_info=True)
        return
    if recovered:
        logger.info("시작 시 만료 run %d건 회수", recovered)


def create_app(
    settings: Settings | None = None,
    current_actor: CurrentActor | None = None,
    clock: Clock | None = None,
    chat_model: ChatModel | None = None,
) -> FastAPI:
    settings = settings or Settings()
    clock = clock or SystemClock()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = make_engine(settings.database_url, settings.db_connect_timeout_s)
        app.state.engine = engine
        app.state.session_factory = make_session_factory(engine)
        app.state.identity = IdentityService(engine, clock, settings.session_ttl_s)
        trainings = TrainingService(engine)
        app.state.training_service = trainings
        # 키가 없으면 모델 호출 시 MODEL_NOT_CONFIGURED로 실패한다(서버 시작은 막지 않는다).
        key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
        chat = chat_model or AnthropicChatModel(api_key=key)
        model = ModelConfig(model=settings.chat_model, max_output_tokens=1024, config_version=PROMPT_VERSION)
        runtime = AgentRuntime(chat, ToolExecutor(trainings, clock), clock, model)
        service = ConversationService(
            engine, clock, runtime, model_name=settings.chat_model, prompt_version=PROMPT_VERSION
        )
        app.state.conversations = service
        # 시작 시 deadline 지난 running을 회수한다(01-run-lifecycle). DB 접속을 기다리느라 시작이 막히지 않게
        # 백그라운드로 돌린다. 실패해도 조회·수락 진입에서 다시 회수된다.
        startup_recovery = asyncio.create_task(_recover_on_startup(service))
        try:
            yield
        finally:
            if not startup_recovery.done():
                startup_recovery.cancel()
            await asyncio.gather(startup_recovery, return_exceptions=True)
            await service.drain()
            close = getattr(chat, "aclose", None)
            if close is not None and chat_model is None:
                await close()
            await engine.dispose()

    app = FastAPI(
        title="사내 업무 도우미 API", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.settings = settings
    app.state.current_actor = current_actor or _default_actor(settings)
    app.state.clock = clock

    error_handlers.install(app)
    app.include_router(health_router, prefix=API_PREFIX)
    if settings.auth_mode == "local_session":
        # 세션 API는 실제 세션 모드에서만 연다. test_stub에서는 클라이언트가 사용자를 고르지 못한다.
        app.include_router(session_router, prefix=API_PREFIX)
    app.include_router(trainings_router, prefix=API_PREFIX)
    app.include_router(conversations_router, prefix=API_PREFIX)

    # 바깥부터 RequestId → Origin 순서로 실행된다.
    app.add_middleware(OriginCheckMiddleware, allowed_origins=settings.allowed_origin_set)
    app.add_middleware(RequestIdMiddleware)
    return app
