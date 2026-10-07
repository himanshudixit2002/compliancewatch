"""FastAPI application factory: logging, telemetry, request context, problem details, health,
routers.

A service's ``main`` module exposes ``build_app(settings=None, ...)`` and serves ``app`` through
``module_app``, so importing the module builds nothing and reads no environment: a process that
hosts several services imports each ``main`` and builds each app with settings of its own.
"""

import sys
import threading
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from starlette.types import Lifespan

from domain_kernel.errors import DomainError
from py_common.auth.fastapi import Authenticator, ErasedTenantsReader
from py_common.health import ReadinessCheck, build_health_router
from py_common.logging import configure_logging
from py_common.problems import install_problem_handlers
from py_common.request_context import RequestContextMiddleware
from py_common.settings import Settings
from py_common.telemetry import Telemetry, configure_telemetry, instrument_app

APP_ATTRIBUTE = "app"
"""The name ``uvicorn <pkg>.main:app`` and ``make openapi`` read from a service's main module."""
_module_apps = threading.RLock()


def create_app(
    *,
    service_name: str,
    version: str,
    routers: Sequence[APIRouter] = (),
    settings: Settings | None = None,
    readiness_checks: Sequence[tuple[str, ReadinessCheck]] = (),
    lifespan: Lifespan[FastAPI] | None = None,
    problem_status: Mapping[type[DomainError], int] | None = None,
    authenticator: Authenticator | None = None,
    erased_tenants: ErasedTenantsReader | None = None,
) -> FastAPI:
    """Build the service app.

    ``problem_status`` maps the service's own domain errors to HTTP statuses; the kernel's defaults
    apply underneath. Every error leaves as ``application/problem+json``. ``tenant_id`` is bound by
    the service's own auth dependency. Telemetry exports to ``CW_OTEL_ENDPOINT`` when it is set
    and is flushed when the app shuts down, after the service's own ``lifespan``.

    ``authenticator`` is how ``py_common.auth.fastapi`` reads callers. By default it follows
    ``CW_AUTH_MODE`` and the ``CW_AUTH_*`` settings; the identity service passes one that
    verifies against its own keys in the process.

    ``app.state.readiness_checks`` keeps the checks behind ``/ready``, so a process that hosts
    this app next to others can report them under its own ``/ready``.

    ``erased_tenants`` are the service's erased markers (``py_common.erasure``): every route
    whose tenant ``tenant_scope`` resolves answers 410 ``tenant-erased`` for a tenant they hold.
    """
    settings = settings or Settings(service_name=service_name)
    configure_logging(
        service_name=service_name,
        log_level=settings.log_level,
        json_output=settings.log_json,
        env=settings.env,
    )
    telemetry = configure_telemetry(service_name=service_name, version=version, settings=settings)
    app = FastAPI(
        title=f"compliancewatch-{service_name}",
        version=version,
        lifespan=_with_telemetry_shutdown(lifespan, telemetry),
    )
    app.state.settings = settings
    app.state.telemetry = telemetry
    app.state.readiness_checks = tuple(readiness_checks)
    app.state.authenticator = authenticator or Authenticator.from_settings(settings)
    app.state.erased_tenants = erased_tenants
    app.add_middleware(RequestContextMiddleware)
    install_problem_handlers(app, problem_status or {})
    app.include_router(
        build_health_router(
            service_name=service_name, version=version, readiness_checks=readiness_checks
        )
    )
    for router in routers:
        app.include_router(router)
    instrument_app(app, telemetry)
    return app


def _with_telemetry_shutdown(
    lifespan: Lifespan[FastAPI] | None, telemetry: Telemetry
) -> Lifespan[FastAPI] | None:
    if not telemetry.enabled:
        return lifespan

    @asynccontextmanager
    async def wrapped(app: FastAPI) -> AsyncIterator[None]:
        if lifespan is None:
            yield
        else:
            async with lifespan(app):
                yield
        telemetry.shutdown()

    return wrapped


def module_app(name: str, factory: Callable[[], FastAPI]) -> FastAPI:
    """The body of a service main module's PEP 562 ``__getattr__``::

        def __getattr__(name: str) -> FastAPI:
            return module_app(name, build_app)

    ``app`` is built by ``factory`` on its first access, once, and kept on the module that
    defines ``factory``, so ``uvicorn <pkg>.main:app``, ``make openapi`` and
    ``from <pkg>.main import app`` work while importing the module builds nothing. Any other
    name raises ``AttributeError``, as a missing module attribute does.
    """
    module = sys.modules[factory.__module__]
    if name != APP_ATTRIBUTE:
        raise AttributeError(f"module {module.__name__!r} has no attribute {name!r}")
    with _module_apps:
        built = module.__dict__.get(APP_ATTRIBUTE)
        if not isinstance(built, FastAPI):
            built = factory()
            setattr(module, APP_ATTRIBUTE, built)
        return built
