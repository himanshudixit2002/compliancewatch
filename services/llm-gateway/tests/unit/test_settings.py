"""GatewaySettings: the parent's ``CW_`` prefix and ``.env`` survive the nested delimiter."""

import os
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from llm_gateway.settings import GatewaySettings, default_registry_path


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for key in list(os.environ):
        if key.startswith("CW_"):
            monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)  # no repo .env in reach


def test_defaults() -> None:
    settings = GatewaySettings(service_name="llm-gateway")
    assert settings.service_name == "llm-gateway"
    assert settings.llm_provider == "fake"
    assert settings.llm_ledger == "memory"
    assert settings.ai_gateway_api_key is None
    assert settings.ai_gateway_base_url == "https://ai-gateway.vercel.sh/v1"
    assert settings.ai_gateway_zero_data_retention is True
    assert settings.ai_gateway_max_retries == 0
    assert settings.llm_embedding_dimensions_param is True
    assert settings.llm_usd_inr == Decimal("88.00")
    assert settings.llm_tenant_monthly_budget_inr == Decimal("1500")
    assert settings.llm_feature_monthly_budget_inr == Decimal("20000")
    assert settings.llm_budget_alarm_ratio == 0.8
    assert settings.llm_cache_ttl_seconds == 3600
    assert settings.llm_cache_max_entries == 1000
    assert settings.llm_breaker_threshold == 3
    assert settings.llm_breaker_open_seconds == 60.0
    assert settings.llm_allow_unregistered_prompts is False
    assert settings.llm_prompt_registry_path == default_registry_path()
    assert settings.llm_routes == {}
    assert settings.langfuse_host is None
    assert settings.langfuse_public_key is None
    assert settings.langfuse_secret_key is None


def test_default_registry_path_points_at_the_checked_in_file() -> None:
    path = default_registry_path()
    assert path.parts[-3:] == ("llm-gateway", "prompts", "registry.toml")
    assert path.is_file()


def test_env_prefix_still_applies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CW_LLM_LEDGER", "postgres")
    monkeypatch.setenv("CW_LLM_USD_INR", "90.5")
    monkeypatch.setenv("CW_LLM_CACHE_TTL_SECONDS", "0")
    monkeypatch.setenv("CW_LOG_LEVEL", "debug")
    monkeypatch.setenv("CW_LLM_EMBEDDING_DIMENSIONS_PARAM", "false")
    settings = GatewaySettings()
    assert settings.llm_embedding_dimensions_param is False
    assert settings.llm_ledger == "postgres"
    assert settings.llm_usd_inr == Decimal("90.5")
    assert settings.llm_cache_ttl_seconds == 0
    assert settings.log_level == "DEBUG"


def test_unprefixed_variables_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_LEDGER", "postgres")
    monkeypatch.setenv("LLM_ROUTES__SMOKE", "fake/other")
    settings = GatewaySettings()
    assert settings.llm_ledger == "memory"
    assert settings.llm_routes == {}


def test_dotenv_is_still_read(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "CW_LLM_USD_INR=91\nCW_LLM_ROUTES__QA=fake/echo\nCW_LLM_BREAKER_THRESHOLD=5\n",
        encoding="utf-8",
    )
    settings = GatewaySettings()
    assert settings.llm_usd_inr == Decimal("91")
    assert settings.llm_routes == {"qa": "fake/echo"}
    assert settings.llm_breaker_threshold == 5


def test_init_values_beat_the_environment_and_dotenv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CW_LLM_USD_INR", "90")
    (tmp_path / ".env").write_text("CW_LLM_LEDGER=postgres\n", encoding="utf-8")
    settings = GatewaySettings(llm_usd_inr=Decimal("1"), llm_ledger="memory")
    assert settings.llm_usd_inr == Decimal("1")
    assert settings.llm_ledger == "memory"


def test_env_file_none_disables_dotenv(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("CW_LLM_LEDGER=postgres\n", encoding="utf-8")
    assert GatewaySettings(_env_file=None).llm_ledger == "memory"


def test_route_overrides_come_from_nested_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CW_LLM_ROUTES__SMOKE", "fake/echo")
    monkeypatch.setenv("CW_LLM_ROUTES__QA", " alibaba/qwen3.7-flash , zai/glm-4.7-flash ")
    settings = GatewaySettings()
    assert settings.llm_routes == {
        "smoke": "fake/echo",
        "qa": "alibaba/qwen3.7-flash,zai/glm-4.7-flash",
    }


def test_route_override_keys_are_normalised() -> None:
    settings = GatewaySettings(llm_routes={" Smoke ": "fake/echo, fake/other"})
    assert settings.llm_routes == {"smoke": "fake/echo,fake/other"}


@pytest.mark.parametrize("text", ["", " ", ",", "a/b,", ",a/b", "a/b,c/d,e/f", " , "])
def test_bad_route_strings_are_refused(text: str) -> None:
    with pytest.raises(ValidationError, match="primary,fallback"):
        GatewaySettings(llm_routes={"smoke": text})


def test_vercel_requires_the_gateway_key() -> None:
    with pytest.raises(ValidationError, match="CW_AI_GATEWAY_API_KEY"):
        GatewaySettings(llm_provider="vercel")


def test_vercel_with_a_key_is_accepted_and_the_key_is_hidden() -> None:
    settings = GatewaySettings(llm_provider="vercel", ai_gateway_api_key=SecretStr("k-1"))
    assert settings.llm_provider == "vercel"
    assert settings.ai_gateway_api_key is not None
    assert settings.ai_gateway_api_key.get_secret_value() == "k-1"
    assert "k-1" not in repr(settings)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("llm_tenant_monthly_budget_inr", Decimal("0")),
        ("llm_feature_monthly_budget_inr", Decimal("-1")),
        ("llm_usd_inr", Decimal("0")),
        ("llm_budget_alarm_ratio", 0),
        ("llm_budget_alarm_ratio", 1.5),
        ("llm_cache_ttl_seconds", -1),
        ("llm_cache_max_entries", 0),
        ("llm_breaker_threshold", 0),
        ("llm_breaker_open_seconds", 0),
        ("ai_gateway_max_retries", -1),
    ],
)
def test_out_of_range_numbers_are_refused(field: str, value: Any) -> None:
    kwargs: dict[str, Any] = {field: value}
    with pytest.raises(ValidationError):
        GatewaySettings(**kwargs)


def test_a_zero_cache_ttl_is_allowed() -> None:
    assert GatewaySettings(llm_cache_ttl_seconds=0).llm_cache_ttl_seconds == 0


def test_settings_are_frozen() -> None:
    settings = GatewaySettings()
    with pytest.raises(ValidationError):
        settings.llm_provider = "vercel"  # type: ignore[misc]
