"""Composition root for the rulebook service.

Guide section 11: wiring of interfaces to implementations happens here, never inside the layers.
The engine behind the Postgres store connects lazily, so importing the module (``make openapi``)
needs no database.
"""

from collections.abc import Callable

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from domain_kernel.errors import DomainError, InvalidRelationError
from py_common.app import create_app
from rulebook import __version__
from rulebook.api.router import router
from rulebook.application.alignment import AlignMentions
from rulebook.application.documents import ReadDocument, RegisterDocument
from rulebook.application.graph import (
    ListEntityClauses,
    ListRelations,
    ReadClause,
    ReadEntity,
    ResolveEntity,
)
from rulebook.application.relations import (
    ApproveRelationCandidate,
    ListRelationCandidates,
    ListRules,
    RejectRelationCandidate,
    StageRelationCandidates,
)
from rulebook.application.review import DecideMentionGroup, ListGroupItems, ListMentionGroups
from rulebook.application.rule_versions import ListCitations, ListRulesInForce, ReadRuleVersion
from rulebook.application.search import ListUnembeddedClauses, SearchClauses, StoreEmbeddings
from rulebook.domain.errors import (
    CandidateClosedError,
    CandidateNotFoundError,
    ClauseNotStoredError,
    DocumentConflictError,
    DocumentIdMismatchError,
    EmbeddingDimensionError,
    EntityTypeMismatchError,
    MentionSpanMismatchError,
    NonCanonicalNameError,
    ReviewGroupClosedError,
    ReviewGroupNotFoundError,
    RuleVersionNotEditableError,
    SupersessionCycleError,
    TargetUnresolvedError,
    TargetVersionRequiredError,
    UnknownClauseError,
    UnknownDocumentError,
    UnknownEntityError,
    UnknownRuleVersionError,
    WritesDisabledError,
    WriteTokenInvalidError,
)
from rulebook.domain.repository import KnowledgeUnitOfWorkFactory
from rulebook.infrastructure.knowledge_repository import PostgresKnowledgeUnitOfWorkFactory
from rulebook.infrastructure.memory import MemoryKnowledgeStore
from rulebook.settings import RulebookSettings
from rulebook.wiring import Wiring

SERVICE_NAME = "rulebook"

PROBLEM_STATUS: dict[type[DomainError], int] = {
    DocumentIdMismatchError: 422,
    DocumentConflictError: 409,
    UnknownDocumentError: 404,
    WriteTokenInvalidError: 401,
    WritesDisabledError: 503,
    UnknownClauseError: 422,
    MentionSpanMismatchError: 422,
    NonCanonicalNameError: 422,
    ReviewGroupNotFoundError: 404,
    ReviewGroupClosedError: 409,
    UnknownEntityError: 404,
    EntityTypeMismatchError: 422,
    CandidateNotFoundError: 404,
    CandidateClosedError: 409,
    TargetUnresolvedError: 409,
    TargetVersionRequiredError: 422,
    UnknownRuleVersionError: 404,
    RuleVersionNotEditableError: 409,
    SupersessionCycleError: 409,
    InvalidRelationError: 422,
    ClauseNotStoredError: 404,
    EmbeddingDimensionError: 422,
}


def build_wiring(settings: RulebookSettings) -> Wiring:
    unit_of_work: KnowledgeUnitOfWorkFactory
    ping: Callable[[], bool]
    if settings.rulebook_store == "memory":
        memory = MemoryKnowledgeStore()
        unit_of_work, ping = memory, memory.ping
    else:
        postgres = PostgresKnowledgeUnitOfWorkFactory.from_url(settings.database_url)
        unit_of_work, ping = postgres, postgres.ping

    async def store_ready() -> bool:
        return await run_in_threadpool(ping)

    return Wiring(
        settings=settings,
        unit_of_work=unit_of_work,
        store_ready=store_ready,
        register_document=RegisterDocument(unit_of_work),
        read_document=ReadDocument(unit_of_work),
        align_mentions=AlignMentions(unit_of_work),
        list_entity_groups=ListMentionGroups(unit_of_work),
        list_group_items=ListGroupItems(unit_of_work),
        decide_entity_group=DecideMentionGroup(unit_of_work),
        stage_relations=StageRelationCandidates(unit_of_work),
        list_relations=ListRelationCandidates(unit_of_work),
        approve_relation=ApproveRelationCandidate(unit_of_work),
        reject_relation=RejectRelationCandidate(unit_of_work),
        list_rules=ListRules(unit_of_work),
        list_rules_in_force=ListRulesInForce(unit_of_work),
        read_rule_version=ReadRuleVersion(unit_of_work),
        list_citations=ListCitations(unit_of_work),
        resolve_entity=ResolveEntity(unit_of_work),
        read_entity=ReadEntity(unit_of_work),
        list_entity_clauses=ListEntityClauses(unit_of_work),
        list_rule_relations=ListRelations(unit_of_work),
        read_clause=ReadClause(unit_of_work),
        store_embeddings=StoreEmbeddings(unit_of_work),
        list_unembedded=ListUnembeddedClauses(unit_of_work),
        search_clauses=SearchClauses(unit_of_work),
    )


def build_app(settings: RulebookSettings | None = None) -> FastAPI:
    settings = settings or RulebookSettings(service_name=SERVICE_NAME)
    wiring = build_wiring(settings)
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

    uvicorn.run("rulebook.main:app", host="127.0.0.1", port=8003, reload=True)
