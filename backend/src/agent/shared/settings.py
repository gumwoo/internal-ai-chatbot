"""시작 설정. 잘못된 조합이면 서버가 뜨기 전에 거부한다(docs/12-first-milestone-spec.md)."""

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]


def database_name(url: str) -> str:
    """SQLAlchemy URL에서 데이터베이스 이름만 꺼낸다."""
    return urlsplit(url).path.lstrip("/")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["local", "test", "production"] = "local"
    auth_mode: Literal["test_stub", "local_session"] = "test_stub"
    test_actor_id: Literal["test-a", "test-b"] | None = "test-a"

    database_url: str
    test_database_url: str | None = None
    # DB에 닿지 않을 때 기다리는 최대 시간. 없으면 OS TCP 재시도로 2분 넘게 멈춘다.
    db_connect_timeout_s: float = 5.0

    # 상태 변경 요청에서 허용할 Origin. 쉼표로 구분한다.
    allowed_origins: str = "http://localhost:5190,http://127.0.0.1:5190"

    chat_model: str = "claude-haiku-5-5"
    embedding_model: str = "gemini-embedding-2"
    embedding_dim: Literal[768, 1536] = 1536
    judge_model: str | None = None
    anthropic_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None

    fixture_mode: Literal["fixed_status", "live_clock"] = "fixed_status"

    @property
    def allowed_origin_set(self) -> frozenset[str]:
        return frozenset(o.strip() for o in self.allowed_origins.split(",") if o.strip())

    @model_validator(mode="after")
    def _check_combination(self) -> "Settings":
        if self.auth_mode == "test_stub":
            if self.app_env not in ("local", "test"):
                raise ValueError("AUTH_MODE=test_stub은 APP_ENV=local/test에서만 허용한다")
            if self.test_actor_id is None:
                raise ValueError("AUTH_MODE=test_stub이면 TEST_ACTOR_ID가 필요하다")
        if self.auth_mode == "local_session":
            raise ValueError("AUTH_MODE=local_session은 M3에서 구현한다. 지금은 test_stub만 쓸 수 있다")
        if self.app_env == "test" and not database_name(self.database_url).endswith("_test"):
            raise ValueError("APP_ENV=test에서는 DATABASE_URL이 이름이 _test로 끝나는 테스트 DB여야 한다")
        if self.test_database_url is not None:
            if database_name(self.test_database_url) == database_name(self.database_url):
                raise ValueError("TEST_DATABASE_URL은 DATABASE_URL과 다른 데이터베이스여야 한다")
            if not database_name(self.test_database_url).endswith("_test"):
                raise ValueError("TEST_DATABASE_URL의 데이터베이스 이름은 _test로 끝나야 한다")
        return self
