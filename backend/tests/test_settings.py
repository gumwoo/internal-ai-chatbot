import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.shared.settings import Settings, database_name
from tests.conftest import make_settings

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


def test_local_session_not_implemented_yet():
    with pytest.raises(ValidationError, match="M3"):
        make_settings(auth_mode="local_session")


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


def test_allowed_origins_parsed():
    settings = make_settings(allowed_origins=" http://a.test:1 , http://b.test:2 ,")
    assert settings.allowed_origin_set == {"http://a.test:1", "http://b.test:2"}
