"""GET /health/live, /health/ready(docs/04-api-spec.md). 모델 호출은 하지 않는다."""

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from agent.shared.errors import AppError, ErrorCode

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "live"}


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    engine = request.app.state.engine
    try:
        # 접속 뒤 쿼리가 멈춰도 ready가 끝없이 기다리지 않게 전체 시간을 제한한다.
        async with asyncio.timeout(request.app.state.settings.db_connect_timeout_s * 2):
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
                vector = await conn.scalar(
                    text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
                )
    except (SQLAlchemyError, OSError, TimeoutError) as exc:
        raise AppError(ErrorCode.SERVICE_UNAVAILABLE, retryable=True) from exc
    if vector is None:
        # 마이그레이션 전이면 필수 의존이 준비되지 않은 것으로 본다.
        raise AppError(ErrorCode.SERVICE_UNAVAILABLE, retryable=True)
    return JSONResponse(
        {
            "status": "ready",
            "checks": {"database": "ok", "vector_extension": vector},
            # 문서·Wiki 미게시는 장애가 아니라 비활성 capability로 표시한다(disabled/ready, Wiki는 stale도).
            "capabilities": await _capabilities(request),
        }
    )


async def _capabilities(request: Request) -> dict[str, str]:
    knowledge = getattr(request.app.state, "knowledge", None)
    wiki = getattr(request.app.state, "wiki", None)
    try:
        corpus = await knowledge.current_snapshot() if knowledge is not None else None
        wiki_state = (await wiki.status())["state"] if wiki is not None else "not_ready"
    except SQLAlchemyError:
        # 마이그레이션 전 등: 필수 의존(DB)은 위에서 확인했고, 선택 기능만 비활성으로 표시한다.
        return {"knowledge": "disabled", "wiki": "disabled"}
    return {
        "knowledge": "ready" if corpus else "disabled",
        "wiki": {"ready": "ready", "stale": "stale"}.get(wiki_state, "disabled"),
    }
