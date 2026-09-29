import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from py_common.settings import Settings


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for key in list(os.environ):
        if key.startswith("CW_"):
            monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)  # no repo .env in reach


def test_defaults() -> None:
    settings = Settings()
    assert settings.service_name == "compliancewatch"
    assert settings.env == "local"
    assert settings.log_level == "INFO"
    assert settings.log_json is True
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.db_schema is None
    assert settings.kafka_bootstrap == "localhost:19092"
    assert settings.otel_endpoint is None
    assert settings.auth_mode == "header"
    assert settings.auth_issuer == "urn:compliancewatch:identity"
    assert settings.auth_audience == "compliancewatch"
    assert settings.auth_jwks_url == "http://localhost:8001/v1/identity/.well-known/jwks.json"
    assert settings.auth_jwks_json is None
    assert settings.auth_leeway_seconds == 30
    assert settings.identity_url == "http://localhost:8001"
    assert settings.service_client_id == ""
    assert settings.service_client_secret is None


def test_env_prefix_and_level_normalisation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CW_LOG_LEVEL", "debug")
    monkeypatch.setenv("CW_ENV", "prod")
    monkeypatch.setenv("CW_AUTH_MODE", "token")
    monkeypatch.setenv("CW_DB_SCHEMA", "obligation")
    settings = Settings()
    assert settings.log_level == "DEBUG"
    assert settings.env == "prod"
    assert settings.db_schema == "obligation"


def test_the_settings_remember_which_env_files_they_read(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("CW_LOG_LEVEL=error\n", encoding="utf-8")
    assert Settings().env_files == (Path(".env"),)
    assert Settings().log_level == "ERROR"
    hermetic = Settings(_env_file=None)
    assert (hermetic.env_files, hermetic.log_level) == ((), "INFO")
    assert Settings(_env_file="other.env").env_files == (Path("other.env"),)


def test_service_name_is_passed_by_the_composition_root() -> None:
    assert Settings(service_name="obligation").service_name == "obligation"


def test_unprefixed_variables_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "error")
    assert Settings().log_level == "INFO"


@pytest.mark.parametrize("mode", ["header", "dual"])
def test_production_refuses_every_auth_mode_but_token(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    monkeypatch.setenv("CW_ENV", "prod")
    monkeypatch.setenv("CW_AUTH_MODE", mode)
    with pytest.raises(ValidationError, match="CW_ENV=prod needs CW_AUTH_MODE=token"):
        Settings()


def test_production_without_an_auth_mode_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CW_ENV", "prod")
    with pytest.raises(ValidationError, match="got header"):
        Settings()


@pytest.mark.parametrize(
    ("env", "mode"),
    [("prod", "token"), ("staging", "dual"), ("local", "header"), ("test", "token")],
)
def test_other_combinations_are_accepted(env: str, mode: str) -> None:
    settings = Settings(env=env, auth_mode=mode)  # type: ignore[arg-type]
    assert (settings.env, settings.auth_mode) == (env, mode)


@pytest.mark.parametrize("mode", ["off", "TOKEN", "bearer"])
def test_an_unknown_auth_mode_is_refused(mode: str) -> None:
    with pytest.raises(ValidationError, match="auth_mode"):
        Settings(auth_mode=mode)  # type: ignore[arg-type]


def test_leeway_is_bounded() -> None:
    with pytest.raises(ValidationError, match="auth_leeway_seconds"):
        Settings(auth_leeway_seconds=-1)
    with pytest.raises(ValidationError, match="auth_leeway_seconds"):
        Settings(auth_leeway_seconds=301)
