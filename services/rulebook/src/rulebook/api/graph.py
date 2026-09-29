"""The knowledge graph for readers such as the Q&A service: resolve a name, read an entity and
the clauses that mention it, follow relations, read a clause. Open reads."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from domain_kernel.ids import CanonicalEntityId, ClauseId, RuleVersionId
from domain_kernel.knowledge import EntityType, RelationKind
from py_common.problems import problem_responses
from rulebook.api.deps import Wired
from rulebook.api.read_schemas import (
    ClauseDetailOut,
    EntityOut,
    EntityResolutionOut,
    MentionedClauseOut,
    RelationOut,
)
from rulebook.domain.graph import RelationQuery

router = APIRouter(tags=["knowledge"])


# Declared before /entities/{entity_id}, which would otherwise try "resolve" as an id.
@router.get(
    "/entities/resolve",
    summary="Resolve a name to a canonical entity; always 200, with a status",
)
def resolve_entity(
    wired: Wired,
    entity_type: Annotated[EntityType, Query(alias="type")],
    name: Annotated[str, Query(max_length=400)],
) -> EntityResolutionOut:
    found = wired.resolve_entity.run(entity_type, name)
    return EntityResolutionOut.from_resolution(entity_type, name, found)


@router.get(
    "/entities/{entity_id}",
    summary="A canonical entity with its aliases",
    responses=problem_responses(404),
)
def read_entity(entity_id: UUID, wired: Wired) -> EntityOut:
    return EntityOut.from_record(wired.read_entity.run(CanonicalEntityId(entity_id)))


@router.get(
    "/entities/{entity_id}/clauses",
    summary="Clauses that mention an entity, newest document first",
    responses=problem_responses(404),
)
def list_entity_clauses(
    entity_id: UUID,
    wired: Wired,
    as_of: Annotated[
        date | None,
        Query(
            description=(
                "Only documents published on or before this date; each clause says whether its "
                "rule is out of force then"
            )
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[MentionedClauseOut]:
    found = wired.list_entity_clauses.run(CanonicalEntityId(entity_id), as_of, limit)
    return [MentionedClauseOut.from_mentioned(clause) for clause in found]


@router.get(
    "/relations",
    summary="Rule relations from a version, to a version or to an entity; name at least one",
    responses=problem_responses(422),
)
def list_relations(
    wired: Wired,
    from_rule_version_id: UUID | None = None,
    to_rule_version_id: UUID | None = None,
    to_entity_id: UUID | None = None,
    relation: RelationKind | None = None,
    published_only: Annotated[
        bool, Query(description="Only relations from versions that have been published")
    ] = True,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[RelationOut]:
    query = RelationQuery(
        from_rule_version_id=None
        if from_rule_version_id is None
        else RuleVersionId(from_rule_version_id),
        to_rule_version_id=None
        if to_rule_version_id is None
        else RuleVersionId(to_rule_version_id),
        to_entity_id=None if to_entity_id is None else CanonicalEntityId(to_entity_id),
        relation=relation,
        published_only=published_only,
        limit=limit,
    )
    return [RelationOut.from_record(record) for record in wired.list_rule_relations.run(query)]


@router.get(
    "/clauses/{clause_id}",
    summary="A clause with its document's regulator, type, reference, title and date",
    tags=["documents"],
    responses=problem_responses(404),
)
def read_clause(clause_id: UUID, wired: Wired) -> ClauseDetailOut:
    return ClauseDetailOut.from_detail(wired.read_clause.run(ClauseId(clause_id)))
