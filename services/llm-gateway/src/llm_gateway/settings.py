"""Process configuration of the llm-gateway service: ``CW_*`` variables on top of py-common's.

The residency policy (``llm_residency``, ``CW_LLM_RESIDENCY``) has one source: that variable, read
once at start. Two ways of writing it that would leave the gateway on another policy than the one
meant are refused, so the gateway does not start and ``cw-mvp check-config`` reports them:

- ``CW_LLM_RESIDENCY=`` with nothing after it. Every other setting treats an empty value as unset
  (``env_ignore_empty``), which here would mean ``global`` and send text out of India where
  someone meant to set the policy; so it is refused instead, in the environment and in ``.env``.
- ``CW_FLAG_LLM_GATEWAY_RESIDENCY``, the flag provider's override of the registry entry
  ``llm_gateway.residency``. That entry is the setting's record (owner, default, expiry,
  removal), kept because every switch-shaped setting is registered; nothing reads the flag, so the
  override would change what ``flag_value`` answers and nothing the gateway does.
"""

from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any, Final, Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    DotEnvSettingsSource,
    EnvSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from py_common.settings import Settings

Provider = Literal["fake", "vercel"]
Ledger = Literal["memory", "postgres"]
Residency = Literal["global", "india_only"]
RESIDENCY_ENV: Final = "CW_LLM_RESIDENCY"
RESIDENCY_FLAG_ENV: Final = "CW_FLAG_LLM_GATEWAY_RESIDENCY"
"""``CW_FLAG_<NAME>`` of the registry entry ``llm_gateway.residency``, which the gateway refuses."""


def default_registry_path() -> Path:
    """``services/llm-gateway/prompts/registry.toml`` in a checkout (editable install).

    The wheel inside the Docker image does not carry ``prompts/``: the Dockerfile copies the
    directory to ``/app/prompts`` and sets ``CW_LLM_PROMPT_REGISTRY_PATH`` instead.
    """
    return Path(__file__).resolve().parents[2] / "prompts" / "registry.toml"


class GatewaySettings(Settings):
    """Provider, residency, ledger, budgets, cache, breaker, prompt registry and tracing settings.

    Route overrides come from ``CW_LLM_ROUTES__<FEATURE>=primary[,fallback]``, one variable per
    feature: shell-safe in ``.env`` (the Makefile sources it), one line per concern in compose
    and Helm, and parsed by pydantic-settings without a custom source.
    """

    model_config = SettingsConfigDict(env_nested_delimiter="__")

    llm_provider: Provider = "fake"
    llm_ledger: Ledger = "memory"
    # Where a call may send text (llm_gateway.domain.residency, ADR-020): global lets the masked
    # text reach models outside India; india_only refuses every call to a real model, since no
    # routed model runs inference in India. fake/... models answer in process under both.
    llm_residency: Residency = "global"

    ai_gateway_api_key: SecretStr | None = None
    ai_gateway_base_url: str = "https://ai-gateway.vercel.sh/v1"
    ai_gateway_zero_data_retention: bool = True
    # SDK retries sleep for the server's Retry-After (up to 120 s) inside the request; the use
    # case's fallback model and the breaker are the retry policy, so the default is none.
    ai_gateway_max_retries: int = Field(default=0, ge=0)
    # Sends dimensions=512 with every embedding call. Turn it off only for a retrieval model
    # that has no such parameter and already returns 512 dimensions; every vector is checked.
    llm_embedding_dimensions_param: bool = True

    llm_usd_inr: Decimal = Field(default=Decimal("88.00"), gt=0)
    # Budgets are ceilings, so zero is not a budget; the domain refuses it and so does this.
    llm_tenant_monthly_budget_inr: Decimal = Field(default=Decimal("1500"), gt=0)
    llm_feature_monthly_budget_inr: Decimal = Field(default=Decimal("20000"), gt=0)
    llm_budget_alarm_ratio: float = Field(default=0.8, gt=0, le=1)

    # A ttl of zero turns the cache off.
    llm_cache_ttl_seconds: int = Field(default=3600, ge=0)
    llm_cache_max_entries: int = Field(default=1000, ge=1)
    llm_breaker_threshold: int = Field(default=3, ge=1)
    llm_breaker_open_seconds: float = Field(default=60.0, gt=0)

    llm_allow_unregistered_prompts: bool = False
    llm_prompt_registry_path: Path = Field(default_factory=default_registry_path)
    llm_routes: dict[str, str] = Field(default_factory=dict)

    langfuse_host: str | None = None
    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """The usual sources, with the residency as written ahead of the environment's: a value
        given to the constructor still wins."""
        as_written = _ResidencyAsWritten(settings_cls, dotenv_settings)
        return init_settings, as_written, env_settings, dotenv_settings, file_secret_settings

    @field_validator("llm_residency", mode="before")
    @classmethod
    def _refuse_the_residency_as_written(cls, value: object) -> object:
        if isinstance(value, _Refused):
            raise ValueError(value.reason)
        return value

    @field_validator("llm_routes")
    @classmethod
    def _normalise_routes(cls, routes: dict[str, str]) -> dict[str, str]:
        normalised: dict[str, str] = {}
        for feature, models in routes.items():
            ids = [model.strip() for model in models.split(",")]
            if not 1 <= len(ids) <= 2 or not all(ids):
                raise ValueError(
                    f"llm_routes[{feature!r}] must be 'primary' or 'primary,fallback', "
                    f"got {models!r}"
                )
            normalised[feature.strip().lower()] = ",".join(ids)
        return normalised

    @model_validator(mode="after")
    def _require_provider_credentials(self) -> Self:
        if self.llm_provider == "vercel" and self.ai_gateway_api_key is None:
            raise ValueError("CW_AI_GATEWAY_API_KEY is required when CW_LLM_PROVIDER=vercel")
        return self


class _Refused:
    """The residency as written cannot be read as a policy, for ``reason``."""

    def __init__(self, reason: str) -> None:
        self.reason = reason


class _ResidencyAsWritten(PydanticBaseSettingsSource):
    """``CW_LLM_RESIDENCY`` and ``CW_FLAG_LLM_GATEWAY_RESIDENCY`` as written: the process
    environment over the ``.env`` files the settings read, empty values included (the other
    sources drop those), names matched without regard to case as the settings match them. It
    gives ``llm_residency`` no value unless one of them is written in a way the gateway refuses;
    then the refusal stands in for the value, and validation reports it."""

    def __init__(
        self, settings_cls: type[BaseSettings], dotenv_settings: PydanticBaseSettingsSource
    ) -> None:
        super().__init__(settings_cls)
        env_file = getattr(dotenv_settings, "env_file", None)
        files = DotEnvSettingsSource(settings_cls, env_file=env_file, env_ignore_empty=False)
        process = EnvSettingsSource(settings_cls, env_ignore_empty=False)
        self._written: Mapping[str, str | None] = {**files.env_vars, **process.env_vars}

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        reasons: list[str] = []
        residency = self._written.get(RESIDENCY_ENV.lower())
        if residency is not None and not residency.strip():
            reasons.append(
                f"{RESIDENCY_ENV} is set but empty: set global or india_only, or unset it for the "
                "default, global"
            )
        override = self._written.get(RESIDENCY_FLAG_ENV.lower())
        if override is not None and override.strip():
            reasons.append(
                f"{RESIDENCY_FLAG_ENV} is set, and nothing reads it: the policy is "
                f"{RESIDENCY_ENV} alone (the registry entry llm_gateway.residency is its record); "
                f"unset {RESIDENCY_FLAG_ENV} and set {RESIDENCY_ENV}"
            )
        return {"llm_residency": _Refused("; ".join(reasons))} if reasons else {}
