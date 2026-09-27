"""FastAPI application factory: logging, request-id middleware, health routes, service routers."""

import uuid
from collections.abc import Sequence

import structlog
from fastapi import APIRouter, FastAPI
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Lifespan, Message, Receive, Scope, Send

from py_common.health import ReadinessCheck, build_health_router
from py_common.logging import configure_logging
from py_common.settings import Settings

REQUEST_ID_HEADER = "x-request-id"


class RequestContextMiddleware:
    """Pure ASGI middleware: reuse or mint an ``x-request-id``, bind it as ``correlation_id``."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        correlation_id = Headers(scope=scope).get(REQUEST_ID_HEADER) or uuid.uuid4().hex

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).append(REQUEST_ID_HEADER, correlation_id)
            await send(message)

        with structlog.contextvars.bound_contextvars(correlation_id=correlation_id):
            await self.app(scope, receive, send_with_request_id)


def create_app(
    *,
    service_name: str,
    version: str,
    routers: Sequence[APIRouter] = (),
    settings: Settings | None = None,
    readiness_checks: Sequence[tuple[str, ReadinessCheck]] = (),
    lifespan: Lifespan[FastAPI] | None = None,
) -> FastAPI:
    """Build the service app.

    ``tenant_id`` is bound later by the auth dependency, never from a header.
    """
    settings = settings or Settings(service_name=service_name)
    configure_logging(
        service_name=service_name, log_level=settings.log_level, json_output=settings.log_json
    )
    app = FastAPI(title=f"compliancewatch-{service_name}", version=version, lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(RequestContextMiddleware)
    app.include_router(
        build_health_router(
            service_name=service_name, version=version, readiness_checks=readiness_checks
        )
    )
    for router in routers:
        app.include_router(router)
    return app
