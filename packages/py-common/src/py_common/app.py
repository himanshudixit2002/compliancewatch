"""FastAPI application factory: logging, telemetry, request context, problem details, health,
routers."""

from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from starlette.types import Lifespan

from domain_kernel.errors import DomainError
from py_common.health import ReadinessCheck, build_health_router
from py_common.logging import configure_logging
from py_common.problems import install_problem_handlers
from py_common.request_context import RequestContextMiddleware
from py_common.settings import Settings
from py_common.telemetry import Telemetry, configure_telemetry, instrument_app


def create_app(
    *,
    service_name: str,
    version: str,
    routers: Sequence[APIRouter] = (),
    settings: Settings | None = None,
    readiness_checks: Sequence[tuple[str, ReadinessCheck]] = (),
    lifespan: Lifespan[FastAPI] | None = None,
    problem_status: Mapping[type[DomainError], int] | None = None,
) -> FastAPI:
    """Build the service app.

    ``problem_status`` maps the service's own domain errors to HTTP statuses; the kernel's defaults
    apply underneath. Every error leaves as ``application/problem+json``. ``tenant_id`` is bound by
    the service's own auth dependency. Telemetry exports to ``CW_OTEL_ENDPOINT`` when it is set
    and is flushed when the app shuts down, after the service's own ``lifespan``.
    """
    settings = settings or Settings(service_name=service_name)
    configure_logging(
        service_name=service_name, log_level=settings.log_level, json_output=settings.log_json
    )
    telemetry = configure_telemetry(service_name=service_name, version=version, settings=settings)
    app = FastAPI(
        title=f"compliancewatch-{service_name}",
        version=version,
        lifespan=_with_telemetry_shutdown(lifespan, telemetry),
    )
    app.state.settings = settings
    app.state.telemetry = telemetry
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
