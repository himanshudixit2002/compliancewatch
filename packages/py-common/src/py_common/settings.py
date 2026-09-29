"""Process configuration for every service.

Values come from ``CW_*`` environment variables; a local ``.env`` is honoured and never committed.
``service_name`` is passed by the composition root, not read from the environment.

``flags_provider`` picks where ``py_common.flags`` reads feature flags: ``env`` (the default) from
the environment, ``unleash`` from an Unleash server at ``unleash_url`` with the client token
``unleash_api_token`` (``CW_FLAGS_PROVIDER``; owner platform; it becomes plain configuration once
a hosted Unleash runs in staging and production).

``auth_mode`` says how a request proves who it comes from (``CW_AUTH_MODE``; owner platform):

- ``header`` (the default): no token is read; the tenant comes from ``x-tenant-id`` as before;
- ``dual``: a bearer token from the identity service is verified and enforced when a request
  carries one, and a request without one is served as in ``header`` mode;
- ``token``: every request needs a bearer token.

Production (``CW_ENV=prod``) refuses anything but ``token``. Tokens are ES256 JWTs issued by
``auth_issuer`` for ``auth_audience``; their keys come from ``auth_jwks_json`` when it is set (an
inline key set, for tests and static configuration) and otherwise from ``auth_jwks_url``, cached
for an hour. ``auth_leeway_seconds`` allows for clock skew on the time claims.

``env_files`` are the ``.env`` files the settings were read from: ``.env`` by default, none when
they were built with ``_env_file=None`` (tests, the demo, the evals). ``py_common.flags`` reads
flags from the same files, so settings kept away from a developer's ``.env`` keep their flags
away from it too.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Self, cast

from pydantic import Field, PrivateAttr, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "staging", "prod"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
FlagsProvider = Literal["env", "unleash"]
AuthMode = Literal["header", "dual", "token"]


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
    auth_mode: AuthMode = "header"
    auth_issuer: str = "urn:compliancewatch:identity"
    auth_audience: str = "compliancewatch"
    auth_jwks_url: str = "http://localhost:8001/v1/identity/.well-known/jwks.json"
    auth_jwks_json: SecretStr | None = None
    auth_leeway_seconds: int = Field(default=30, ge=0, le=300)
    _env_files: tuple[Path, ...] = PrivateAttr(default=())

    if not TYPE_CHECKING:
        # Hidden from mypy so the pydantic plugin still types ``Settings(...)`` by its fields.
        def __init__(self, **values: Any) -> None:
            # pydantic-settings reads ``_env_file`` and forgets it; keep which files it read.
            chosen = values.get("_env_file", type(self).model_config.get("env_file"))
            super().__init__(**values)
            self._env_files = _paths(chosen)

    @property
    def env_files(self) -> tuple[Path, ...]:
        """The ``.env`` files these settings were read from, later ones winning; empty when
        they were built with ``_env_file=None``."""
        return self._env_files

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

    @model_validator(mode="after")
    def _require_tokens_in_production(self) -> Self:
        if self.env == "prod" and self.auth_mode != "token":
            raise ValueError(
                f"CW_ENV=prod needs CW_AUTH_MODE=token, got {self.auth_mode}: production serves "
                "no request without a verified access token"
            )
        return self


def _paths(env_file: object) -> tuple[Path, ...]:
    """``_env_file`` as pydantic-settings takes it (None, a path, or a sequence of paths), which
    has refused any other value by the time this runs."""
    if env_file is None:
        return ()
    if isinstance(env_file, str | Path):
        return (Path(env_file),)
    return tuple(Path(path) for path in cast(Sequence[str | Path], env_file))
