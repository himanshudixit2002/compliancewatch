"""In-memory unit of work: the store for tests, demos and a rulebook without a database.

Changes made inside a unit of work become visible to others only when the block exits cleanly,
as with the Postgres store. Units of work run one at a time (a lock held for the whole block),
so two overlapping requests cannot both start from the same tables and lose a write. The
uniqueness rules are the database's: first write wins, a repeat is a no-op.
"""

import copy
import math
import re
import threading
from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from uuid import UUID, uuid4

from domain_kernel.events import utc_now
from domain_kernel.ids import CanonicalEntityId, ClauseId, DocumentId, RuleId, RuleVersionId
from domain_kernel.knowledge import EntityRef, EntityType, RelationKind, RuleRelation
from domain_kernel.ontology import AttributeLevel
from domain_kernel.status import RuleVersionStatus
from domain_kernel.vectors import ClauseFilter, Vector
from rulebook.domain.documents import StoredClause, StoredDocument
from rulebook.domain.graph import (
    ClauseDetail,
    EntityRecord,
    MentionedClause,
    MentionSpan,
    RelationQuery,
    RelationRecord,
)
from rulebook.domain.relations import CandidateStatus, RelationCandidate
from rulebook.domain.repository import KnowledgeUnitOfWork
from rulebook.domain.review import EntityReviewItem, MentionGroup, ReviewStatus
from rulebook.domain.rule_versions import (
    IN_FORCE_STATUSES,
    CitationRecord,
    RuleVersionRecord,
    in_force,
)
from rulebook.domain.runs import ExtractionRun, RuleSummary
from rulebook.domain.search import CitedClause, ClauseEmbedding
from rulebook.domain.seed import SeedStatus

EXAMPLES_PER_GROUP = 5
TEST_EFFECTIVE_FROM = date(2026, 4, 1)
"""Where a test version starts when the test does not say: a date, not a regulatory fact."""
_TOKEN = re.compile(r"[\w\u0900-\u097f]+")
"""A word: letters, digits and Devanagari marks, so a Hindi word stays one token."""
STOP_WORDS = frozenset({"a", "an", "and", "for", "in", "is", "of", "on", "or", "the", "to"})


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
    level: AttributeLevel = AttributeLevel.REGISTRATION


@dataclass
class _Version:
    rule_id: UUID
    rule_key: str
    version: int
    status: RuleVersionStatus
    title: str
    summary: str
    specification: dict[str, object]
    obligation_template: dict[str, object]
    recurrence: dict[str, object] | None
    effective_from: date
    effective_to: date | None
    source: dict[str, object] = field(default_factory=dict)
    seed_status: SeedStatus = SeedStatus.NEEDS_REVIEW
    todo: tuple[str, ...] = ()
    published_at: datetime | None = None


@dataclass
class _Citation:
    rule_version_id: RuleVersionId
    clause_id: ClauseId
    quote: str
    verified: bool
    match_score: float | None
    verified_at: datetime | None


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
    versions: dict[RuleVersionId, _Version] = field(default_factory=dict)
    citations: dict[UUID, _Citation] = field(default_factory=dict)
    embeddings: dict[tuple[ClauseId, str], Vector] = field(default_factory=dict)
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

    def clause(self, clause_id: ClauseId) -> ClauseDetail | None:
        clause = self._tables.clauses.get(clause_id)
        if clause is None:
            return None
        return ClauseDetail(clause, self._tables.documents[clause.document_id])


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

    def describe(self, entity_id: CanonicalEntityId) -> EntityRecord | None:
        entity = self._tables.entities.get(entity_id)
        if entity is None:
            return None
        return EntityRecord(entity_id, entity.entity_type, entity.name, tuple(entity.aliases))


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

    def entity_at(
        self, clause_id: ClauseId, span_start: int, entity_type: EntityType
    ) -> CanonicalEntityId | None:
        return next(
            (
                entity_id
                for (clause, entity_id, start) in sorted(self._tables.mentions, key=str)
                if clause == clause_id
                and start == span_start
                and self._tables.entities[entity_id].entity_type is entity_type
            ),
            None,
        )

    def clauses_mentioning(
        self, entity_id: CanonicalEntityId, as_of: date | None, limit: int
    ) -> Sequence[MentionedClause]:
        spans: dict[ClauseId, list[MentionSpan]] = {}
        for (clause_id, mentioned, start), (text, end, _, _) in self._tables.mentions.items():
            if mentioned == entity_id:
                spans.setdefault(clause_id, []).append(MentionSpan(text, start, end))
        found: list[MentionedClause] = []
        for clause_id, mentions in spans.items():
            clause = self._tables.clauses[clause_id]
            document = self._tables.documents[clause.document_id]
            if as_of is not None and (
                document.published_at is None or document.published_at > as_of
            ):
                continue
            ordered = tuple(sorted(mentions, key=lambda span: span.span_start))
            found.append(MentionedClause(ClauseDetail(clause, document), ordered))
        return sorted(found, key=_newest_first)[:limit]


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

    def group_items(
        self, entity_type: EntityType, proposed_name: str
    ) -> tuple[EntityReviewItem, ...]:
        return tuple(
            sorted(
                (
                    item
                    for item in self.lock_group(entity_type, proposed_name)
                    if item.status is ReviewStatus.OPEN
                ),
                key=lambda item: str(item.review_id),
            )
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

    def set_target_entity_at(
        self,
        clause_id: ClauseId,
        span_start: int,
        entity_type: EntityType,
        entity_id: CanonicalEntityId,
    ) -> int:
        updated = 0
        for candidate_id, candidate in list(self._tables.candidates.items()):
            if (
                candidate.status is CandidateStatus.OPEN
                and candidate.target_entity_id is None
                and candidate.target_type is entity_type
                and candidate.target_clause_id == clause_id
                and candidate.target_span_start == span_start
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

    def lock_supersession(self) -> None:
        """Units of work already run one at a time here."""

    def find(self, query: RelationQuery) -> Sequence[RelationRecord]:
        found: list[RelationRecord] = []
        for relation_id, (relation, candidate_id) in sorted(
            self._tables.relations.items(), key=lambda item: str(item[0])
        ):
            record = self._record(relation_id, relation, candidate_id)
            source = self._tables.versions.get(record.from_rule_version_id)
            if (
                (query.from_rule_version_id in (None, record.from_rule_version_id))
                and (query.to_rule_version_id in (None, record.to_rule_version_id))
                and (query.to_entity_id in (None, record.to_entity_id))
                and (query.relation in (None, record.relation))
                and not (
                    query.published_only
                    and (source is None or source.status not in IN_FORCE_STATUSES)
                )
            ):
                found.append(record)
        return found[: query.limit]

    def _record(
        self, relation_id: UUID, relation: RuleRelation, candidate_id: UUID | None
    ) -> RelationRecord:
        evidence = self._tables.clauses[relation.evidence_clause_id]
        target = relation.target
        candidate = None if candidate_id is None else self._tables.candidates.get(candidate_id)
        return RelationRecord(
            relation_id=relation_id,
            from_rule_version_id=relation.from_rule_version_id,
            relation=relation.relation,
            to_kind=relation.to_kind,
            to_ref=relation.to_ref,
            to_rule_version_id=target if isinstance(target, RuleVersionId) else None,
            to_entity_id=target.entity_id if isinstance(target, EntityRef) else None,
            evidence_clause_id=evidence.clause_id,
            evidence_clause_ref=evidence.clause_ref,
            evidence_document_id=evidence.document_id,
            candidate_id=candidate_id,
            period_label=None if candidate is None else candidate.period_label,
            new_due_on=None if candidate is None else candidate.new_due_on,
        )


def _newest_first(found: MentionedClause) -> tuple[bool, int, str, int]:
    """Newest document first, undated ones last, then by document and clause order."""
    published = found.detail.document.published_at
    return (
        published is None,
        0 if published is None else -published.toordinal(),
        str(found.detail.document.document_id),
        found.detail.clause.ordinal,
    )


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
        return None if version is None else version.status


class MemoryRuleVersionRepository:
    def __init__(self, tables: _Tables) -> None:
        self._tables = tables

    def in_force(
        self,
        as_of: date,
        *,
        rule_key: str | None,
        regulator: str | None,
        limit: int,
        after: str | None,
    ) -> Sequence[RuleVersionRecord]:
        found = [
            record
            for record in (
                _version_record(self._tables, v_id, v) for v_id, v in self._tables.versions.items()
            )
            if in_force(record, as_of)
            and rule_key in (None, record.rule_key)
            and regulator in (None, record.regulator)
            and (after is None or record.rule_key > after)
        ]
        return sorted(found, key=lambda record: (record.rule_key, record.version))[:limit]

    def get(self, rule_version_id: RuleVersionId) -> RuleVersionRecord | None:
        version = self._tables.versions.get(rule_version_id)
        return None if version is None else _version_record(self._tables, rule_version_id, version)


class MemoryClauseIndex:
    """Token overlap for the lexical leg, cosine similarity for the vector leg."""

    def __init__(self, tables: _Tables) -> None:
        self._tables = tables

    def store(self, model: str, embeddings: Sequence[ClauseEmbedding]) -> tuple[int, int]:
        stored = 0
        for embedding in embeddings:
            key = (embedding.clause_id, model)
            if key not in self._tables.embeddings:
                self._tables.embeddings[key] = embedding.vector
                stored += 1
        return stored, len(embeddings) - stored

    def unknown_clauses(self, clause_ids: Sequence[ClauseId]) -> frozenset[ClauseId]:
        return frozenset(c for c in clause_ids if c not in self._tables.clauses)

    def unembedded(
        self, model: str, document_id: DocumentId | None, limit: int, after: ClauseId | None
    ) -> Sequence[ClauseDetail]:
        found = [
            ClauseDetail(clause, self._tables.documents[clause.document_id])
            for clause in sorted(self._tables.clauses.values(), key=lambda c: str(c.clause_id))
            if (clause.clause_id, model) not in self._tables.embeddings
            and document_id in (None, clause.document_id)
            and (after is None or str(clause.clause_id) > str(after))
        ]
        return found[:limit]

    def lexical(self, text: str, filters: ClauseFilter, pool: int) -> Sequence[ClauseId]:
        wanted = _tokens(text)
        scored = [
            (len(wanted & _tokens(clause.text)), clause.clause_id)
            for clause in self._tables.clauses.values()
            if _passes(self._tables.documents[clause.document_id], filters)
        ]
        ranked = sorted((s for s in scored if s[0]), key=lambda s: (-s[0], str(s[1])))
        return [clause_id for _, clause_id in ranked[:pool]]

    def nearest(
        self, vector: Vector, model: str, filters: ClauseFilter, pool: int
    ) -> Sequence[ClauseId]:
        scored = [
            (_cosine(vector, stored), clause_id)
            for (clause_id, stored_model), stored in self._tables.embeddings.items()
            if stored_model == model
            and _passes(
                self._tables.documents[self._tables.clauses[clause_id].document_id], filters
            )
        ]
        ranked = sorted(scored, key=lambda s: (-s[0], str(s[1])))
        return [clause_id for _, clause_id in ranked[:pool]]

    def hits(
        self, clause_ids: Sequence[ClauseId], as_of: date | None
    ) -> Mapping[ClauseId, CitedClause]:
        found: dict[ClauseId, CitedClause] = {}
        for clause_id in clause_ids:
            clause = self._tables.clauses[clause_id]
            citing = {
                citation.rule_version_id
                for citation in self._tables.citations.values()
                if citation.clause_id == clause_id
                and citation.verified
                and _cited_in_force(self._tables, citation.rule_version_id, as_of)
            }
            found[clause_id] = CitedClause(
                ClauseDetail(clause, self._tables.documents[clause.document_id]),
                tuple(sorted(citing, key=str)),
            )
        return found


def _cited_in_force(tables: _Tables, rule_version_id: RuleVersionId, as_of: date | None) -> bool:
    version = tables.versions.get(rule_version_id)
    if version is None or version.status not in IN_FORCE_STATUSES:
        return False
    return as_of is None or in_force(_version_record(tables, rule_version_id, version), as_of)


def _tokens(text: str) -> frozenset[str]:
    return frozenset(t for t in _TOKEN.findall(text.casefold()) if t not in STOP_WORDS)


def _cosine(first: Vector, second: Vector) -> float:
    dot = sum(a * b for a, b in zip(first, second, strict=True))
    return dot / (math.hypot(*first) * math.hypot(*second))


def _passes(document: StoredDocument, filters: ClauseFilter) -> bool:
    return (
        filters.regulator in (None, document.regulator)
        and (not filters.doc_types or document.doc_type in filters.doc_types)
        and (
            filters.as_of is None
            or (document.published_at is not None and document.published_at <= filters.as_of)
        )
    )


def _version_record(
    tables: _Tables, rule_version_id: RuleVersionId, version: _Version
) -> RuleVersionRecord:
    rule = tables.rules[version.rule_key]
    return RuleVersionRecord(
        rule_version_id=rule_version_id,
        rule_id=RuleId(version.rule_id),
        rule_key=version.rule_key,
        regulator=rule.regulator,
        level=rule.level,
        version=version.version,
        status=version.status,
        title=version.title,
        summary=version.summary,
        specification=version.specification,
        obligation_template=version.obligation_template,
        recurrence=version.recurrence,
        effective_from=version.effective_from,
        effective_to=version.effective_to,
        source=version.source,
        seed_status=version.seed_status,
        todo=version.todo,
        published_at=version.published_at,
    )


class MemoryCitationRepository:
    def __init__(self, tables: _Tables) -> None:
        self._tables = tables

    def for_version(self, rule_version_id: RuleVersionId) -> tuple[CitationRecord, ...]:
        found: list[tuple[tuple[str, int, str], CitationRecord]] = []
        for citation_id, citation in self._tables.citations.items():
            if citation.rule_version_id != rule_version_id:
                continue
            clause = self._tables.clauses[citation.clause_id]
            record = CitationRecord(
                citation_id=citation_id,
                rule_version_id=rule_version_id,
                clause_id=clause.clause_id,
                document_id=clause.document_id,
                clause_ref=clause.clause_ref,
                quote=citation.quote,
                verified=citation.verified,
                match_score=citation.match_score,
                verified_at=citation.verified_at,
            )
            found.append(((str(clause.document_id), clause.ordinal, str(citation_id)), record))
        return tuple(record for _, record in sorted(found, key=lambda item: item[0]))


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
        self._rule_versions = MemoryRuleVersionRepository(tables)
        self._citations = MemoryCitationRepository(tables)
        self._index = MemoryClauseIndex(tables)
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
    def rule_versions(self) -> MemoryRuleVersionRepository:
        return self._rule_versions

    @property
    def citations(self) -> MemoryCitationRepository:
        return self._citations

    @property
    def index(self) -> MemoryClauseIndex:
        return self._index

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
        level: AttributeLevel = AttributeLevel.REGISTRATION,
        effective_from: date = TEST_EFFECTIVE_FROM,
        effective_to: date | None = None,
        summary: str = "",
        specification: Mapping[str, object] | None = None,
        obligation_template: Mapping[str, object] | None = None,
        recurrence: Mapping[str, object] | None = None,
        published_at: datetime | None = None,
    ) -> tuple[RuleId, RuleVersionId]:
        """A rule with one version, for tests and demos (the seed command writes real ones).
        The version's content defaults to empty mappings: nothing here is a regulatory fact."""
        rule_id = RuleId(uuid4())
        with self._lock:
            self._tables.rules[rule_key] = _Rule(rule_id.value, rule_key, regulator, title, level)
        version_id = self.add_version(
            rule_key,
            title=title,
            status=status,
            effective_from=effective_from,
            effective_to=effective_to,
            summary=summary,
            specification=specification,
            obligation_template=obligation_template,
            recurrence=recurrence,
            published_at=published_at,
        )
        return rule_id, version_id

    def add_version(
        self,
        rule_key: str,
        *,
        title: str = "",
        status: RuleVersionStatus = RuleVersionStatus.DRAFT,
        effective_from: date = TEST_EFFECTIVE_FROM,
        effective_to: date | None = None,
        summary: str = "",
        specification: Mapping[str, object] | None = None,
        obligation_template: Mapping[str, object] | None = None,
        recurrence: Mapping[str, object] | None = None,
        published_at: datetime | None = None,
    ) -> RuleVersionId:
        """The next version of a rule ``add_rule`` created."""
        version_id = RuleVersionId.new()
        with self._lock:
            rule = self._tables.rules[rule_key]
            number = 1 + max(
                (v.version for v in self._tables.versions.values() if v.rule_id == rule.rule_id),
                default=0,
            )
            self._tables.versions[version_id] = _Version(
                rule_id=rule.rule_id,
                rule_key=rule_key,
                version=number,
                status=status,
                title=title,
                summary=summary,
                specification=dict(specification or {}),
                obligation_template=dict(obligation_template or {}),
                recurrence=None if recurrence is None else dict(recurrence),
                effective_from=effective_from,
                effective_to=effective_to,
                published_at=published_at,
            )
        return version_id

    def add_citation(
        self,
        rule_version_id: RuleVersionId,
        clause_id: ClauseId,
        quote: str,
        *,
        verified: bool = True,
        match_score: float | None = 1.0,
    ) -> UUID:
        """A citation of a stored clause, verified unless the test says otherwise."""
        citation_id = uuid4()
        with self._lock:
            self._tables.citations[citation_id] = _Citation(
                rule_version_id=rule_version_id,
                clause_id=clause_id,
                quote=quote,
                verified=verified,
                match_score=match_score,
                verified_at=utc_now() if verified else None,
            )
        return citation_id

    def add_entity(
        self, entity_type: EntityType, name: str, aliases: Sequence[str] = ()
    ) -> CanonicalEntityId:
        """A canonical entity with aliases, as an analyst's review would leave it."""
        entity_id = CanonicalEntityId.new()
        with self._lock:
            self._tables.entities[entity_id] = _Entity(entity_type, name, list(aliases))
        return entity_id

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
