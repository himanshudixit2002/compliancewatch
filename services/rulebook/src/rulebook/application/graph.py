"""Read the knowledge graph: resolve a name to an entity, read an entity and the clauses that
mention it, follow relations, read a clause.

A resolve always answers with a status: a caller asking about "GSTR 3B" learns that the name
resolved, is ambiguous (with the entities that share it), names nothing, or needs its statute.
"""

from collections.abc import Sequence
from dataclasses import replace
from datetime import date

from domain_kernel.ids import CanonicalEntityId, ClauseId
from domain_kernel.knowledge import EntityType, normalise_name
from rulebook.domain.alignment import Resolved, ReviewReason, resolve
from rulebook.domain.errors import ClauseNotStoredError, UnknownEntityError
from rulebook.domain.graph import (
    STATUS_BY_REASON,
    ClauseDetail,
    EntityRecord,
    EntityResolution,
    MentionedClause,
    RelationQuery,
    RelationRecord,
    ResolutionStatus,
)
from rulebook.domain.repository import KnowledgeUnitOfWorkFactory

MAX_CLAUSES = 200
MAX_RELATIONS = 500


class ResolveEntity:
    def __init__(self, unit_of_work: KnowledgeUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self, entity_type: EntityType, name: str) -> EntityResolution:
        normalised = normalise_name(entity_type, name)
        with self._unit_of_work() as uow:
            outcome = resolve(entity_type, normalised, uow.entities)
            if isinstance(outcome, Resolved):
                entity = uow.entities.describe(outcome.entity_id)
                return EntityResolution(ResolutionStatus.RESOLVED, normalised, entity)
            candidates: tuple[EntityRecord, ...] = ()
            if outcome.reason is ReviewReason.AMBIGUOUS_ALIAS:
                shared = dict.fromkeys(uow.entities.by_alias(entity_type, normalised))
                candidates = tuple(
                    record
                    for record in (uow.entities.describe(entity_id) for entity_id in shared)
                    if record is not None
                )
            return EntityResolution(
                STATUS_BY_REASON[outcome.reason], normalised, candidates=candidates
            )


class ReadEntity:
    def __init__(self, unit_of_work: KnowledgeUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self, entity_id: CanonicalEntityId) -> EntityRecord:
        with self._unit_of_work() as uow:
            record = uow.entities.describe(entity_id)
        if record is None:
            raise UnknownEntityError(f"entity {entity_id} does not exist")
        return record


class ListEntityClauses:
    def __init__(self, unit_of_work: KnowledgeUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(
        self, entity_id: CanonicalEntityId, as_of: date | None = None, limit: int = 50
    ) -> Sequence[MentionedClause]:
        with self._unit_of_work() as uow:
            if uow.entities.describe(entity_id) is None:
                raise UnknownEntityError(f"entity {entity_id} does not exist")
            return uow.mentions.clauses_mentioning(
                entity_id, as_of, min(max(limit, 1), MAX_CLAUSES)
            )


class ListRelations:
    def __init__(self, unit_of_work: KnowledgeUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self, query: RelationQuery) -> Sequence[RelationRecord]:
        with self._unit_of_work() as uow:
            return uow.relations.find(replace(query, limit=min(query.limit, MAX_RELATIONS)))


class ReadClause:
    def __init__(self, unit_of_work: KnowledgeUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self, clause_id: ClauseId) -> ClauseDetail:
        with self._unit_of_work() as uow:
            detail = uow.documents.clause(clause_id)
        if detail is None:
            raise ClauseNotStoredError(f"clause {clause_id} is not stored")
        return detail
