import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.shared.settings import Settings, database_name
from tests.conftest import check_test_database, make_settings

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"


def test_env_example_loads_as_is(tmp_path, monkeypatch):
    """.env.example을 그대로 복사한 .env로 서버 설정이 만들어져야 한다(문자열 숫자·빈 값·줄 끝 주석)."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    env_file = tmp_path / ".env"
    shutil.copyfile(ENV_EXAMPLE, env_file)
    settings = Settings(_env_file=env_file)
    assert settings.embedding_dim == 1536
    assert settings.app_env == "local"
    assert settings.test_actor_id == "test-a"
    assert settings.anthropic_api_key is None
    assert settings.judge_model is None
    assert database_name(settings.database_url) == "agent_dev"
    assert database_name(settings.test_database_url) == "agent_test"


def test_embedding_dim_rejects_other_values():
    with pytest.raises(ValidationError, match="EMBEDDING_DIM"):
        make_settings(embedding_dim=3072)


def test_test_stub_allowed_in_test_env():
    settings = make_settings()
    assert settings.auth_mode == "test_stub"
    assert settings.test_actor_id == "test-a"


def test_test_stub_refused_in_production():
    with pytest.raises(ValidationError, match="test_stub"):
        make_settings(app_env="production")


def test_local_session_mode_and_session_ttl():
    # M3: local_session은 production에서도 쓸 수 있다(test_stub만 local/test로 제한).
    assert make_settings(auth_mode="local_session", app_env="production").auth_mode == "local_session"
    with pytest.raises(ValidationError, match="SESSION_TTL_S"):
        make_settings(auth_mode="local_session", session_ttl_s=0)


def test_unknown_actor_id_refused():
    with pytest.raises(ValidationError):
        make_settings(test_actor_id="admin")


def test_test_stub_requires_actor_id():
    with pytest.raises(ValidationError, match="TEST_ACTOR_ID"):
        make_settings(test_actor_id=None)


def test_test_env_requires_test_database():
    with pytest.raises(ValidationError, match="_test"):
        make_settings(database_url="postgresql+psycopg://u:p@127.0.0.1:5440/agent_dev")


def test_test_database_must_differ_from_dev():
    with pytest.raises(ValidationError, match="다른 데이터베이스"):
        make_settings(
            app_env="local",
            database_url="postgresql+psycopg://u:p@127.0.0.1:5440/agent_test",
            test_database_url="postgresql+psycopg://u:p@127.0.0.1:5440/agent_test",
        )


DEV = "postgresql+psycopg://u:p@127.0.0.1:5440/agent_dev"


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://u:p@127.0.0.1:5440/agent_test?dbname=agent_dev",
        "postgresql+psycopg://u:p@127.0.0.1:5440/agent_test?host=10.0.0.9",
        "postgresql+psycopg://u:p@127.0.0.1:5440/agent_test?port=5432",
        "postgresql+psycopg://u:p@127.0.0.1:5440/agent_test?service=prod",
        "postgresql+psycopg://u:p@127.0.0.1:5440/agent_test?DBNAME=agent_dev",
    ],
)
def test_url_query_cannot_redirect_connection(url):
    """M0 검증 P2-1: `_test` 이름으로 검사를 통과하고 쿼리로 다른 DB에 접속하는 우회를 막는다."""
    with pytest.raises(ValueError, match="접속 대상"):
        database_name(url)
    with pytest.raises(ValidationError, match="접속 대상"):
        make_settings(database_url=url)
    assert check_test_database(url, DEV) is not None


def test_check_test_database_rules():
    assert check_test_database("postgresql+psycopg://u:p@h:1/agent_test", DEV) is None
    assert "_test" in check_test_database(DEV, None)
    assert "같다" in check_test_database(
        "postgresql+psycopg://u:p@h:1/x_test", "postgresql+psycopg://u:p@h:2/x_test"
    )


def test_test_database_url_must_end_with_test():
    with pytest.raises(ValidationError, match="_test로 끝나야"):
        make_settings(
            app_env="local",
            database_url=DEV,
            test_database_url="postgresql+psycopg://u:p@127.0.0.1:5440/other",
        )


@pytest.mark.parametrize("missing", ["app_env", "auth_mode"])
def test_mode_settings_have_no_defaults(monkeypatch, missing):
    """M0 검증 P2-2: 실행 모드·인증 방식이 빠지면 test_stub으로 조용히 켜지지 않고 시작을 거절한다."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    values = {"app_env": "local", "auth_mode": "test_stub", "test_actor_id": "test-a", "database_url": DEV}
    del values[missing]
    with pytest.raises(ValidationError, match=missing):
        Settings(_env_file=None, **values)


def test_empty_test_actor_id_is_refused(monkeypatch):
    monkeypatch.setenv("TEST_ACTOR_ID", "")
    with pytest.raises(ValidationError, match="TEST_ACTOR_ID"):
        Settings(_env_file=None, app_env="local", auth_mode="test_stub", database_url=DEV)


def test_fixture_mode_has_no_default(monkeypatch):
    monkeypatch.delenv("FIXTURE_MODE", raising=False)
    assert make_settings().fixture_mode is None


def test_allowed_origins_parsed():
    settings = make_settings(allowed_origins=" http://a.test:1 , http://b.test:2 ,")
    assert settings.allowed_origin_set == {"http://a.test:1", "http://b.test:2"}
