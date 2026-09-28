"""In-memory unit of work: the store for tests, demos and a rulebook without a database.

Changes made inside a unit of work become visible to others only when the block exits cleanly,
as with the Postgres store. Units of work run one at a time (a lock held for the whole block),
so two overlapping requests cannot both start from the same tables and lose a write. The
uniqueness rules are the database's: first write wins, a repeat is a no-op.
"""

import copy
import threading
from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field, replace
from uuid import UUID, uuid4

from domain_kernel.ids import CanonicalEntityId, ClauseId, DocumentId, RuleId, RuleVersionId
from domain_kernel.knowledge import EntityType, RelationKind, RuleRelation
from domain_kernel.status import RuleVersionStatus
from rulebook.domain.documents import StoredClause, StoredDocument
from rulebook.domain.relations import CandidateStatus, RelationCandidate
from rulebook.domain.repository import KnowledgeUnitOfWork
from rulebook.domain.review import EntityReviewItem, MentionGroup, ReviewStatus
from rulebook.domain.runs import ExtractionRun, RuleSummary

EXAMPLES_PER_GROUP = 5


@dataclass
class _Entity:
    entity_type: EntityType
    name: str
    aliases: list[str] = field(default_factory=list)


@dataclass
class _Rule:
    rule_id: UUID
    rule_key: str
    regulator: str
    title: str


@dataclass
class _Tables:
    documents: dict[DocumentId, StoredDocument] = field(default_factory=dict)
    clauses: dict[ClauseId, StoredClause] = field(default_factory=dict)
    entities: dict[CanonicalEntityId, _Entity] = field(default_factory=dict)
    mentions: dict[tuple[ClauseId, CanonicalEntityId, int], tuple[str, int, str, str]] = field(
        default_factory=dict
    )
    reviews: dict[UUID, EntityReviewItem] = field(default_factory=dict)
    candidates: dict[UUID, RelationCandidate] = field(default_factory=dict)
    relations: dict[UUID, tuple[RuleRelation, UUID | None]] = field(default_factory=dict)
    rules: dict[str, _Rule] = field(default_factory=dict)
    versions: dict[RuleVersionId, tuple[UUID, RuleVersionStatus]] = field(default_factory=dict)
    runs: dict[UUID, ExtractionRun] = field(default_factory=dict)

    def copy(self) -> "_Tables":
        return copy.deepcopy(self)


class MemoryDocumentRepository:
    def __init__(self, tables: _Tables) -> None:
        self._tables = tables

    def get(self, document_id: DocumentId) -> StoredDocument | None:
        return self._tables.documents.get(document_id)

    def add(self, document: StoredDocument) -> bool:
        if document.document_id in self._tables.documents:
            return False
        self._tables.documents[document.document_id] = document
        return True

    def clauses(self, document_id: DocumentId) -> tuple[StoredClause, ...]:
        found = [c for c in self._tables.clauses.values() if c.document_id == document_id]
        return tuple(sorted(found, key=lambda clause: clause.ordinal))

    def add_clauses(self, clauses: Sequence[StoredClause]) -> None:
        for clause in clauses:
            self._tables.clauses.setdefault(clause.clause_id, clause)


class MemoryEntityRepository:
    def __init__(self, tables: _Tables) -> None:
        self._tables = tables

    def by_name(self, entity_type: EntityType, name: str) -> CanonicalEntityId | None:
        return next(
            (
                entity_id
                for entity_id, entity in self._tables.entities.items()
                if entity.entity_type is entity_type and entity.name == name
            ),
            None,
        )

    def by_alias(self, entity_type: EntityType, alias: str) -> Sequence[CanonicalEntityId]:
        return [
            entity_id
            for entity_id, entity in self._tables.entities.items()
            if entity.entity_type is entity_type and alias in entity.aliases
        ]

    def get(self, entity_id: CanonicalEntityId) -> tuple[EntityType, str] | None:
        entity = self._tables.entities.get(entity_id)
        return None if entity is None else (entity.entity_type, entity.name)

    def create_or_get(self, entity_type: EntityType, name: str) -> tuple[CanonicalEntityId, bool]:
        existing = self.by_name(entity_type, name)
        if existing is not None:
            return existing, False
        entity_id = CanonicalEntityId.new()
        self._tables.entities[entity_id] = _Entity(entity_type, name)
        return entity_id, True

    def add_alias(self, entity_id: CanonicalEntityId, alias: str) -> bool:
        entity = self._tables.entities[entity_id]
        if alias in entity.aliases:
            return False
        entity.aliases.append(alias)
        return True


class MemoryMentionRepository:
    def __init__(self, tables: _Tables) -> None:
        self._tables = tables

    def add(
        self,
        clause_id: ClauseId,
        entity_id: CanonicalEntityId,
        mention_text: str,
        span_start: int,
        span_end: int,
        *,
        method: str,
        extractor: str,
    ) -> bool:
        key = (clause_id, entity_id, span_start)
        if key in self._tables.mentions:
            return False
        self._tables.mentions[key] = (mention_text, span_end, method, extractor)
        return True


class MemoryReviewRepository:
    def __init__(self, tables: _Tables) -> None:
        self._tables = tables

    def enqueue(self, item: EntityReviewItem) -> bool:
        if item.review_id in self._tables.reviews:
            return False
        self._tables.reviews[item.review_id] = item
        return True

    def open_groups(
        self, entity_type: EntityType | None, limit: int, after: tuple[str, str] | None
    ) -> Sequence[MentionGroup]:
        groups: dict[tuple[str, str], list[EntityReviewItem]] = {}
        for item in self._tables.reviews.values():
            if item.status is not ReviewStatus.OPEN:
                continue
            if entity_type is not None and item.entity_type is not entity_type:
                continue
            key = (item.entity_type.value, item.proposed_name)
            if after is not None and key <= after:
                continue
            groups.setdefault(key, []).append(item)
        result: list[MentionGroup] = []
        for key in sorted(groups)[:limit]:
            items = sorted(groups[key], key=lambda i: (str(i.document_id), str(i.clause_id)))
            result.append(
                MentionGroup(
                    entity_type=EntityType(key[0]),
                    proposed_name=key[1],
                    open_count=len(items),
                    examples=tuple(items[:EXAMPLES_PER_GROUP]),
                )
            )
        return result

    def lock_group(
        self, entity_type: EntityType, proposed_name: str
    ) -> tuple[EntityReviewItem, ...]:
        return tuple(
            item
            for item in self._tables.reviews.values()
            if item.entity_type is entity_type and item.proposed_name == proposed_name
        )

    def save(self, item: EntityReviewItem) -> None:
        self._tables.reviews[item.review_id] = item


class MemoryCandidateRepository:
    def __init__(self, tables: _Tables) -> None:
        self._tables = tables

    def add(self, candidate: RelationCandidate) -> bool:
        if candidate.candidate_id in self._tables.candidates:
            return False
        self._tables.candidates[candidate.candidate_id] = candidate
        return True

    def lock(self, candidate_id: UUID) -> RelationCandidate | None:
        return self._tables.candidates.get(candidate_id)

    def page(
        self,
        status: CandidateStatus | None,
        document_id: DocumentId | None,
        limit: int,
        after: UUID | None,
    ) -> Sequence[RelationCandidate]:
        found = [
            c
            for c in self._tables.candidates.values()
            if (status is None or c.status is status)
            and (document_id is None or c.document_id == document_id)
            and (after is None or str(c.candidate_id) > str(after))
        ]
        return sorted(found, key=lambda c: str(c.candidate_id))[:limit]

    def save(self, candidate: RelationCandidate) -> None:
        self._tables.candidates[candidate.candidate_id] = candidate

    def set_target_entity(
        self, entity_type: EntityType, name: str, entity_id: CanonicalEntityId
    ) -> int:
        updated = 0
        for candidate_id, candidate in list(self._tables.candidates.items()):
            if (
                candidate.status is CandidateStatus.OPEN
                and candidate.target_entity_id is None
                and candidate.target_type is entity_type
                and candidate.target_name == name
            ):
                self._tables.candidates[candidate_id] = replace(
                    candidate, target_entity_id=entity_id
                )
                updated += 1
        return updated


class MemoryRelationRepository:
    def __init__(self, tables: _Tables) -> None:
        self._tables = tables

    def add(self, relation: RuleRelation, *, relation_id: UUID, candidate_id: UUID | None) -> bool:
        edge = _edge(relation)
        if relation_id in self._tables.relations or any(
            _edge(stored) == edge for stored, _ in self._tables.relations.values()
        ):
            return False
        self._tables.relations[relation_id] = (relation, candidate_id)
        return True

    def supersedes_edges(self) -> Mapping[RuleVersionId, frozenset[RuleVersionId]]:
        edges: dict[RuleVersionId, set[RuleVersionId]] = {}
        for relation, _ in self._tables.relations.values():
            if relation.relation is RelationKind.SUPERSEDES and isinstance(
                relation.target, RuleVersionId
            ):
                edges.setdefault(relation.from_rule_version_id, set()).add(relation.target)
        return {source: frozenset(targets) for source, targets in edges.items()}


def _edge(relation: RuleRelation) -> tuple[str, str, str, str, str]:
    return (
        str(relation.from_rule_version_id),
        relation.relation.value,
        relation.to_kind,
        relation.to_ref,
        str(relation.evidence_clause_id),
    )


class MemoryRuleCatalog:
    def __init__(self, tables: _Tables) -> None:
        self._tables = tables

    def list_rules(self) -> tuple[RuleSummary, ...]:
        return tuple(
            RuleSummary(rule.rule_key, rule.rule_id, rule.regulator, rule.title)
            for rule in sorted(self._tables.rules.values(), key=lambda r: r.rule_key)
        )

    def rule_id(self, rule_key: str) -> UUID | None:
        rule = self._tables.rules.get(rule_key)
        return None if rule is None else rule.rule_id

    def version_status(self, rule_version_id: RuleVersionId) -> RuleVersionStatus | None:
        version = self._tables.versions.get(rule_version_id)
        return None if version is None else version[1]


class MemoryRunRepository:
    def __init__(self, tables: _Tables) -> None:
        self._tables = tables

    def record(self, run: ExtractionRun) -> bool:
        if run.run_id in self._tables.runs:
            return False
        self._tables.runs[run.run_id] = run
        return True


class MemoryUnitOfWork:
    def __init__(self, tables: _Tables) -> None:
        self._documents = MemoryDocumentRepository(tables)
        self._entities = MemoryEntityRepository(tables)
        self._mentions = MemoryMentionRepository(tables)
        self._reviews = MemoryReviewRepository(tables)
        self._candidates = MemoryCandidateRepository(tables)
        self._relations = MemoryRelationRepository(tables)
        self._rules = MemoryRuleCatalog(tables)
        self._runs = MemoryRunRepository(tables)

    @property
    def documents(self) -> MemoryDocumentRepository:
        return self._documents

    @property
    def entities(self) -> MemoryEntityRepository:
        return self._entities

    @property
    def mentions(self) -> MemoryMentionRepository:
        return self._mentions

    @property
    def reviews(self) -> MemoryReviewRepository:
        return self._reviews

    @property
    def candidates(self) -> MemoryCandidateRepository:
        return self._candidates

    @property
    def relations(self) -> MemoryRelationRepository:
        return self._relations

    @property
    def rules(self) -> MemoryRuleCatalog:
        return self._rules

    @property
    def runs(self) -> MemoryRunRepository:
        return self._runs


class MemoryKnowledgeStore:
    """``store()`` opens a unit of work on a copy of the tables; a clean exit publishes it."""

    def __init__(self) -> None:
        self._tables = _Tables()
        self._lock = threading.Lock()

    def __call__(self) -> AbstractContextManager[KnowledgeUnitOfWork]:
        return self._open()

    @contextmanager
    def _open(self) -> Iterator[KnowledgeUnitOfWork]:
        with self._lock:
            working = self._tables.copy()
            yield MemoryUnitOfWork(working)
            self._tables = working

    def ping(self) -> bool:
        return True

    def add_rule(
        self,
        rule_key: str,
        *,
        title: str = "",
        regulator: str = "CBIC",
        status: RuleVersionStatus = RuleVersionStatus.DRAFT,
    ) -> tuple[RuleId, RuleVersionId]:
        """A rule with one version, for tests and demos (the seed command writes real ones)."""
        rule_id, version_id = RuleId(uuid4()), RuleVersionId.new()
        with self._lock:
            self._tables.rules[rule_key] = _Rule(rule_id.value, rule_key, regulator, title)
            self._tables.versions[version_id] = (rule_id.value, status)
        return rule_id, version_id

    def entity_names(self) -> dict[CanonicalEntityId, tuple[EntityType, str, tuple[str, ...]]]:
        with self._lock:
            return {
                entity_id: (entity.entity_type, entity.name, tuple(entity.aliases))
                for entity_id, entity in self._tables.entities.items()
            }

    def mention_count(self) -> int:
        with self._lock:
            return len(self._tables.mentions)

    def rule_relations(self) -> list[tuple[RuleRelation, UUID | None]]:
        with self._lock:
            return list(self._tables.relations.values())

    def runs(self) -> list[ExtractionRun]:
        with self._lock:
            return list(self._tables.runs.values())
