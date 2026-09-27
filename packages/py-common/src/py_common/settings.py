"""Process configuration for every service.

Values come from ``CW_*`` environment variables; a local ``.env`` is honoured and never committed.
``service_name`` is passed by the composition root, not read from the environment.
"""

from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "staging", "prod"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


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
    otel_endpoint: str | None = None

    @field_validator("log_level", mode="before")
    @classmethod
    def _uppercase_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value
