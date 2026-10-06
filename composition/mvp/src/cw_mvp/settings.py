"""Process configuration of the composition root: ``CW_*`` on top of py-common's.

The shared settings (the database, Kafka, Temporal, OpenTelemetry, auth mode and service client)
are read once here and handed to every service; each service still reads its own ``CW_*``
settings (stores, providers, flags) from the environment (``cw_mvp.registry.service_settings``).

The app process answers on two listeners, both on ``mvp_host`` (``::``, which takes IPv4 too):

- ``mvp_public_port`` (8000) is the one the edge reaches. It serves only the routes
  ``cw_mvp.exposure`` classes public, and the admin ones when ``CW_AUTH_MODE=token``.
- ``mvp_internal_port`` (8080) is reachable only on the private network and serves every route.
  The services this process hosts call each other at ``mvp_internal_url``, which the worker
  process overrides with ``--internal-url``.

``mvp_forwarded_allow_ips`` are the proxies whose ``X-Forwarded-*`` headers are trusted.
``mvp_thread_tokens`` is the size of the thread pool sync routes run on, raised from anyio's 40
when the app starts, and ``mvp_loopback_limit`` bounds how many requests of the routes that call
other services over the internal listener run at once, so the calls they make always find a free
thread. ``mvp_service_scopes`` are the scopes of the service tokens the hosted services send each
other, minted in the process by identity's issuer, as ``client=scope+scope,client=scope``; empty,
the committed ``identity_dev_clients.toml`` gives them.

The worker process (``cw-mvp worker``) answers ``/health`` and ``/loops`` on
``mvp_worker_health_port`` (8001). Every ``mvp_worker_heartbeat_seconds`` it records which loops
and Temporal task queues are running; ``/health`` turns 503 when one it hosts is not, or when no
heartbeat came for ``mvp_worker_stale_seconds``, as when the event loop is blocked. Two switches
pick what it runs, both off by default (owner platform; each is removed once managed Kafka, or
Temporal Cloud, serves staging and production):

- ``worker_kafka_enabled`` (``CW_WORKER_KAFKA_ENABLED``): the outbox relays of every schema with
  an ``outbox_event`` table and every service's Kafka consumers;
- ``worker_temporal_enabled`` (``CW_WORKER_TEMPORAL_ENABLED``): every service's Temporal workers,
  on one client.

Periodic jobs (notification dispatch and retention, the rulebook's transitions, obligation's
reminder sweep, the idempotency purge of every schema with the table) run with either switch
off, each behind its service's own switch where it has one.

``ReleaseSettings`` are what the release commands read (``cw-mvp migrate``, ``topics``,
``release`` and ``check-config``): these, and ``migration_database_url``
(``CW_MIGRATION_DATABASE_URL``, a secret), the URL of the role that owns the service schemas.
Migrations run as that role and never over the app's runtime URL (``CW_DATABASE_URL``), whose
role row-level security applies to.
"""

from typing import Self

from pydantic import Field, SecretStr, model_validator

from py_common.settings import Settings

APP_SERVICE_NAME = "compliancewatch-api"
"""The service name of the app process: its telemetry resource and its log lines outside a
request."""
WORKER_SERVICE_NAME = "compliancewatch-worker"
"""The service name of the worker process."""


class MvpSettings(Settings):
    mvp_host: str = "::"
    mvp_public_port: int = Field(default=8000, ge=1, le=65535)
    mvp_internal_port: int = Field(default=8080, ge=1, le=65535)
    mvp_internal_url: str = "http://127.0.0.1:8080"
    mvp_forwarded_allow_ips: str = "*"
    mvp_thread_tokens: int = Field(default=200, ge=40, le=1000)
    mvp_loopback_limit: int = Field(default=32, ge=1, le=500)
    mvp_service_scopes: str = ""
    mvp_worker_health_port: int = Field(default=8001, ge=1, le=65535)
    mvp_worker_heartbeat_seconds: float = Field(default=5.0, gt=0, le=60)
    mvp_worker_stale_seconds: float = Field(default=30.0, gt=0, le=600)
    worker_kafka_enabled: bool = False
    worker_temporal_enabled: bool = False

    @model_validator(mode="after")
    def _two_listeners(self) -> Self:
        if self.mvp_public_port == self.mvp_internal_port:
            raise ValueError(
                "CW_MVP_PUBLIC_PORT and CW_MVP_INTERNAL_PORT must differ: the port a request "
                "comes in on decides which routes it reaches"
            )
        return self

    @model_validator(mode="after")
    def _fresh_heartbeats(self) -> Self:
        if self.mvp_worker_stale_seconds <= self.mvp_worker_heartbeat_seconds:
            raise ValueError(
                "CW_MVP_WORKER_STALE_SECONDS must be longer than CW_MVP_WORKER_HEARTBEAT_SECONDS"
            )
        return self


class ReleaseSettings(MvpSettings):
    migration_database_url: SecretStr | None = None
