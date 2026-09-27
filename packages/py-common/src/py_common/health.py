"""Liveness and readiness endpoints, mounted at the root of every service."""

from collections.abc import Awaitable, Callable, Sequence

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from py_common.logging import get_logger

ReadinessCheck = Callable[[], Awaitable[bool]]
log = get_logger(__name__)


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class ReadyResponse(BaseModel):
    status: str
    checks: dict[str, bool]


def build_health_router(
    *,
    service_name: str,
    version: str,
    readiness_checks: Sequence[tuple[str, ReadinessCheck]] = (),
) -> APIRouter:
    router = APIRouter(tags=["health"])

    @router.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", service=service_name, version=version)

    @router.get("/ready", response_model=ReadyResponse, responses={503: {"model": ReadyResponse}})
    async def ready(response: Response) -> ReadyResponse:
        results: dict[str, bool] = {}
        for name, check in readiness_checks:
            try:
                results[name] = await check()
            except Exception:
                # A failing probe must report, not raise: the caller decides what to do.
                log.exception("readiness_check_failed", check=name)
                results[name] = False
        ok = all(results.values())
        if not ok:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadyResponse(status="ready" if ok else "not_ready", checks=results)

    return router
