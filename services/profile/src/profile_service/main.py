"""Composition root for the profile service.

Guide section 11: wiring of interfaces to implementations happens here, never inside the layers.
The tenant comes from the ``x-tenant-id`` header until the identity service issues tokens.
"""

from collections.abc import Awaitable, Callable

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

import ontology as ontology_package
from domain_kernel.errors import DomainError, InvalidAttributeValueError, UnknownAttributeError
from domain_kernel.ontology import Ontology, OntologyWording
from profile_service import __version__
from profile_service.api.businesses import router as businesses_router
from profile_service.api.router import router
from profile_service.application.attributes import (
    BuildSnapshot,
    ConfirmFinancialYear,
    NextQuestion,
    SetAttributes,
)
from profile_service.application.businesses import (
    AddRegistration,
    CreateBusiness,
    ListBusinesses,
    ReadBusiness,
    UpdateBusiness,
)
from profile_service.application.onboarding import OnboardingChecklist
from profile_service.application.prefill import PrefillFromGstin
from profile_service.application.registration import RegisterNodes
from profile_service.domain.errors import (
    AttributeLevelMismatchError,
    BusinessIdentifierRequiredError,
    FinancialYearRequiredError,
    InvalidHierarchyError,
    NotABusinessError,
    ProfileNodeNotFoundError,
    RegistrationAmbiguousError,
    TenantRequiredError,
)
from profile_service.domain.flags import FeatureFlags
from profile_service.domain.lookup import GstinLookupProvider
from profile_service.domain.repository import UnitOfWorkFactory
from profile_service.infrastructure.flags import OpenFeatureFlags
from profile_service.infrastructure.lookup import (
    DEMO_LOOKUPS,
    ManualLookupProvider,
    StaticLookupProvider,
)
from profile_service.infrastructure.lookup_http import HttpGstinLookupProvider
from profile_service.infrastructure.memory import MemoryStore
from profile_service.infrastructure.repository import (
    JsonLinesEvalRecorder,
    PostgresUnitOfWorkFactory,
)
from profile_service.settings import ProfileSettings
from profile_service.wiring import Wiring
from py_common.app import create_app
from py_common.flags import configure_flags
from py_common.idempotency import IdempotencyStore, MemoryIdempotencyStore
from py_common.idempotency.sqlalchemy import SqlAlchemyIdempotencyStore

SERVICE_NAME = "profile"
PROBLEM_STATUS: dict[type[DomainError], int] = {
    TenantRequiredError: 401,
    ProfileNodeNotFoundError: 404,
    NotABusinessError: 404,
    BusinessIdentifierRequiredError: 422,
    RegistrationAmbiguousError: 422,
    InvalidHierarchyError: 422,
    AttributeLevelMismatchError: 422,
    FinancialYearRequiredError: 422,
    # A value the ontology rejects or a key it does not define is a bad request, not a 404
    InvalidAttributeValueError: 422,
    UnknownAttributeError: 422,
}


def wire(
    settings: ProfileSettings,
    ontology: Ontology | None = None,
    *,
    wording: OntologyWording | None = None,
    flags: FeatureFlags | None = None,
) -> Wiring:
    """Build the use cases on the store the settings name, with the packaged ontology and its
    English wording unless others are given. Without ``flags`` the process-wide OpenFeature
    provider is configured from the settings and answers them. Idempotency keys live next to
    the profile tables (``idempotency_key``, migration 0003), each key in its own short
    transaction."""
    loaded = ontology or ontology_package.load()
    if flags is None:
        configure_flags(settings)
        flags = OpenFeatureFlags()
    unit_of_work: UnitOfWorkFactory
    ping: Callable[[], bool]
    idempotency: IdempotencyStore
    if settings.profile_store == "memory":
        memory = MemoryStore()
        unit_of_work, ping, idempotency = memory, memory.ping, MemoryIdempotencyStore()
    else:
        recorder = (
            None
            if settings.profile_eval_cases_path is None
            else JsonLinesEvalRecorder(settings.profile_eval_cases_path)
        )
        postgres = PostgresUnitOfWorkFactory.from_url(settings.database_url, eval_cases=recorder)
        unit_of_work, ping = postgres, postgres.ping
        idempotency = SqlAlchemyIdempotencyStore(postgres.engine)

    async def store_ready() -> bool:
        return await run_in_threadpool(ping)

    prefill = PrefillFromGstin(unit_of_work, _lookup(settings), loaded, flags)
    return Wiring(
        settings=settings,
        ontology=loaded,
        wording=wording or ontology_package.load_wording(),
        unit_of_work=unit_of_work,
        store_ready=store_ready,
        idempotency=idempotency,
        register=RegisterNodes(unit_of_work),
        set_attributes=SetAttributes(unit_of_work, loaded),
        next_question=NextQuestion(unit_of_work, loaded),
        build_snapshot=BuildSnapshot(unit_of_work),
        confirm_financial_year=ConfirmFinancialYear(unit_of_work, loaded),
        prefill=prefill,
        create_business=CreateBusiness(unit_of_work, loaded, prefill),
        update_business=UpdateBusiness(unit_of_work, loaded),
        read_business=ReadBusiness(unit_of_work),
        list_businesses=ListBusinesses(unit_of_work),
        add_registration=AddRegistration(unit_of_work, prefill),
        onboarding=OnboardingChecklist(unit_of_work, loaded),
    )


def _lookup(settings: ProfileSettings) -> GstinLookupProvider:
    """The provider ``CW_PROFILE_GSTIN_LOOKUP`` names (the flag ``profile.gstin_lookup``)."""
    if settings.profile_gstin_lookup == "static":
        return StaticLookupProvider(DEMO_LOOKUPS)
    key = settings.profile_gstin_lookup_api_key
    if settings.profile_gstin_lookup == "http" and key is not None:
        return HttpGstinLookupProvider(
            settings.profile_gstin_lookup_url,
            api_key=key.get_secret_value(),
            timeout_seconds=settings.profile_gstin_lookup_timeout_seconds,
        )
    return ManualLookupProvider()


def _ontology_ready(wiring: Wiring) -> Callable[[], Awaitable[bool]]:
    async def check() -> bool:
        return len(wiring.ontology) > 0

    return check


def build_app(
    settings: ProfileSettings | None = None, *, flags: FeatureFlags | None = None
) -> FastAPI:
    """``flags`` replaces the OpenFeature flags (tests)."""
    settings = settings or ProfileSettings(service_name=SERVICE_NAME)
    wiring = wire(settings, flags=flags)
    app = create_app(
        service_name=SERVICE_NAME,
        version=__version__,
        routers=[router, businesses_router],
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
