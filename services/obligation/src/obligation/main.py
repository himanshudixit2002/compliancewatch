"""Composition root for the obligation service.

Guide section 11: wiring of interfaces to implementations happens here, never inside the layers.
The use cases run on the Postgres unit of work (row-level security by tenant, events through the
outbox). The API reads a business's obligations; the caller and its tenant come from
``py_common.auth`` by ``CW_AUTH_MODE`` (``api.deps``). Nothing writes through the API yet: the use
cases that create and change obligations wait for their event consumers.
"""

from collections.abc import Callable

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from domain_kernel.errors import DomainError
from obligation import __version__
from obligation.api.router import router
from obligation.application.changes import ApplyDeadlineChange, CloseObligation, WithdrawRule
from obligation.application.materialise import MaterialiseObligations
from obligation.application.queries import ListObligations
from obligation.domain.errors import (
    ObligationClosedError,
    ObligationNotFoundError,
    ObligationTenantRequiredError,
    ObligationWindowInvalidError,
)
from obligation.domain.repository import UnitOfWorkFactory
from obligation.infrastructure.memory import MemoryStore
from obligation.infrastructure.repository import PostgresUnitOfWorkFactory
from obligation.settings import ObligationSettings
from obligation.wiring import Wiring
from py_common.app import create_app, module_app

SERVICE_NAME = "obligation"
PROBLEM_STATUS: dict[type[DomainError], int] = {
    ObligationTenantRequiredError: 401,
    ObligationWindowInvalidError: 422,
    ObligationNotFoundError: 404,
    ObligationClosedError: 409,
}


def wire(settings: ObligationSettings) -> Wiring:
    unit_of_work: UnitOfWorkFactory
    ping: Callable[[], bool]
    if settings.obligation_store == "memory":
        memory = MemoryStore()
        unit_of_work, ping = memory, memory.ping
    else:
        postgres = PostgresUnitOfWorkFactory.from_url(settings.database_url)
        unit_of_work, ping = postgres, postgres.ping

    async def store_ready() -> bool:
        return await run_in_threadpool(ping)

    return Wiring(
        settings=settings,
        unit_of_work=unit_of_work,
        store_ready=store_ready,
        materialise=MaterialiseObligations(unit_of_work),
        apply_deadline_change=ApplyDeadlineChange(unit_of_work),
        withdraw_rule=WithdrawRule(unit_of_work),
        close_obligation=CloseObligation(unit_of_work),
        list_obligations=ListObligations(unit_of_work),
    )


def build_app(settings: ObligationSettings | None = None) -> FastAPI:
    settings = settings or ObligationSettings(service_name=SERVICE_NAME)
    wiring = wire(settings)
    app = create_app(
        service_name=SERVICE_NAME,
        version=__version__,
        routers=[router],
        settings=settings,
        readiness_checks=[("store", wiring.store_ready)],
        problem_status=PROBLEM_STATUS,
    )
    app.state.wiring = wiring
    return app


def __getattr__(name: str) -> FastAPI:
    """``app`` is built on first access, so importing this module builds nothing."""
    return module_app(name, build_app)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("obligation.main:app", host="127.0.0.1", port=8005, reload=True)
