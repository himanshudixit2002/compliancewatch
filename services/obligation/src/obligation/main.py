"""Composition root for the obligation service.

Guide section 11: wiring of interfaces to implementations happens here, never inside the layers.
The use cases run on the Postgres unit of work (row-level security by tenant, events through the
outbox); the API surface is still the health routes and ping until the first consumer lands.
"""

from collections.abc import Callable

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from obligation import __version__
from obligation.api.router import router
from obligation.application.changes import ApplyDeadlineChange, CloseObligation, WithdrawRule
from obligation.application.materialise import MaterialiseObligations
from obligation.domain.repository import UnitOfWorkFactory
from obligation.infrastructure.memory import MemoryStore
from obligation.infrastructure.repository import PostgresUnitOfWorkFactory
from obligation.settings import ObligationSettings
from py_common.app import create_app

SERVICE_NAME = "obligation"


class Wiring:
    def __init__(self, settings: ObligationSettings) -> None:
        self.settings = settings
        unit_of_work: UnitOfWorkFactory
        ping: Callable[[], bool]
        if settings.obligation_store == "memory":
            memory = MemoryStore()
            unit_of_work, ping = memory, memory.ping
        else:
            postgres = PostgresUnitOfWorkFactory.from_url(settings.database_url)
            unit_of_work, ping = postgres, postgres.ping
        self.unit_of_work = unit_of_work
        self._ping = ping
        self.materialise = MaterialiseObligations(self.unit_of_work)
        self.apply_deadline_change = ApplyDeadlineChange(self.unit_of_work)
        self.withdraw_rule = WithdrawRule(self.unit_of_work)
        self.close_obligation = CloseObligation(self.unit_of_work)

    async def store_ready(self) -> bool:
        return await run_in_threadpool(self._ping)


def build_app(settings: ObligationSettings | None = None) -> FastAPI:
    settings = settings or ObligationSettings(service_name=SERVICE_NAME)
    wiring = Wiring(settings)
    app = create_app(
        service_name=SERVICE_NAME,
        version=__version__,
        routers=[router],
        settings=settings,
        readiness_checks=[("store", wiring.store_ready)],
    )
    app.state.wiring = wiring
    return app


app = build_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("obligation.main:app", host="127.0.0.1", port=8005, reload=True)
