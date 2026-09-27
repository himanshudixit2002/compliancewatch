import os
from pathlib import Path

import pytest

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


def test_env_prefix_and_level_normalisation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CW_LOG_LEVEL", "debug")
    monkeypatch.setenv("CW_ENV", "prod")
    monkeypatch.setenv("CW_DB_SCHEMA", "obligation")
    settings = Settings()
    assert settings.log_level == "DEBUG"
    assert settings.env == "prod"
    assert settings.db_schema == "obligation"


def test_service_name_is_passed_by_the_composition_root() -> None:
    assert Settings(service_name="obligation").service_name == "obligation"


def test_unprefixed_variables_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "error")
    assert Settings().log_level == "INFO"
