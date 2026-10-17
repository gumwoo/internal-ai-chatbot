import pytest
from pydantic import ValidationError

from tests.conftest import make_settings


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
