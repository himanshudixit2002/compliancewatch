"""Process configuration for every service.

Values come from ``CW_*`` environment variables; a local ``.env`` is honoured and never committed.
``service_name`` is passed by the composition root, not read from the environment.

``flags_provider`` picks where ``py_common.flags`` reads feature flags: ``env`` (the default) from
the environment, ``unleash`` from an Unleash server at ``unleash_url`` with the client token
``unleash_api_token`` (``CW_FLAGS_PROVIDER``; owner platform; it becomes plain configuration once
a hosted Unleash runs in staging and production).
"""

from typing import Literal, Self

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "staging", "prod"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
FlagsProvider = Literal["env", "unleash"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CW_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        frozen=True,
    )

    service_name: str = "compliancewatch"
    env: Environment = "local"
    log_level: LogLevel = "INFO"
    log_json: bool = True
    database_url: str = "postgresql+psycopg://cw:cw@localhost:5432/compliancewatch"
    db_schema: str | None = None
    kafka_bootstrap: str = "localhost:19092"
    redis_url: str = "redis://localhost:6379/0"
    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    otel_endpoint: str | None = None
    flags_provider: FlagsProvider = "env"
    unleash_url: str | None = None
    unleash_api_token: SecretStr | None = None

    @field_validator("log_level", mode="before")
    @classmethod
    def _uppercase_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _require_unleash_connection(self) -> Self:
        if self.flags_provider == "unleash" and (
            not self.unleash_url or self.unleash_api_token is None
        ):
            raise ValueError(
                "CW_FLAGS_PROVIDER=unleash needs CW_UNLEASH_URL and CW_UNLEASH_API_TOKEN"
            )
        return self
