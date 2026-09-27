"""FastAPI application factory: logging, request context, problem details, health, routers."""

from collections.abc import Mapping, Sequence

from fastapi import APIRouter, FastAPI
from starlette.types import Lifespan

from domain_kernel.errors import DomainError
from py_common.health import ReadinessCheck, build_health_router
from py_common.logging import configure_logging
from py_common.problems import install_problem_handlers
from py_common.request_context import RequestContextMiddleware
from py_common.settings import Settings


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
    the service's own auth dependency.
    """
    settings = settings or Settings(service_name=service_name)
    configure_logging(
        service_name=service_name, log_level=settings.log_level, json_output=settings.log_json
    )
    app = FastAPI(title=f"compliancewatch-{service_name}", version=version, lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(RequestContextMiddleware)
    install_problem_handlers(app, problem_status or {})
    app.include_router(
        build_health_router(
            service_name=service_name, version=version, readiness_checks=readiness_checks
        )
    )
    for router in routers:
        app.include_router(router)
    return app
