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
- ``token``: every route that reads the caller (tenant, service-to-service, analyst and admin
  routes) needs a bearer token. Probes, sign-in and the reads that are the same for every caller
  stay open; ``packages/py-common/README.md`` lists them.

Production (``CW_ENV=prod``) refuses anything but ``token``. Tokens are ES256 JWTs issued by
``auth_issuer`` for ``auth_audience``; their keys come from ``auth_jwks_json`` when it is set (an
inline key set, for tests and static configuration) and otherwise from ``auth_jwks_url``, cached
for an hour. ``auth_leeway_seconds`` allows for clock skew on the time claims.

``service_client_id`` and ``service_client_secret`` are this process's service client at the
identity service (``identity_url``). With a secret set, ``py_common.auth.service_tokens`` gets
access tokens with them and every outgoing HTTP client sends one; without it no token is sent.
An empty id stands for ``service_name``, so a process that only migrates, relays or seeds starts
whatever secret a shared ``.env`` holds.

``env_files`` are the ``.env`` files the settings were read from: ``.env`` by default, none when
they were built with ``_env_file=None`` (tests, the demo, the evals). ``py_common.flags`` reads
flags from the same files, so settings kept away from a developer's ``.env`` keep their flags
away from it too.

Managed brokers and collectors need credentials the dev stack does without; every one of them is
empty by default, so the compose Redpanda, Temporal and collector work as before:

- Kafka: ``kafka_security_protocol`` (``PLAINTEXT``, ``SSL``, ``SASL_PLAINTEXT`` or
  ``SASL_SSL``). A ``SASL_*`` protocol needs ``kafka_sasl_mechanism`` (``PLAIN``,
  ``SCRAM-SHA-256`` or ``SCRAM-SHA-512``), ``kafka_sasl_username`` and ``kafka_sasl_password``;
  ``SSL`` and ``SASL_SSL`` verify the broker against ``kafka_ssl_cafile``, or the system's
  certificate authorities when it is empty. ``py_common.kafka.KafkaClientConfig`` turns them
  into the client arguments every producer, consumer and admin client takes.
- Temporal: ``temporal_api_key`` (Temporal Cloud's API keys), or a client certificate
  ``temporal_tls_cert`` with its private key ``temporal_tls_key``, both PEM text so they fit a
  secret store; not both. ``temporal_tls`` turns TLS on or off; left empty it is on whenever a
  credential is set.
- OpenTelemetry: ``otel_protocol`` picks the OTLP transport (``grpc``, or ``http/protobuf`` for
  gateways such as Grafana Cloud's, which get ``<endpoint>/v1/traces`` and
  ``<endpoint>/v1/metrics``); ``otel_headers`` are the headers every export sends, in the
  ``OTEL_EXPORTER_OTLP_HEADERS`` form ``key=value,key2=value2`` with URL-encoded values, such as
  ``Authorization=Basic%20<token>``.

``with_search_path(url, schema)`` is a database URL whose connections put ``schema`` first on
their ``search_path``, the way one database serves every service schema.

``db_pool_size`` and ``db_max_overflow`` size the connection pool of each engine
``py_common.database.create_pooled_engine`` builds: that many connections stay open, and up to
the overflow more are opened under load. They are small because a process that hosts several
services holds one pool per engine of each, and a managed Postgres caps the connections of the
whole deployment.
"""

import re
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Self, cast
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

from pydantic import Field, PrivateAttr, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "staging", "prod"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
FlagsProvider = Literal["env", "unleash"]
AuthMode = Literal["header", "dual", "token"]
KafkaSecurityProtocol = Literal["PLAINTEXT", "SSL", "SASL_PLAINTEXT", "SASL_SSL"]
KafkaSaslMechanism = Literal["PLAIN", "SCRAM-SHA-256", "SCRAM-SHA-512"]
OtelProtocol = Literal["grpc", "http/protobuf"]

SCHEMA_NAME = re.compile(r"[a-z_][a-z0-9_]{0,62}")
"""A schema ``with_search_path`` accepts: a plain lower-case Postgres identifier."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CW_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        frozen=True,
        # A refused configuration is reported without the values, which include credentials.
        hide_input_in_errors=True,
    )

    service_name: str = "compliancewatch"
    env: Environment = "local"
    log_level: LogLevel = "INFO"
    log_json: bool = True
    database_url: str = "postgresql+psycopg://cw:cw@localhost:5432/compliancewatch"
    db_schema: str | None = None
    db_pool_size: int = Field(default=3, ge=1, le=100)
    db_max_overflow: int = Field(default=2, ge=0, le=100)
    kafka_bootstrap: str = "localhost:19092"
    kafka_security_protocol: KafkaSecurityProtocol = "PLAINTEXT"
    kafka_sasl_mechanism: KafkaSaslMechanism | None = None
    kafka_sasl_username: str | None = None
    kafka_sasl_password: SecretStr | None = None
    kafka_ssl_cafile: str | None = None
    redis_url: str = "redis://localhost:6379/0"
    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_api_key: SecretStr | None = None
    temporal_tls: bool | None = None
    temporal_tls_cert: SecretStr | None = None
    temporal_tls_key: SecretStr | None = None
    otel_endpoint: str | None = None
    otel_protocol: OtelProtocol = "grpc"
    otel_headers: SecretStr | None = None
    flags_provider: FlagsProvider = "env"
    unleash_url: str | None = None
    unleash_api_token: SecretStr | None = None
    auth_mode: AuthMode = "header"
    auth_issuer: str = "urn:compliancewatch:identity"
    auth_audience: str = "compliancewatch"
    auth_jwks_url: str = "http://localhost:8001/v1/identity/.well-known/jwks.json"
    auth_jwks_json: SecretStr | None = None
    auth_leeway_seconds: int = Field(default=30, ge=0, le=300)
    identity_url: str = "http://localhost:8001"
    service_client_id: str = ""
    service_client_secret: SecretStr | None = None
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

    @property
    def temporal_tls_enabled(self) -> bool:
        """Whether the Temporal client uses TLS: ``temporal_tls`` when it is set, otherwise
        whenever an API key or a client certificate is."""
        if self.temporal_tls is not None:
            return self.temporal_tls
        return _present(self.temporal_api_key) or _present(self.temporal_tls_cert)

    @property
    def otel_header_map(self) -> dict[str, str]:
        """``otel_headers`` decoded, with lower-case names (gRPC metadata needs them)."""
        return parse_otel_headers(_secret(self.otel_headers))

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
    def _require_kafka_credentials(self) -> Self:
        if self.kafka_security_protocol.startswith("SASL_"):
            missing = [
                variable
                for variable, value in (
                    ("CW_KAFKA_SASL_MECHANISM", self.kafka_sasl_mechanism),
                    ("CW_KAFKA_SASL_USERNAME", self.kafka_sasl_username),
                    ("CW_KAFKA_SASL_PASSWORD", _secret(self.kafka_sasl_password)),
                )
                if not value
            ]
            if missing:
                raise ValueError(
                    f"CW_KAFKA_SECURITY_PROTOCOL={self.kafka_security_protocol} needs "
                    f"{', '.join(missing)}"
                )
        return self

    @model_validator(mode="after")
    def _require_one_temporal_credential(self) -> Self:
        cert, key = _present(self.temporal_tls_cert), _present(self.temporal_tls_key)
        if cert != key:
            raise ValueError(
                "CW_TEMPORAL_TLS_CERT and CW_TEMPORAL_TLS_KEY go together: a client certificate "
                "needs its private key"
            )
        if cert and _present(self.temporal_api_key):
            raise ValueError(
                "CW_TEMPORAL_API_KEY and CW_TEMPORAL_TLS_CERT are two ways to authenticate to "
                "Temporal; set one"
            )
        if cert and self.temporal_tls is False:
            raise ValueError("CW_TEMPORAL_TLS=false leaves the client certificate unused")
        return self

    @model_validator(mode="after")
    def _require_readable_otel_headers(self) -> Self:
        _ = self.otel_header_map
        return self

    @model_validator(mode="after")
    def _require_tokens_in_production(self) -> Self:
        if self.env == "prod" and self.auth_mode != "token":
            raise ValueError(
                f"CW_ENV=prod needs CW_AUTH_MODE=token, got {self.auth_mode}: production serves "
                "no request without a verified access token"
            )
        return self


def parse_otel_headers(raw: str) -> dict[str, str]:
    """Headers in the ``OTEL_EXPORTER_OTLP_HEADERS`` form: ``key=value`` pairs separated by
    commas, URL-encoded. Names are lower-cased. A pair without ``=`` or without a name raises
    ``ValueError`` naming its position only, since the values are credentials."""
    headers: dict[str, str] = {}
    for position, pair in enumerate(raw.split(","), start=1):
        if not pair.strip():
            continue
        name, separator, value = pair.partition("=")
        name = unquote(name.strip()).lower()
        if not separator or not name:
            raise ValueError(
                f"CW_OTEL_HEADERS pair {position} is not key=value (the form of "
                "OTEL_EXPORTER_OTLP_HEADERS)"
            )
        headers[name] = unquote(value.strip())
    return headers


def with_search_path(url: str, schema: str) -> str:
    """``url`` with ``options=-csearch_path=<schema>,public``, so every connection it opens
    finds the service's tables first and the shared extensions in ``public`` after them.

    A ``search_path`` already in ``options`` is replaced; other options and every other query
    parameter are kept. Some connection poolers refuse startup options; connect to the database
    directly then.
    """
    if not SCHEMA_NAME.fullmatch(schema):
        raise ValueError(f"schema must be a lower-case Postgres identifier, got {schema!r}")
    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    options = [value for key, value in query if key == "options"]
    kept = [option for option in _without_search_path(" ".join(options).split()) if option.strip()]
    kept.append(f"-csearch_path={schema},public")
    rest = [(key, value) for key, value in query if key != "options"]
    return urlunsplit(parts._replace(query=urlencode([*rest, ("options", " ".join(kept))])))


def _without_search_path(options: Sequence[str]) -> list[str]:
    """libpq ``options`` arguments without any that set ``search_path`` (``-c search_path=x``,
    ``-csearch_path=x`` or ``--search_path=x``)."""
    kept: list[str] = []
    skip_next = False
    for index, option in enumerate(options):
        if skip_next:
            skip_next = False
            continue
        following = options[index + 1] if index + 1 < len(options) else ""
        if option == "-c" and _sets_search_path(following):
            skip_next = True
            continue
        if option.startswith("-c") and _sets_search_path(option[2:]):
            continue
        if option.startswith("--") and _sets_search_path(option[2:]):
            continue
        kept.append(option)
    return kept


def _sets_search_path(assignment: str) -> bool:
    return assignment.replace("-", "_").lower().startswith("search_path=")


def _present(secret: SecretStr | None) -> bool:
    return bool(_secret(secret))


def _secret(secret: SecretStr | None) -> str:
    return "" if secret is None else secret.get_secret_value()


def _paths(env_file: object) -> tuple[Path, ...]:
    """``_env_file`` as pydantic-settings takes it (None, a path, or a sequence of paths), which
    has refused any other value by the time this runs."""
    if env_file is None:
        return ()
    if isinstance(env_file, str | Path):
        return (Path(env_file),)
    return tuple(Path(path) for path in cast(Sequence[str | Path], env_file))
