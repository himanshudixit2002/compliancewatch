"""The rulebook's own settings: the store, the write token and the publish flag."""

import pytest

from rulebook.settings import RulebookSettings
from rulebook.testing import rulebook_settings


def test_publishing_is_off_by_default() -> None:
    settings = RulebookSettings(_env_file=None, service_name="rulebook")
    assert settings.rulebook_publish_enabled is False
    assert settings.rulebook_store == "postgres"
    assert settings.rulebook_write_token is None
    assert rulebook_settings().rulebook_publish_enabled is False


def test_the_flag_reads_its_environment_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CW_RULEBOOK_PUBLISH_ENABLED", "true")
    settings = RulebookSettings(_env_file=None, service_name="rulebook")
    assert settings.rulebook_publish_enabled is True
