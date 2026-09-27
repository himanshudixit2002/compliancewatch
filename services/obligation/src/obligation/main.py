"""Composition root for the obligation service.

Guide section 11: wiring of interfaces to implementations happens here, never inside the layers.
The use cases run on the Postgres unit of work (row-level security by tenant, events through the
outbox); the API surface is still the health routes and ping until the first consumer lands.
"""

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from obligation import __version__
from obligation.api.router import router
from obligation.application.changes import ApplyDeadlineChange, CloseObligation, WithdrawRule
from obligation.application.materialise import MaterialiseObligations
from obligation.infrastructure.repository import PostgresUnitOfWorkFactory
from py_common.app import create_app
from py_common.settings import Settings

SERVICE_NAME = "obligation"


class Wiring:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.unit_of_work = PostgresUnitOfWorkFactory.from_url(settings.database_url)
        self.materialise = MaterialiseObligations(self.unit_of_work)
        self.apply_deadline_change = ApplyDeadlineChange(self.unit_of_work)
        self.withdraw_rule = WithdrawRule(self.unit_of_work)
        self.close_obligation = CloseObligation(self.unit_of_work)

    async def database_ready(self) -> bool:
        return await run_in_threadpool(self.unit_of_work.ping)


def build_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings(service_name=SERVICE_NAME)
    wiring = Wiring(settings)
    app = create_app(
        service_name=SERVICE_NAME,
        version=__version__,
        routers=[router],
        settings=settings,
        readiness_checks=[("database", wiring.database_ready)],
    )
    app.state.wiring = wiring
    return app


app = build_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("obligation.main:app", host="127.0.0.1", port=8005, reload=True)
