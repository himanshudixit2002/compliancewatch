"""The app process: every hosted service's FastAPI app behind one dispatcher.

``build_app(settings)`` builds, in order:

1. the process's telemetry, as ``compliancewatch-api`` (the first call in a process wins, so
   every service's app reports under that resource);
2. identity, then every other service with its own settings (``registry.service_settings``).
   Every service verifies callers with identity's authenticator, which holds identity's keys,
   so no service fetches the key set over HTTP. Outside ``header`` mode the services that call
   others (``takes_token_source``) send service tokens minted in the process by identity's
   issuer, with the scopes of ``CW_MVP_SERVICE_SCOPES``, so the app needs no client secrets;
3. the root app, which serves ``/health`` and ``/ready`` for all of them (``/ready`` lists every
   service's checks as ``<service>.<check>``) and whose lifespan enters every service's lifespan
   in order and leaves them in reverse. On start it also raises the thread pool that sync routes
   run on to ``CW_MVP_THREAD_TOKENS``;
4. the dispatcher (``cw_mvp.dispatch``) in front of the root app and the services, inside one
   ``RequestContextMiddleware``, so a request gets one correlation id and one ``x-request-id``.

``service_overrides`` replaces settings of named services, such as the memory stores of
``cw_mvp.testing``, and ``build_overrides`` passes extra arguments to their ``build_app``, such
as a scripted completion provider. Both refuse a service the registry does not have.
"""

from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any, Final

import anyio.to_thread
from fastapi import FastAPI
from starlette.types import ASGIApp, Receive, Scope, Send

from cw_mvp import __version__
from cw_mvp.dispatch import RouteTable, ServiceDispatcher
from cw_mvp.exposure import EXPOSURE
from cw_mvp.registry import REGISTRY, ServiceEntry, check_overrides, service_settings
from cw_mvp.settings import APP_SERVICE_NAME, MvpSettings
from domain_kernel.access import Principal
from identity.settings import parse_dev_clients
from identity.wiring import Wiring as IdentityWiring
from py_common.app import create_app
from py_common.auth import IssuerTokenSource, TokenIssuer, TokenSource
from py_common.auth.fastapi import Authenticator
from py_common.flags import flag_may_be_on
from py_common.health import ReadinessCheck
from py_common.logging import configure_logging
from py_common.request_context import RequestContextMiddleware
from py_common.telemetry import configure_telemetry

IDENTITY: Final = "identity"
"""The service built first: its authenticator and issuer serve every other one."""

TokenSources = Callable[[str], TokenSource]
"""The in-process token source of a service, by its name."""


class CombinedApp:
    """The ASGI app ``cw-mvp serve`` runs: the request context around the dispatcher. It keeps
    the settings, the root app, every service's app and the dispatcher for tests and tools."""

    def __init__(
        self,
        settings: MvpSettings,
        root: FastAPI,
        services: Mapping[str, FastAPI],
        dispatcher: ServiceDispatcher,
    ) -> None:
        self.settings = settings
        self.root = root
        self.services = dict(services)
        self.dispatcher = dispatcher
        self._app: ASGIApp = RequestContextMiddleware(dispatcher)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._app(scope, receive, send)


def build_app(
    settings: MvpSettings | None = None,
    *,
    service_overrides: Mapping[str, Mapping[str, Any]] | None = None,
    build_overrides: Mapping[str, Mapping[str, Any]] | None = None,
    registry: Sequence[ServiceEntry[Any]] = REGISTRY,
) -> CombinedApp:
    settings = settings or MvpSettings(service_name=APP_SERVICE_NAME)
    service_overrides = service_overrides or {}
    build_overrides = build_overrides or {}
    check_overrides(service_overrides, registry)
    check_overrides(build_overrides, registry)
    configure_telemetry(service_name=APP_SERVICE_NAME, version=__version__, settings=settings)

    services: dict[str, FastAPI] = {}
    authenticator: Authenticator | None = None
    tokens: TokenSources | None = None
    for entry in registry:
        entry_settings = service_settings(
            entry,
            settings,
            internal_url=settings.mvp_internal_url,
            **service_overrides.get(entry.name, {}),
        )
        arguments = dict(build_overrides.get(entry.name, {}))
        if entry.takes_authenticator:
            if authenticator is None:
                raise ValueError(
                    f"{IDENTITY} must come first in the registry: {entry.name} "
                    "verifies callers with its authenticator"
                )
            arguments.setdefault("authenticator", authenticator)
        if entry.takes_token_source and tokens is not None:
            arguments.setdefault("token_source", tokens(entry.name))
        app = entry.build(entry_settings, **arguments)
        if entry.name == IDENTITY:
            authenticator = _authenticator_of(app)
            if settings.auth_mode != "header":
                tokens = in_process_tokens(app, settings.mvp_service_scopes)
        services[entry.name] = app

    root = create_app(
        service_name=APP_SERVICE_NAME,
        version=__version__,
        settings=settings,
        readiness_checks=readiness_checks(services),
        lifespan=_lifespan(services, thread_tokens=settings.mvp_thread_tokens),
        authenticator=authenticator,
    )
    # Every service's create_app configured logging under its own name; the process logs as
    # one, and the dispatcher binds the owning service to each request's lines.
    configure_logging(
        service_name=APP_SERVICE_NAME,
        log_level=settings.log_level,
        json_output=settings.log_json,
        env=settings.env,
    )
    table = RouteTable.of(
        services,
        {entry.name: entry.prefix for entry in registry},
        exposure=EXPOSURE,
        loopback={
            entry.name: entry.loopback_routes_for(lambda flag: flag_may_be_on(flag, settings))
            for entry in registry
        },
    )
    dispatcher = ServiceDispatcher(
        root,
        services,
        table,
        internal_port=settings.mvp_internal_port,
        auth_mode=settings.auth_mode,
        loopback_limit=settings.mvp_loopback_limit,
    )
    return CombinedApp(settings, root, services, dispatcher)


def readiness_checks(services: Mapping[str, FastAPI]) -> list[tuple[str, ReadinessCheck]]:
    """Every service's readiness checks, named ``<service>.<check>``."""
    checks: list[tuple[str, ReadinessCheck]] = []
    for service, app in services.items():
        for name, check in getattr(app.state, "readiness_checks", ()):
            checks.append((f"{service}.{name}", check))
    return checks


def in_process_tokens(identity: FastAPI, scopes: str) -> TokenSources:
    """Token sources that mint each service's token with identity's issuer, the service's scopes
    taken from ``scopes`` (``client=scope+scope,...``; blank for the committed dev clients)."""
    wiring = identity.state.wiring
    if not isinstance(wiring, IdentityWiring):  # pragma: no cover - identity.main sets it
        raise TypeError("the identity app carries no wiring")
    granted = parse_dev_clients(scopes)
    issuer = TokenIssuer(
        wiring.keys, issuer=wiring.settings.auth_issuer, audience=wiring.settings.auth_audience
    )

    def source(service: str) -> TokenSource:
        principal = Principal.service(service, granted.get(service, frozenset()))
        return IssuerTokenSource(issuer, principal)

    return source


def raise_thread_limit(tokens: int) -> None:
    """Let at least ``tokens`` sync routes run at once; anyio's default is 40."""
    limiter = anyio.to_thread.current_default_thread_limiter()
    if limiter.total_tokens < tokens:
        limiter.total_tokens = tokens


def _authenticator_of(app: FastAPI) -> Authenticator:
    authenticator = app.state.authenticator
    if not isinstance(authenticator, Authenticator):  # pragma: no cover - create_app sets it
        raise TypeError(f"{IDENTITY} app carries no authenticator")
    return authenticator


def _lifespan(services: Mapping[str, FastAPI], *, thread_tokens: int) -> Callable[[FastAPI], Any]:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        raise_thread_limit(thread_tokens)
        async with AsyncExitStack() as stack:
            for app in services.values():
                await stack.enter_async_context(app.router.lifespan_context(app))
            yield

    return lifespan
