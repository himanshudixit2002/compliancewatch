"""Process configuration of the llm-gateway service: ``CW_*`` variables on top of py-common's."""

from decimal import Decimal
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import SettingsConfigDict

from py_common.settings import Settings

Provider = Literal["fake", "vercel"]
Ledger = Literal["memory", "postgres"]


def default_registry_path() -> Path:
    """``services/llm-gateway/prompts/registry.toml`` in a checkout (editable install).

    The wheel inside the Docker image does not carry ``prompts/``: the Dockerfile copies the
    directory to ``/app/prompts`` and sets ``CW_LLM_PROMPT_REGISTRY_PATH`` instead.
    """
    return Path(__file__).resolve().parents[2] / "prompts" / "registry.toml"


class GatewaySettings(Settings):
    """Provider, ledger, budgets, cache, breaker, prompt registry and tracing settings.

    Route overrides come from ``CW_LLM_ROUTES__<FEATURE>=primary[,fallback]``, one variable per
    feature: shell-safe in ``.env`` (the Makefile sources it), one line per concern in compose
    and Helm, and parsed by pydantic-settings without a custom source.
    """

    model_config = SettingsConfigDict(env_nested_delimiter="__")

    llm_provider: Provider = "fake"
    llm_ledger: Ledger = "memory"

    ai_gateway_api_key: SecretStr | None = None
    ai_gateway_base_url: str = "https://ai-gateway.vercel.sh/v1"
    ai_gateway_zero_data_retention: bool = True
    # SDK retries sleep for the server's Retry-After (up to 120 s) inside the request; the use
    # case's fallback model and the breaker are the retry policy, so the default is none.
    ai_gateway_max_retries: int = Field(default=0, ge=0)

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
