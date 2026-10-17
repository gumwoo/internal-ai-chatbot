"""비동기 DB 엔진(D-28). 모듈은 자기 테이블만 이 세션으로 다룬다(모듈 지도의 소유권 규칙).

psycopg async는 Windows 기본 Proactor 루프를 지원하지 않는다. 그래서 Selector 루프로 실행한다.
- uvicorn: `--loop asyncio:SelectorEventLoop`
- Alembic env.py, pytest: asyncio.SelectorEventLoop을 직접 지정
"""

import math

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine


def make_engine(url: str, connect_timeout_s: float = 5.0) -> AsyncEngine:
    # libpq connect_timeout은 정수 초이고 2초 미만은 2초로 본다.
    timeout = max(2, math.ceil(connect_timeout_s))
    # hide_parameters: DB 오류 메시지에 SQL 파라미터(답변 본문·입력)가 실려 로그로 새지 않게 한다(T-03).
    return create_async_engine(
        url, pool_pre_ping=True, hide_parameters=True, connect_args={"connect_timeout": timeout}
    )


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)
