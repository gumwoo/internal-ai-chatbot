# APP-02 플랫폼 API 이미지. 마이그레이션은 자동 실행하지 않는다(별도 명령으로 적용).
FROM ghcr.io/astral-sh/uv:0.13.0 AS uv

FROM python:3.13-slim
COPY --from=uv /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 의존성만 먼저 설치해 소스 변경 때 캐시를 재사용한다.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project

COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --locked --no-dev

RUN useradd --system --uid 10001 app
USER app

EXPOSE 8010
CMD ["/app/.venv/bin/uvicorn", "agent.app.main:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8010", "--loop", "asyncio:SelectorEventLoop"]
