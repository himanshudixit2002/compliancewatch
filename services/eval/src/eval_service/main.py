"""Composition root for the eval service.

Guide section 11: wiring of interfaces to implementations happens here, never inside the layers.
An operator starts a run of one harness suite under a profile; the run is stored with its gates
and their drift against the previous run of the same suite and profile, and
``eval.run.completed`` goes out through the outbox in the same transaction. Admins start runs;
the regulatory roles read them (``api.deps``).
"""

from collections.abc import Callable

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from domain_kernel.errors import DomainError
from eval_service import __version__
from eval_service.api.router import router
from eval_service.application.queries import GetEvalRun, ListEvalRuns
from eval_service.application.run_eval import RunEvalSuite
from eval_service.domain.errors import EvalHarnessError, EvalRunNotFoundError
from eval_service.domain.repository import SuiteRunner, UnitOfWorkFactory
from eval_service.infrastructure.harness import HarnessSuiteRunner
from eval_service.infrastructure.memory import MemoryStore
from eval_service.infrastructure.repository import PostgresUnitOfWorkFactory
from eval_service.settings import EvalSettings
from eval_service.wiring import Wiring
from py_common.app import create_app

SERVICE_NAME = "eval"
PROBLEM_STATUS: dict[type[DomainError], int] = {
    EvalRunNotFoundError: 404,
    EvalHarnessError: 502,
}


def wire(settings: EvalSettings, *, runner: SuiteRunner | None = None) -> Wiring:
    """``runner``, when given, runs the suites in place of the harness: the seam tests use."""
    unit_of_work: UnitOfWorkFactory
    ping: Callable[[], bool]
    if settings.eval_store == "memory":
        memory = MemoryStore()
        unit_of_work, ping = memory, memory.ping
    else:
        postgres = PostgresUnitOfWorkFactory.from_url(settings.database_url)
        unit_of_work, ping = postgres, postgres.ping
    suite_runner = runner or HarnessSuiteRunner(
        golden_dir=settings.eval_golden_dir,
        gateway_url=settings.eval_gateway_url,
        timeout_seconds=settings.eval_harness_timeout_seconds,
    )

    async def store_ready() -> bool:
        return await run_in_threadpool(ping)

    return Wiring(
        settings=settings,
        store_ready=store_ready,
        run_suite=RunEvalSuite(unit_of_work, suite_runner),
        list_runs=ListEvalRuns(unit_of_work),
        get_run=GetEvalRun(unit_of_work),
    )


def build_app(
    settings: EvalSettings | None = None, *, runner: SuiteRunner | None = None
) -> FastAPI:
    settings = settings or EvalSettings(service_name=SERVICE_NAME)
    wiring = wire(settings, runner=runner)
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


app = build_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("eval_service.main:app", host="127.0.0.1", port=8009, reload=True)
