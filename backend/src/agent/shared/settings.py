"""시작 설정. 잘못된 조합이면 서버가 뜨기 전에 거부한다(docs/12-first-milestone-spec.md)."""

from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import make_url

REPO_ROOT = Path(__file__).resolve().parents[4]

# URL 쿼리로 접속 대상을 바꾸는 키. psycopg dialect는 쿼리를 접속 인자에 덮어쓰므로
# `.../agent_test?dbname=agent_dev`가 실제로는 개발 DB에 접속한다. 이런 URL은 거절한다.
_TARGET_QUERY_KEYS = frozenset({"dbname", "database", "host", "hostaddr", "port", "service"})


def database_name(url: str) -> str:
    """실제 접속할 데이터베이스 이름. 접속 대상을 바꾸는 쿼리 키가 있으면 ValueError."""
    parsed = make_url(url)
    overridden = sorted(_TARGET_QUERY_KEYS & {key.lower() for key in parsed.query})
    if overridden:
        raise ValueError(f"DB URL 쿼리로 접속 대상을 바꿀 수 없다: {overridden}")
    if not parsed.database:
        raise ValueError("DB URL에 데이터베이스 이름이 없다")
    return parsed.database


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # `ANTHROPIC_API_KEY=`처럼 빈 값은 빈 문자열이 아니라 미설정(None/기본값)으로 본다.
        env_ignore_empty=True,
    )

    # 실행 모드와 인증 방식은 기본값 없이 명시해야 한다. 설정이 빠지면 서버가 시작하지 않는다.
    app_env: Literal["local", "test", "production"]
    auth_mode: Literal["test_stub", "local_session"]
    test_actor_id: Literal["test-a", "test-b"] | None = None

    database_url: str
    test_database_url: str | None = None
    # DB에 닿지 않을 때 기다리는 최대 시간. 없으면 OS TCP 재시도로 2분 넘게 멈춘다.
    db_connect_timeout_s: float = 5.0

    # 상태 변경 요청에서 허용할 Origin. 쉼표로 구분한다.
    allowed_origins: str = "http://localhost:5190,http://127.0.0.1:5190"

    chat_model: str = "claude-haiku-5-5"
    embedding_model: str = "gemini-embedding-2"
    # 환경 변수는 문자열로 들어오므로 int로 받은 뒤 허용값을 검사한다(Literal[int]는 "1536"을 거절한다).
    embedding_dim: int = 1536
    judge_model: str | None = None
    anthropic_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None

    # MOD-04: fixture_mode는 기본값 없이 명시한다. seed 명령은 이 값이나 --mode가 없으면 거절한다.
    fixture_mode: Literal["fixed_status", "live_clock"] | None = None

    @property
    def allowed_origin_set(self) -> frozenset[str]:
        return frozenset(o.strip() for o in self.allowed_origins.split(",") if o.strip())

    @field_validator("embedding_dim")
    @classmethod
    def _check_embedding_dim(cls, value: int) -> int:
        if value not in (768, 1536):
            raise ValueError("EMBEDDING_DIM은 768 또는 1536이다(O-04에서 확정)")
        return value

    @model_validator(mode="after")
    def _check_combination(self) -> "Settings":
        if self.auth_mode == "test_stub":
            if self.app_env not in ("local", "test"):
                raise ValueError("AUTH_MODE=test_stub은 APP_ENV=local/test에서만 허용한다")
            if self.test_actor_id is None:
                raise ValueError("AUTH_MODE=test_stub이면 TEST_ACTOR_ID가 필요하다")
        if self.auth_mode == "local_session":
            raise ValueError("AUTH_MODE=local_session은 M3에서 구현한다. 지금은 test_stub만 쓸 수 있다")
        dev_name = database_name(self.database_url)
        if self.app_env == "test" and not dev_name.endswith("_test"):
            raise ValueError("APP_ENV=test에서는 DATABASE_URL이 이름이 _test로 끝나는 테스트 DB여야 한다")
        if self.test_database_url is not None:
            test_name = database_name(self.test_database_url)
            if test_name == dev_name:
                raise ValueError("TEST_DATABASE_URL은 DATABASE_URL과 다른 데이터베이스여야 한다")
            if not test_name.endswith("_test"):
                raise ValueError("TEST_DATABASE_URL의 데이터베이스 이름은 _test로 끝나야 한다")
        return self
