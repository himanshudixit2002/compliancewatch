"""Composition root for the profile service.

Guide section 11: wiring of interfaces to implementations happens here, never inside the layers.
The tenant comes from the ``x-tenant-id`` header until the identity service issues tokens.
"""

from collections.abc import Awaitable, Callable

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

import ontology as ontology_package
from domain_kernel.errors import DomainError, InvalidAttributeValueError, UnknownAttributeError
from domain_kernel.ontology import Ontology
from profile_service import __version__
from profile_service.api.router import router
from profile_service.application.attributes import (
    BuildSnapshot,
    ConfirmFinancialYear,
    NextQuestion,
    SetAttributes,
)
from profile_service.application.prefill import PrefillFromGstin
from profile_service.application.registration import RegisterNodes
from profile_service.domain.errors import (
    AttributeLevelMismatchError,
    FinancialYearRequiredError,
    InvalidHierarchyError,
    ProfileNodeNotFoundError,
    TenantRequiredError,
)
from profile_service.domain.lookup import GstinLookupProvider
from profile_service.domain.repository import UnitOfWorkFactory
from profile_service.infrastructure.lookup import (
    DEMO_LOOKUPS,
    ManualLookupProvider,
    StaticLookupProvider,
)
from profile_service.infrastructure.memory import MemoryStore
from profile_service.infrastructure.repository import (
    JsonLinesEvalRecorder,
    PostgresUnitOfWorkFactory,
)
from profile_service.settings import ProfileSettings
from profile_service.wiring import Wiring
from py_common.app import create_app

SERVICE_NAME = "profile"
PROBLEM_STATUS: dict[type[DomainError], int] = {
    TenantRequiredError: 401,
    ProfileNodeNotFoundError: 404,
    InvalidHierarchyError: 422,
    AttributeLevelMismatchError: 422,
    FinancialYearRequiredError: 422,
    # A value the ontology rejects or a key it does not define is a bad request, not a 404
    InvalidAttributeValueError: 422,
    UnknownAttributeError: 422,
}


def wire(settings: ProfileSettings, ontology: Ontology | None = None) -> Wiring:
    loaded = ontology or ontology_package.load()
    unit_of_work: UnitOfWorkFactory
    ping: Callable[[], bool]
    if settings.profile_store == "memory":
        memory = MemoryStore()
        unit_of_work, ping = memory, memory.ping
    else:
        recorder = (
            None
            if settings.profile_eval_cases_path is None
            else JsonLinesEvalRecorder(settings.profile_eval_cases_path)
        )
        postgres = PostgresUnitOfWorkFactory.from_url(settings.database_url, eval_cases=recorder)
        unit_of_work, ping = postgres, postgres.ping

    async def store_ready() -> bool:
        return await run_in_threadpool(ping)

    lookup: GstinLookupProvider = (
        StaticLookupProvider(DEMO_LOOKUPS)
        if settings.profile_gstin_lookup == "static"
        else ManualLookupProvider()
    )
    set_attributes = SetAttributes(unit_of_work, loaded)
    return Wiring(
        settings=settings,
        ontology=loaded,
        unit_of_work=unit_of_work,
        store_ready=store_ready,
        register=RegisterNodes(unit_of_work),
        set_attributes=set_attributes,
        next_question=NextQuestion(unit_of_work, loaded),
        build_snapshot=BuildSnapshot(unit_of_work),
        confirm_financial_year=ConfirmFinancialYear(unit_of_work, loaded),
        prefill=PrefillFromGstin(unit_of_work, lookup, set_attributes, loaded),
    )


def _ontology_ready(wiring: Wiring) -> Callable[[], Awaitable[bool]]:
    async def check() -> bool:
        return len(wiring.ontology) > 0

    return check


def build_app(settings: ProfileSettings | None = None) -> FastAPI:
    settings = settings or ProfileSettings(service_name=SERVICE_NAME)
    wiring = wire(settings)
    app = create_app(
        service_name=SERVICE_NAME,
        version=__version__,
        routers=[router],
        settings=settings,
        readiness_checks=[("store", wiring.store_ready), ("ontology", _ontology_ready(wiring))],
        problem_status=PROBLEM_STATUS,
    )
    app.state.wiring = wiring
    return app


app = build_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("profile_service.main:app", host="127.0.0.1", port=8002, reload=True)
