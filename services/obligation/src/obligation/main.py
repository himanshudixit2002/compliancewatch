"""Composition root for the obligation service.

Guide section 11: wiring of interfaces to implementations happens here, never inside the layers.
The use cases run on the Postgres unit of work (row-level security by tenant, events through the
outbox, audit entries into ``audit.event``). The API reads a business's obligations and one
obligation whole, lets the tenant's members start, complete, waive, assign and comment on
one and report an error in it (behind the flag ``obligation.error_reports``, read through
``py_common.flags``), and hands the tenant's admins and identity the service's part of a tenant's
data export;
the caller and its tenant come from ``py_common.auth`` by ``CW_AUTH_MODE`` (``api.deps``).
The writes take an Idempotency-Key, kept next to the obligations (``idempotency_key``, migration
0005) and each key in its own short transaction. The detail reads the rulebook at
``CW_RULEBOOK_URL`` when its cache has no row of the version, an assignment asks the identity
service at ``CW_IDENTITY_URL`` whether the assignee is a user of the tenant, and the public list of
a business's obligations asks the profile service at ``CW_PROFILE_URL`` whether a business with
nothing on the page is the tenant's, each with this service's token outside ``header`` mode. The
worker (``obligation.worker``) creates and closes obligations from applicability decisions and
rule events.
"""

from collections.abc import Callable

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from domain_kernel.erasure import ErasedTenants
from domain_kernel.errors import DomainError, InvalidTransitionError
from obligation import __version__
from obligation.api.router import business_router, public_router, router
from obligation.application.changes import ApplyDeadlineChange, CloseObligation, WithdrawRule
from obligation.application.error_reports import ListErrorReports, ReportError
from obligation.application.export import ExportTenantData
from obligation.application.materialise import MaterialiseObligations
from obligation.application.queries import ListBusinessObligations, ListObligations
from obligation.application.tracking import (
    AddComment,
    AssignObligation,
    ChangeStatus,
    ReadObligation,
)
from obligation.domain.errors import (
    AssigneeNotMemberError,
    BusinessNotFoundError,
    ErrorReportDecidedError,
    ErrorReportNotFoundError,
    ErrorReportsDisabledError,
    IdentityUnavailableError,
    ObligationClosedError,
    ObligationNotFoundError,
    ObligationTenantRequiredError,
    ObligationWindowInvalidError,
    ProfileUnavailableError,
    RulebookUnavailableError,
)
from obligation.domain.flags import FeatureFlags
from obligation.domain.ports import ProfileNodes, RuleVersionReader, TenantMembers
from obligation.domain.repository import UnitOfWorkFactory
from obligation.infrastructure.flags import OpenFeatureFlags
from obligation.infrastructure.identity_client import HttpTenantMembers
from obligation.infrastructure.memory import MemoryStore
from obligation.infrastructure.profile_client import HttpProfileNodes
from obligation.infrastructure.repository import PostgresUnitOfWorkFactory
from obligation.infrastructure.rulebook_client import HttpRuleVersionReader
from obligation.settings import ObligationSettings
from obligation.wiring import Wiring
from py_common.app import create_app, module_app
from py_common.auth import TokenSource, service_auth_from
from py_common.auth.fastapi import Authenticator
from py_common.erasure import PostgresErasedTenants
from py_common.flags import configure_flags
from py_common.idempotency import IdempotencyStore, MemoryIdempotencyStore
from py_common.idempotency.sqlalchemy import SqlAlchemyIdempotencyStore

SERVICE_NAME = "obligation"
PROBLEM_STATUS: dict[type[DomainError], int] = {
    ObligationTenantRequiredError: 401,
    ObligationWindowInvalidError: 422,
    ObligationNotFoundError: 404,
    BusinessNotFoundError: 404,
    ErrorReportsDisabledError: 404,
    ErrorReportNotFoundError: 404,
    ErrorReportDecidedError: 409,
    ObligationClosedError: 409,
    InvalidTransitionError: 422,
    AssigneeNotMemberError: 422,
    RulebookUnavailableError: 503,
    IdentityUnavailableError: 503,
    ProfileUnavailableError: 503,
}


def wire(
    settings: ObligationSettings,
    *,
    rules: RuleVersionReader | None = None,
    members: TenantMembers | None = None,
    profiles: ProfileNodes | None = None,
    token_source: TokenSource | None = None,
    flags: FeatureFlags | None = None,
) -> Wiring:
    """The use cases on the store the settings name, reading the rulebook, the identity service
    and the profile service over HTTP unless ``rules``, ``members`` and ``profiles`` are
    given. Without ``flags`` the process-wide OpenFeature provider is configured from the
    settings and answers them (the report route's ``obligation.error_reports``)."""
    if flags is None:
        configure_flags(settings)
        flags = OpenFeatureFlags()
    unit_of_work: UnitOfWorkFactory
    ping: Callable[[], bool]
    idempotency: IdempotencyStore
    erased: ErasedTenants
    if settings.obligation_store == "memory":
        memory = MemoryStore()
        unit_of_work, ping, idempotency = memory, memory.ping, MemoryIdempotencyStore()
        erased = memory.erased
    else:
        postgres = PostgresUnitOfWorkFactory.from_url(settings.database_url)
        unit_of_work, ping = postgres, postgres.ping
        idempotency = SqlAlchemyIdempotencyStore(postgres.engine)
        erased = PostgresErasedTenants.pooled(settings.database_url)
    if rules is None or members is None or profiles is None:
        auth = service_auth_from(settings, token_source=token_source)
        rules = rules or HttpRuleVersionReader(settings.rulebook_url, auth=auth)
        members = members or HttpTenantMembers(settings.identity_url, auth=auth)
        profiles = profiles or HttpProfileNodes(settings.profile_url, auth=auth)

    async def store_ready() -> bool:
        return await run_in_threadpool(ping)

    return Wiring(
        settings=settings,
        unit_of_work=unit_of_work,
        store_ready=store_ready,
        idempotency=idempotency,
        materialise=MaterialiseObligations(unit_of_work),
        apply_deadline_change=ApplyDeadlineChange(unit_of_work),
        withdraw_rule=WithdrawRule(unit_of_work),
        close_obligation=CloseObligation(unit_of_work),
        list_obligations=ListObligations(unit_of_work),
        list_business_obligations=ListBusinessObligations(unit_of_work, profiles),
        read_obligation=ReadObligation(unit_of_work, rules),
        change_status=ChangeStatus(unit_of_work),
        assign=AssignObligation(unit_of_work, members),
        add_comment=AddComment(unit_of_work),
        report_error=ReportError(unit_of_work, flags),
        list_error_reports=ListErrorReports(unit_of_work),
        export_tenant_data=ExportTenantData(unit_of_work),
        erased_tenants=erased,
    )


def build_app(
    settings: ObligationSettings | None = None,
    *,
    rules: RuleVersionReader | None = None,
    members: TenantMembers | None = None,
    profiles: ProfileNodes | None = None,
    authenticator: Authenticator | None = None,
    token_source: TokenSource | None = None,
    flags: FeatureFlags | None = None,
) -> FastAPI:
    """``authenticator`` replaces the one ``CW_AUTH_MODE`` describes and ``token_source`` the
    service client's tokens; a process that hosts identity passes identity's own. ``rules``,
    ``members`` and ``profiles`` replace the rulebook, identity and profile clients, and
    ``flags`` the OpenFeature flags (tests and demos)."""
    settings = settings or ObligationSettings(service_name=SERVICE_NAME)
    wiring = wire(
        settings,
        rules=rules,
        members=members,
        profiles=profiles,
        token_source=token_source,
        flags=flags,
    )
    app = create_app(
        service_name=SERVICE_NAME,
        version=__version__,
        routers=[router, public_router, business_router],
        settings=settings,
        readiness_checks=[("store", wiring.store_ready)],
        problem_status=PROBLEM_STATUS,
        authenticator=authenticator,
        erased_tenants=wiring.erased_tenants,
    )
    app.state.wiring = wiring
    return app


def __getattr__(name: str) -> FastAPI:
    """``app`` is built on first access, so importing this module builds nothing."""
    return module_app(name, build_app)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("obligation.main:app", host="127.0.0.1", port=8005, reload=True)
