"""The qa service's own settings: the KAG flag and its tenants, the upstream URLs, timeouts."""

from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from qa.settings import QaSettings

TENANT_A = UUID("00000000-0000-0000-0000-00000000000a")
TENANT_B = UUID("00000000-0000-0000-0000-00000000000b")


def settings() -> QaSettings:
    return QaSettings(_env_file=None, service_name="qa")


def test_the_flag_is_off_by_default_and_targets_every_tenant() -> None:
    loaded = settings()
    assert loaded.qa_kag_enabled is False
    assert loaded.qa_kag_tenants == frozenset()
    assert loaded.qa_prompts_dir is None
    assert (loaded.qa_http_timeout_seconds, loaded.qa_llm_timeout_seconds) == (5.0, 10.0)
    assert loaded.rulebook_url == "http://localhost:8003"
    assert loaded.profile_url == "http://localhost:8002"
    assert loaded.obligation_url == "http://localhost:8005"
    assert loaded.llm_gateway_url == "http://localhost:8008"


def test_the_flag_and_tenants_read_their_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CW_QA_KAG_ENABLED", "true")
    monkeypatch.setenv("CW_QA_KAG_TENANTS", f" {TENANT_A}, {TENANT_B} ,")
    monkeypatch.setenv("CW_QA_PROMPTS_DIR", "/app/prompts")
    monkeypatch.setenv("CW_PROFILE_URL", "http://profile.test")
    loaded = settings()
    assert loaded.qa_kag_enabled is True
    assert loaded.qa_kag_tenants == frozenset({TENANT_A, TENANT_B})
    assert loaded.qa_prompts_dir == Path("/app/prompts")
    assert loaded.profile_url == "http://profile.test"


def test_an_empty_tenant_list_means_every_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CW_QA_KAG_TENANTS", "")
    assert settings().qa_kag_tenants == frozenset()


def test_a_tenant_that_is_not_a_uuid_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CW_QA_KAG_TENANTS", "acme")
    with pytest.raises(ValidationError):
        settings()


def test_timeouts_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        QaSettings(_env_file=None, qa_http_timeout_seconds=0)
