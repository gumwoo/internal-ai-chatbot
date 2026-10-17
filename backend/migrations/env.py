"""Alembic async 실행. 접속 URL은 Settings에서 읽는다.

- 기본: DATABASE_URL(개발 DB)
- `alembic -x target=test ...`: TEST_DATABASE_URL(테스트 DB)
- 코드에서 호출할 때는 Config.attributes["database_url"]로 직접 넘긴다.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from agent.shared.settings import Settings

config = context.config

if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

# 테이블은 각 모듈 마이그레이션이 직접 만든다. autogenerate는 쓰지 않는다.
target_metadata = None


def _database_url() -> str:
    if url := config.attributes.get("database_url"):
        return url
    settings = Settings()
    if context.get_x_argument(as_dictionary=True).get("target") == "test":
        if settings.test_database_url is None:
            raise RuntimeError("-x target=test에는 TEST_DATABASE_URL이 필요하다")
        return settings.test_database_url
    return settings.database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(_database_url(), poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


def run_migrations_online() -> None:
    # psycopg async는 Windows Proactor 루프를 지원하지 않는다.
    asyncio.run(run_async_migrations(), loop_factory=asyncio.SelectorEventLoop)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
