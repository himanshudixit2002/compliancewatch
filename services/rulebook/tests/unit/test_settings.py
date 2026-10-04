"""The rulebook's own settings: the store, the two tokens, the publish flag and where a synthetic
approval is accepted."""

import pytest

from py_common.settings import Environment
from rulebook.settings import RulebookSettings
from rulebook.testing import rulebook_settings


def test_publishing_is_off_by_default() -> None:
    settings = RulebookSettings(_env_file=None, service_name="rulebook")
    assert settings.rulebook_publish_enabled is False
    assert settings.rulebook_store == "postgres"
    assert settings.rulebook_write_token is None
    assert settings.rulebook_review_token is None
    assert rulebook_settings().rulebook_publish_enabled is False


def test_the_flag_reads_its_environment_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CW_RULEBOOK_PUBLISH_ENABLED", "true")
    settings = RulebookSettings(_env_file=None, service_name="rulebook")
    assert settings.rulebook_publish_enabled is True


def test_the_review_token_reads_its_environment_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CW_RULEBOOK_REVIEW_TOKEN", "analysts")
    settings = RulebookSettings(_env_file=None, service_name="rulebook")
    assert settings.rulebook_review_token is not None
    assert settings.rulebook_review_token.get_secret_value() == "analysts"


@pytest.mark.parametrize(("env", "allowed"), [("local", True), ("test", True), ("staging", False)])
def test_synthetic_approvals_are_allowed_in_local_and_test_only(
    env: Environment, allowed: bool
) -> None:
    settings = RulebookSettings(_env_file=None, service_name="rulebook", env=env)
    assert settings.synthetic_approvals_allowed is allowed
    prod = RulebookSettings(_env_file=None, service_name="rulebook", env="prod", auth_mode="token")
    assert prod.synthetic_approvals_allowed is False
