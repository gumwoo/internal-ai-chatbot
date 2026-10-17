"""테스트 DB가 필요한 검사. TEST_DATABASE_URL이 없으면 건너뛴다."""

import asyncio
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from agent.app.main import create_app
from agent.shared.db import make_engine
from tests.conftest import make_settings

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def _alembic(url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.attributes["database_url"] = url
    config.attributes["configure_logger"] = False
    return config


async def _vector_version(url: str) -> str | None:
    engine = make_engine(url)
    try:
        async with engine.connect() as conn:
            return await conn.scalar(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'"))
    finally:
        await engine.dispose()


@pytest.fixture
def migrated(test_database_url: str) -> str:
    command.upgrade(_alembic(test_database_url), "head")
    return test_database_url


async def test_migration_down_and_up(migrated: str):
    # alembic env.py는 자체 이벤트 루프를 돌리므로 테스트 루프 밖 스레드에서 실행한다.
    config = _alembic(migrated)
    await asyncio.to_thread(command.downgrade, config, "base")
    assert await _vector_version(migrated) is None
    await asyncio.to_thread(command.upgrade, config, "head")
    assert await _vector_version(migrated) is not None


async def test_ready_reports_database_and_disabled_capabilities(migrated: str):
    app = create_app(make_settings(database_url=migrated))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/api/v1/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["vector_extension"]
    assert body["capabilities"] == {"knowledge": "disabled", "wiki": "disabled"}
