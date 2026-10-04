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


def test_seed_on_start_is_off_by_default_and_reads_its_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert rulebook_settings().rulebook_seed_on_start is False
    monkeypatch.setenv("CW_RULEBOOK_SEED_ON_START", "true")
    monkeypatch.setenv("CW_RULEBOOK_STORE", "memory")
    settings = RulebookSettings(_env_file=None, service_name="rulebook")
    assert settings.rulebook_seed_on_start is True


@pytest.mark.parametrize("env", ["local", "test"])
def test_seed_on_start_is_honoured_in_local_and_test(env: Environment) -> None:
    settings = rulebook_settings(env=env, rulebook_seed_on_start=True)
    assert settings.rulebook_seed_on_start is True


def test_seed_on_start_is_refused_outside_local_and_test() -> None:
    with pytest.raises(ValueError, match="SEED_ON_START is refused with CW_ENV=staging"):
        rulebook_settings(env="staging", rulebook_seed_on_start=True)
    with pytest.raises(ValueError, match="refused with CW_ENV=prod"):
        rulebook_settings(env="prod", auth_mode="token", rulebook_seed_on_start=True)


def test_seed_on_start_is_refused_with_the_postgres_store() -> None:
    with pytest.raises(ValueError, match="fills the memory store"):
        rulebook_settings(rulebook_store="postgres", rulebook_seed_on_start=True)
