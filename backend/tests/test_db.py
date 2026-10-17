"""테스트 DB가 필요한 검사. TEST_DATABASE_URL이 없으면 건너뛴다."""

import asyncio

from alembic import command
from sqlalchemy import text

from agent.app.main import create_app
from agent.shared.db import make_engine
from tests.conftest import alembic_config, api_client, make_settings


async def _vector_version(url: str) -> str | None:
    engine = make_engine(url)
    try:
        async with engine.connect() as conn:
            return await conn.scalar(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'"))
    finally:
        await engine.dispose()


async def _table_exists(url: str, name: str) -> bool:
    engine = make_engine(url)
    try:
        async with engine.connect() as conn:
            return bool(await conn.scalar(text("SELECT to_regclass(:name) IS NOT NULL"), {"name": name}))
    finally:
        await engine.dispose()


async def test_migration_down_and_up(migrated: str):
    # alembic env.py는 자체 이벤트 루프를 돌리므로 테스트 루프 밖 스레드에서 실행한다.
    config = alembic_config(migrated)
    await asyncio.to_thread(command.downgrade, config, "base")
    assert await _vector_version(migrated) is None
    assert await _table_exists(migrated, "trainings") is False
    await asyncio.to_thread(command.upgrade, config, "head")
    assert await _vector_version(migrated) is not None
    assert await _table_exists(migrated, "trainings") is True


async def test_ready_reports_database_and_disabled_capabilities(migrated: str):
    app = create_app(make_settings(database_url=migrated))
    async with api_client(app) as client:
        response = await client.get("/api/v1/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["vector_extension"]
    assert body["capabilities"] == {"knowledge": "disabled", "wiki": "disabled"}
