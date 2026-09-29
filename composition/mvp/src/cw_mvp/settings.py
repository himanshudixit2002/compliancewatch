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
"""

from typing import Self

from pydantic import Field, model_validator

from py_common.settings import Settings

APP_SERVICE_NAME = "compliancewatch-api"
"""The service name of the app process: its telemetry resource and its log lines outside a
request."""


class MvpSettings(Settings):
    mvp_host: str = "::"
    mvp_public_port: int = Field(default=8000, ge=1, le=65535)
    mvp_internal_port: int = Field(default=8080, ge=1, le=65535)
    mvp_internal_url: str = "http://127.0.0.1:8080"
    mvp_forwarded_allow_ips: str = "*"
    mvp_thread_tokens: int = Field(default=200, ge=40, le=1000)
    mvp_loopback_limit: int = Field(default=32, ge=1, le=500)
    mvp_service_scopes: str = ""

    @model_validator(mode="after")
    def _two_listeners(self) -> Self:
        if self.mvp_public_port == self.mvp_internal_port:
            raise ValueError(
                "CW_MVP_PUBLIC_PORT and CW_MVP_INTERNAL_PORT must differ: the port a request "
                "comes in on decides which routes it reaches"
            )
        return self
