"""공통 fixture. DB 테스트는 이름이 _test로 끝나는 테스트 DB에서만 돈다(FR-08)."""

import asyncio
import os

import pytest

from agent.shared.settings import Settings, database_name


def pytest_asyncio_loop_factories(config, item):
    # psycopg async는 Windows Proactor 루프를 지원하지 않는다.
    return {"selector": asyncio.SelectorEventLoop}


def _configured_urls() -> tuple[str | None, str | None]:
    """환경 변수, 없으면 .env(Settings)에서 개발·테스트 DB URL을 읽는다."""
    test_url = os.environ.get("TEST_DATABASE_URL")
    dev_url = os.environ.get("DATABASE_URL")
    if test_url is None or dev_url is None:
        try:
            loaded = Settings()
        except Exception:
            return dev_url, test_url
        test_url = test_url or loaded.test_database_url
        dev_url = dev_url or loaded.database_url
    return dev_url, test_url


@pytest.fixture(scope="session")
def test_database_url() -> str:
    dev_url, test_url = _configured_urls()
    if test_url is None:
        pytest.skip("TEST_DATABASE_URL이 없어 DB 테스트를 건너뛴다")
    name = database_name(test_url)
    if not name.endswith("_test"):
        pytest.exit(f"테스트 DB 이름이 _test로 끝나지 않는다: {name}", returncode=2)
    if dev_url is not None and database_name(dev_url) == name:
        pytest.exit("테스트 DB가 개발 DB와 같다", returncode=2)
    return test_url


def make_settings(
    database_url: str = "postgresql+psycopg://u:p@127.0.0.1:1/none_test", **overrides
) -> Settings:
    """.env를 읽지 않는 테스트 설정. OS 환경 변수의 TEST_DATABASE_URL도 쓰지 않게 비운다."""
    values = {
        "app_env": "test",
        "auth_mode": "test_stub",
        "test_actor_id": "test-a",
        "database_url": database_url,
        "test_database_url": None,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)
