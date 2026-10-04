"""Composition root for the applicability-engine service.

Guide section 11: wiring of interfaces to implementations happens here, never inside the layers.
The use cases run on the Postgres unit of work (row-level security by tenant, events through the
outbox) and read the profile service and the rulebook over HTTP, every call with this service's
own access token once ``CW_SERVICE_CLIENT_SECRET`` is set, or with the token of ``token_source``
when the process that hosts the engine passes one (identity's issuer in the process); tests pass
their own ``Readers``. The caller and its tenant come from ``py_common.auth`` by ``CW_AUTH_MODE``
(``api.deps``). Idempotency keys live next to the decisions (``idempotency_key``, migration
0001), each key in its own short transaction. The ontology is the packaged one. The review
queue's routes run on the same units of work; the profile.updated consumer is the worker's
(``applicability_engine.worker``), which builds its readers with ``http_readers`` too.
"""

from collections.abc import Callable

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from applicability_engine import __version__
from applicability_engine.api.router import router
from applicability_engine.application.evaluate import EvaluateRule
from applicability_engine.application.queries import ListDecisions, ReadDecision
from applicability_engine.application.review import ListReviewItems, ResolveReviewItem
from applicability_engine.domain.errors import (
    ApplicabilityTenantRequiredError,
    BusinessNotFoundError,
    DecisionNotFoundError,
    DependencyUnavailableError,
    ReviewItemNotFoundError,
    ReviewItemResolvedError,
    RuleVersionNotFoundError,
    RuleVersionNotPublishedError,
)
from applicability_engine.domain.repository import UnitOfWorkFactory
from applicability_engine.infrastructure.memory import MemoryStore
from applicability_engine.infrastructure.profile_client import HttpProfiles
from applicability_engine.infrastructure.repository import PostgresUnitOfWorkFactory
from applicability_engine.infrastructure.rulebook_client import HttpRulebook
from applicability_engine.settings import ApplicabilityEngineSettings
from applicability_engine.wiring import Readers, Wiring
from domain_kernel.errors import DomainError
from domain_kernel.ontology import Ontology
from ontology import load as load_ontology
from py_common.app import create_app, module_app
from py_common.auth import TokenSource, service_auth_from
from py_common.auth.fastapi import Authenticator
from py_common.idempotency import IdempotencyStore, MemoryIdempotencyStore
from py_common.idempotency.sqlalchemy import SqlAlchemyIdempotencyStore

SERVICE_NAME = "applicability-engine"
PROBLEM_STATUS: dict[type[DomainError], int] = {
    ApplicabilityTenantRequiredError: 401,
    BusinessNotFoundError: 404,
    RuleVersionNotFoundError: 404,
    DecisionNotFoundError: 404,
    ReviewItemNotFoundError: 404,
    RuleVersionNotPublishedError: 409,
    ReviewItemResolvedError: 409,
    DependencyUnavailableError: 503,
}


def http_readers(
    settings: ApplicabilityEngineSettings, *, token_source: TokenSource | None = None
) -> Readers:
    auth = service_auth_from(settings, token_source=token_source)
    timeout = settings.applicability_engine_http_timeout_seconds
    return Readers(
        profiles=HttpProfiles(settings.profile_url, auth=auth, timeout_seconds=timeout),
        rulebook=HttpRulebook(
            settings.rulebook_url,
            auth=auth,
            timeout_seconds=timeout,
            cache_seconds=settings.applicability_engine_rules_cache_seconds,
        ),
    )


def wire(
    settings: ApplicabilityEngineSettings,
    readers: Readers | None = None,
    ontology: Ontology | None = None,
    *,
    token_source: TokenSource | None = None,
) -> Wiring:
    """Build the use cases on the store the settings name, reading over HTTP unless ``readers``
    are given, with the packaged ontology unless another is."""
    readers = readers or http_readers(settings, token_source=token_source)
    unit_of_work: UnitOfWorkFactory
    ping: Callable[[], bool]
    idempotency: IdempotencyStore
    if settings.applicability_engine_store == "memory":
        memory = MemoryStore()
        unit_of_work, ping, idempotency = memory, memory.ping, MemoryIdempotencyStore()
    else:
        postgres = PostgresUnitOfWorkFactory.from_url(settings.database_url)
        unit_of_work, ping = postgres, postgres.ping
        idempotency = SqlAlchemyIdempotencyStore(postgres.engine)

    async def store_ready() -> bool:
        return await run_in_threadpool(ping)

    return Wiring(
        settings=settings,
        unit_of_work=unit_of_work,
        store_ready=store_ready,
        idempotency=idempotency,
        evaluate=EvaluateRule(
            unit_of_work, readers.profiles, readers.rulebook, ontology or load_ontology()
        ),
        list_decisions=ListDecisions(unit_of_work),
        read_decision=ReadDecision(unit_of_work),
        list_review_items=ListReviewItems(unit_of_work),
        resolve_review_item=ResolveReviewItem(unit_of_work),
    )


def build_app(
    settings: ApplicabilityEngineSettings | None = None,
    *,
    readers: Readers | None = None,
    ontology: Ontology | None = None,
    authenticator: Authenticator | None = None,
    token_source: TokenSource | None = None,
) -> FastAPI:
    """``authenticator`` replaces the one ``CW_AUTH_MODE`` describes and ``token_source`` the
    service client's tokens; a process that hosts identity passes identity's own."""
    settings = settings or ApplicabilityEngineSettings(service_name=SERVICE_NAME)
    wiring = wire(settings, readers, ontology, token_source=token_source)
    app = create_app(
        service_name=SERVICE_NAME,
        version=__version__,
        routers=[router],
        settings=settings,
        readiness_checks=[("store", wiring.store_ready)],
        problem_status=PROBLEM_STATUS,
        authenticator=authenticator,
    )
    app.state.wiring = wiring
    return app


def __getattr__(name: str) -> FastAPI:
    """``app`` is built on first access, so importing this module builds nothing."""
    return module_app(name, build_app)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("applicability_engine.main:app", host="127.0.0.1", port=8004, reload=True)
