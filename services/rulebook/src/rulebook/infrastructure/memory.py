"""In-memory unit of work: the store for tests, demos and a rulebook without a database.

Changes made inside a unit of work become visible to others only when the block exits cleanly,
as with the Postgres store. Units of work run one at a time (a lock held for the whole block),
so two overlapping requests cannot both start from the same tables and lose a write. The
uniqueness rules are the database's: first write wins, a repeat is a no-op. Events go to an
outbox list that is part of the tables, so they are kept or dropped with the unit of work, and
a status change must follow the kernel's transitions, as the Postgres trigger requires.
Audit entries wait in the unit's ``MemoryAuditSink`` and join the store's log only when the
unit exits cleanly (``audit_entries()`` reads it), as rows of ``audit.event`` commit with it.
"""

import copy
import math
import re
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from uuid import UUID, uuid4

from domain_kernel.audit import AuditEntry
from domain_kernel.errors import InvariantViolationError
from domain_kernel.events import utc_now
from domain_kernel.ids import (
    CanonicalEntityId,
    ClauseId,
    DocumentId,
    RuleId,
    RuleVersionId,
    UserId,
)
from domain_kernel.knowledge import EntityRef, EntityType, RelationKind, RuleRelation
from domain_kernel.ontology import AttributeLevel
from domain_kernel.predicates import specification_to_mapping
from domain_kernel.status import RULE_VERSION_TRANSITIONS, RuleVersionStatus
from domain_kernel.vectors import ClauseFilter, Vector
from py_common.audit import MemoryAuditSink
from rulebook.domain.changes import (
    CHANGE_ACTIONS,
    ChangeEntry,
    ChangeQuery,
    RuleChangeKind,
    deadline_change_id,
    newest_first,
)
from rulebook.domain.documents import StoredClause, StoredDocument
from rulebook.domain.errors import (
    ReviewTaskClosedError,
    ReviewTaskNotFoundError,
    RuleCandidateNotFoundError,
    RuleKeyTakenError,
    UnknownRuleVersionError,
)
from rulebook.domain.events import RulebookEvent
from rulebook.domain.graph import (
    ClauseDetail,
    EntityRecord,
    MentionedClause,
    MentionSpan,
    RelationQuery,
    RelationRecord,
)
from rulebook.domain.intake import (
    CandidateSummary,
    RuleCandidate,
    RuleCandidateStatus,
    version_closed,
)
from rulebook.domain.publication import (
    REPLACING,
    DecisionAction,
    PendingReplacement,
    RuleVersionDecision,
)
from rulebook.domain.relations import CandidateStatus, RelationCandidate
from rulebook.domain.repository import KnowledgeUnitOfWork
from rulebook.domain.review import (
    EntityReviewItem,
    MentionGroup,
    ReviewQueueStats,
    ReviewStatus,
)
from rulebook.domain.review_tasks import (
    CandidateCounts,
    QueuedTask,
    ReviewTask,
    ReviewTaskStats,
    TaskQuery,
    queue_position,
    task_stats,
)
from rulebook.domain.rule_versions import (
    IN_FORCE_STATUSES,
    CitationRecord,
    RuleHead,
    RuleVersionRecord,
    VersionPage,
    ended_since,
    in_force,
    out_of_force,
)
from rulebook.domain.runs import ExtractionRun, RuleSummary
from rulebook.domain.search import CitedClause, ClauseEmbedding
from rulebook.domain.seed import (
    SEED_CONTENT_KEYS,
    SeedCalendar,
    SeedOutcome,
    SeedRule,
    SeedStatus,
    reviewed_content,
    seed_content,
)

EXAMPLES_PER_GROUP = 5
FROZEN_STATUSES = frozenset(
    {RuleVersionStatus.PUBLISHED, RuleVersionStatus.SUPERSEDED, RuleVersionStatus.WITHDRAWN}
)
"""Statuses whose content the rule_version guard freezes."""
TASK_VERSION_KEY = "fk_review_task_rule_version_id_candidate_id_rule_version"
"""Migration 0011's key from a candidate task's version and candidate to the version."""
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
    high_impact: bool = False
    submitted_at: datetime | None = None
    candidate_id: UUID | None = None


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
    queued_at: dict[UUID, datetime] = field(default_factory=dict)
    candidates: dict[UUID, RelationCandidate] = field(default_factory=dict)
    relations: dict[UUID, tuple[RuleRelation, UUID | None]] = field(default_factory=dict)
    rules: dict[str, _Rule] = field(default_factory=dict)
    versions: dict[RuleVersionId, _Version] = field(default_factory=dict)
    citations: dict[UUID, _Citation] = field(default_factory=dict)
    embeddings: dict[tuple[ClauseId, str], Vector] = field(default_factory=dict)
    runs: dict[UUID, ExtractionRun] = field(default_factory=dict)
    decisions: list[RuleVersionDecision] = field(default_factory=list)
    outbox: list[RulebookEvent] = field(default_factory=list)
    review_tasks: dict[UUID, ReviewTask] = field(default_factory=dict)
    rule_candidates: dict[UUID, RuleCandidate] = field(default_factory=dict)

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
            found.append(
                MentionedClause(
                    ClauseDetail(clause, document),
                    ordered,
                    _out_of_force(self._tables, clause_id, as_of),
                )
            )
        return sorted(found, key=_newest_first)[:limit]


class MemoryReviewRepository:
    def __init__(self, tables: _Tables, clock: Callable[[], datetime] = utc_now) -> None:
        self._tables = tables
        self._clock = clock

    def enqueue(self, item: EntityReviewItem) -> bool:
        if item.review_id in self._tables.reviews:
            return False
        self._tables.reviews[item.review_id] = item
        self._tables.queued_at[item.review_id] = self._clock()
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

    def queue_stats(self) -> ReviewQueueStats:
        by_type: dict[EntityType, int] = {}
        queued: list[datetime] = []
        for item in self._tables.reviews.values():
            if item.status is not ReviewStatus.OPEN:
                continue
            by_type[item.entity_type] = by_type.get(item.entity_type, 0) + 1
            if item.review_id in self._tables.queued_at:
                queued.append(self._tables.queued_at[item.review_id])
        return ReviewQueueStats(by_type, min(queued, default=None))


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

    def remove_approved(self, rule_version_id: RuleVersionId) -> tuple[UUID, ...]:
        removed = [
            (relation_id, candidate_id)
            for relation_id, (relation, candidate_id) in self._tables.relations.items()
            if relation.from_rule_version_id == rule_version_id and candidate_id is not None
        ]
        for relation_id, _ in removed:
            del self._tables.relations[relation_id]
        return tuple(sorted((candidate_id for _, candidate_id in removed if candidate_id), key=str))

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
        """Each rule with the title of its latest version, a closed draft skipped, as the
        Postgres store reads it; a rule with no other version is left out."""
        found: list[RuleSummary] = []
        for rule in sorted(self._tables.rules.values(), key=lambda r: r.rule_key):
            latest = _latest_open(self._tables, rule)
            if latest is not None:
                found.append(
                    RuleSummary(rule.rule_key, rule.rule_id, rule.regulator, latest[1].title)
                )
        return tuple(found)

    def rule_id(self, rule_key: str) -> UUID | None:
        rule = self._tables.rules.get(rule_key)
        return None if rule is None else rule.rule_id

    def version_status(self, rule_version_id: RuleVersionId) -> RuleVersionStatus | None:
        version = self._tables.versions.get(rule_version_id)
        return None if version is None else version.status


class MemoryRuleVersionRepository:
    def __init__(self, tables: _Tables) -> None:
        self._tables = tables

    def in_force(self, as_of: date, page: VersionPage) -> Sequence[RuleVersionRecord]:
        return self._page(lambda record: in_force(record, as_of), page)

    def ended(self, since: date, page: VersionPage) -> Sequence[RuleVersionRecord]:
        return self._page(lambda record: ended_since(record, since), page)

    def _page(
        self, listed: Callable[[RuleVersionRecord], bool], page: VersionPage
    ) -> list[RuleVersionRecord]:
        found = [
            record
            for record in (
                _version_record(self._tables, v_id, v) for v_id, v in self._tables.versions.items()
            )
            if listed(record) and page.admits(record)
        ]
        return sorted(found, key=lambda record: (record.rule_key, record.version))[: page.limit]

    def get(self, rule_version_id: RuleVersionId) -> RuleVersionRecord | None:
        version = self._tables.versions.get(rule_version_id)
        return None if version is None else _version_record(self._tables, rule_version_id, version)

    def lock(self, rule_version_id: RuleVersionId) -> RuleVersionRecord | None:
        """Units of work already run one at a time here."""
        return self.get(rule_version_id)

    def lock_many(
        self, rule_version_ids: Sequence[RuleVersionId]
    ) -> Mapping[RuleVersionId, RuleVersionRecord]:
        found = (self.get(version_id) for version_id in sorted(set(rule_version_ids), key=str))
        return {record.rule_version_id: record for record in found if record is not None}

    def of_rule(self, rule_id: RuleId) -> Sequence[RuleVersionRecord]:
        found = [
            _version_record(self._tables, version_id, version)
            for version_id, version in self._tables.versions.items()
            if version.rule_id == rule_id.value
        ]
        return sorted(found, key=lambda record: record.version)

    def save_lifecycle(self, record: RuleVersionRecord) -> None:
        version = self._tables.versions.get(record.rule_version_id)
        if version is None:
            raise UnknownRuleVersionError(str(record.rule_version_id))
        if record.status is not version.status:
            RULE_VERSION_TRANSITIONS.assert_transition(version.status, record.status)
        version.status = record.status
        version.seed_status = record.seed_status
        version.effective_to = record.effective_to
        version.published_at = record.published_at
        version.submitted_at = record.submitted_at
        version.high_impact = record.high_impact

    def save_draft(self, record: RuleVersionRecord) -> None:
        version = self._tables.versions.get(record.rule_version_id)
        if version is None:
            raise UnknownRuleVersionError(str(record.rule_version_id))
        if version.status in FROZEN_STATUSES:
            raise InvariantViolationError(
                f"rule version {record.rule_version_id}: the content of a published version is "
                "frozen"
            )
        version.title = record.title
        version.summary = record.summary
        version.specification = dict(record.specification)
        version.obligation_template = dict(record.obligation_template)
        version.recurrence = None if record.recurrence is None else dict(record.recurrence)
        version.effective_from = record.effective_from
        version.effective_to = record.effective_to
        version.todo = tuple(record.todo)

    def record_decision(self, decision: RuleVersionDecision) -> None:
        self._tables.decisions.append(decision)

    def decisions(self, rule_version_id: RuleVersionId) -> tuple[RuleVersionDecision, ...]:
        found = [d for d in self._tables.decisions if d.rule_version_id == rule_version_id]
        return tuple(sorted(found, key=lambda decision: decision.decided_at))

    def approvers(self, rule_version_id: RuleVersionId, since: datetime) -> frozenset[UserId]:
        return frozenset(
            decision.actor_id
            for decision in self._tables.decisions
            if decision.rule_version_id == rule_version_id
            and decision.action is DecisionAction.APPROVED
            and decision.actor_id is not None
            and decision.decided_at >= since
        )

    def replaced_by_others(
        self, rule_version_ids: Sequence[RuleVersionId], excluding: RuleVersionId
    ) -> frozenset[RuleVersionId]:
        wanted = set(rule_version_ids)
        found: set[RuleVersionId] = set()
        for relation, _ in self._tables.relations.values():
            target = relation.target
            source = self._tables.versions.get(relation.from_rule_version_id)
            if (
                relation.relation in REPLACING
                and isinstance(target, RuleVersionId)
                and target in wanted
                and relation.from_rule_version_id != excluding
                and source is not None
                and source.status in IN_FORCE_STATUSES
            ):
                found.add(target)
        return frozenset(found)

    def pending_replacements(self, today: date) -> Sequence[PendingReplacement]:
        pending: list[PendingReplacement] = []
        for relation, _ in self._tables.relations.values():
            target_id = relation.target
            if relation.relation not in REPLACING or not isinstance(target_id, RuleVersionId):
                continue
            replacing = self._tables.versions.get(relation.from_rule_version_id)
            target = self._tables.versions.get(target_id)
            if (
                replacing is not None
                and target is not None
                and replacing.status in IN_FORCE_STATUSES
                and replacing.effective_from <= today
                and target.status is RuleVersionStatus.PUBLISHED
            ):
                pending.append(
                    PendingReplacement(
                        relation=relation.relation,
                        target_id=target_id,
                        target_rule_id=RuleId(target.rule_id),
                        replacing_id=relation.from_rule_version_id,
                        replacing_from=replacing.effective_from,
                    )
                )
        return sorted(
            pending,
            key=lambda p: (p.replacing_from, str(p.target_id), str(p.replacing_id)),
        )

    def lock_publication(self) -> None:
        """Units of work already run one at a time here."""

    def changes(self, query: ChangeQuery) -> Sequence[ChangeEntry]:
        entries: list[ChangeEntry] = []
        for decision in self._tables.decisions:
            kind = CHANGE_ACTIONS.get(decision.action)
            if kind is None:
                continue
            entries.append(
                ChangeEntry(
                    change_id=decision.decision_id,
                    kind=kind,
                    changed_at=decision.decided_at,
                    rule_version_id=decision.rule_version_id,
                    caused_by=decision.caused_by,
                )
            )
            if kind is RuleChangeKind.PUBLISHED:
                entries.extend(self._deadline_changes(decision))
        found = [
            entry
            for entry in entries
            if (query.since is None or entry.changed_at >= query.since)
            and (query.regulator is None or self._regulator(entry) == query.regulator)
            and (
                query.after is None
                or (entry.changed_at, entry.change_id)
                < (query.after.changed_at, query.after.change_id)
            )
        ]
        return newest_first(found)[: query.limit]

    def _deadline_changes(self, decision: RuleVersionDecision) -> list[ChangeEntry]:
        """The deadline changes the publication ``decision`` made: one per extends_deadline
        relation from its version to another."""
        found: list[ChangeEntry] = []
        for relation_id, (relation, candidate_id) in self._tables.relations.items():
            target = relation.target
            if (
                relation.from_rule_version_id != decision.rule_version_id
                or relation.relation is not RelationKind.EXTENDS_DEADLINE
                or not isinstance(target, RuleVersionId)
            ):
                continue
            candidate = None if candidate_id is None else self._tables.candidates.get(candidate_id)
            found.append(
                ChangeEntry(
                    change_id=deadline_change_id(decision.decision_id, relation_id),
                    kind=RuleChangeKind.DEADLINE_CHANGED,
                    changed_at=decision.decided_at,
                    rule_version_id=target,
                    caused_by=decision.rule_version_id,
                    period_label=None if candidate is None else candidate.period_label,
                    new_due_on=None if candidate is None else candidate.new_due_on,
                    evidence_clause_id=relation.evidence_clause_id,
                )
            )
        return found

    def _regulator(self, entry: ChangeEntry) -> str | None:
        version = self._tables.versions.get(entry.rule_version_id)
        return None if version is None else self._tables.rules[version.rule_key].regulator

    def lock_rule(self, rule_key: str) -> RuleHead | None:
        """Units of work already run one at a time here, so nothing is locked."""
        rule = self._tables.rules.get(rule_key)
        if rule is None:
            return None
        return RuleHead(
            rule_id=RuleId(rule.rule_id),
            rule_key=rule.rule_key,
            regulator=rule.regulator,
            level=rule.level,
            last_version=max(
                (v.version for v in self._tables.versions.values() if v.rule_id == rule.rule_id),
                default=0,
            ),
        )

    def add_rule_and_version(self, record: RuleVersionRecord, *, new_rule: bool) -> None:
        if new_rule:
            if record.rule_key in self._tables.rules:
                raise RuleKeyTakenError(record.rule_key)
            self._tables.rules[record.rule_key] = _Rule(
                record.rule_id.value, record.rule_key, record.regulator, record.level
            )
        rule = self._tables.rules[record.rule_key]
        if rule.rule_id != record.rule_id.value:
            raise InvariantViolationError(f"rule {record.rule_key} has another id")
        taken = {v.version for v in self._tables.versions.values() if v.rule_id == rule.rule_id}
        if record.version in taken or record.version != max(taken, default=0) + 1:
            raise InvariantViolationError(
                f"version {record.version} of {record.rule_key} does not follow the latest"
            )
        if record.status is not RuleVersionStatus.DRAFT or record.published_at is not None:
            raise InvariantViolationError("a version is inserted as an unpublished draft")
        if record.candidate_id is not None and any(
            version.candidate_id == record.candidate_id
            for version in self._tables.versions.values()
        ):
            raise InvariantViolationError(f"candidate {record.candidate_id} has a version already")
        self._tables.versions[record.rule_version_id] = _Version(
            rule_id=rule.rule_id,
            rule_key=record.rule_key,
            version=record.version,
            status=record.status,
            title=record.title,
            summary=record.summary,
            specification=dict(record.specification),
            obligation_template=dict(record.obligation_template),
            recurrence=None if record.recurrence is None else dict(record.recurrence),
            effective_from=record.effective_from,
            effective_to=record.effective_to,
            source=dict(record.source),
            seed_status=record.seed_status,
            todo=tuple(record.todo),
            high_impact=record.high_impact,
            candidate_id=record.candidate_id,
        )


class MemoryRuleCandidateRepository:
    """The rule candidates under the table's rules: one row per candidate id, first write
    wins, and the version a candidate names was drafted from it (the composite key)."""

    def __init__(self, tables: _Tables) -> None:
        self._tables = tables

    def add(self, candidate: RuleCandidate) -> bool:
        if candidate.candidate_id in self._tables.rule_candidates:
            return False
        if candidate.document_id not in self._tables.documents:
            raise InvariantViolationError(f"document {candidate.document_id} is not stored")
        _require_drafted_from(
            self._tables,
            candidate.rule_version_id,
            candidate.candidate_id,
            "fk_rule_candidate_rule_version_id_id_rule_version",
        )
        self._tables.rule_candidates[candidate.candidate_id] = candidate
        return True

    def get(self, candidate_id: UUID) -> RuleCandidate | None:
        return self._tables.rule_candidates.get(candidate_id)

    def lock(self, candidate_id: UUID) -> RuleCandidate | None:
        """Units of work already run one at a time here."""
        return self.get(candidate_id)

    def save(self, candidate: RuleCandidate) -> None:
        if candidate.candidate_id not in self._tables.rule_candidates:
            raise RuleCandidateNotFoundError(
                f"rule candidate {candidate.candidate_id} is not stored"
            )
        _require_drafted_from(
            self._tables,
            candidate.rule_version_id,
            candidate.candidate_id,
            "fk_rule_candidate_rule_version_id_id_rule_version",
        )
        self._tables.rule_candidates[candidate.candidate_id] = candidate

    def decided_since(self, since: datetime) -> Sequence[RuleCandidate]:
        found = [
            candidate
            for candidate in self._tables.rule_candidates.values()
            if candidate.decided_at is not None and candidate.decided_at >= since
        ]
        return sorted(found, key=lambda candidate: (candidate.decided_at, candidate.candidate_id))


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
                _out_of_force(self._tables, clause_id, as_of),
            )
        return found


def _cited_in_force(tables: _Tables, rule_version_id: RuleVersionId, as_of: date | None) -> bool:
    version = tables.versions.get(rule_version_id)
    if version is None or version.status not in IN_FORCE_STATUSES:
        return False
    return as_of is None or in_force(_version_record(tables, rule_version_id, version), as_of)


def _out_of_force(tables: _Tables, clause_id: ClauseId, as_of: date | None) -> bool:
    citing = {
        citation.rule_version_id
        for citation in tables.citations.values()
        if citation.clause_id == clause_id and citation.verified
    }
    return out_of_force(
        (
            _version_record(tables, version_id, tables.versions[version_id])
            for version_id in citing
            if version_id in tables.versions
        ),
        as_of,
    )


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
        high_impact=version.high_impact,
        submitted_at=version.submitted_at,
        candidate_id=version.candidate_id,
    )


def _require_drafted_from(
    tables: _Tables, rule_version_id: RuleVersionId | None, candidate_id: UUID, key: str
) -> None:
    """A candidate, or its task, names only the version drafted from that candidate: what
    migration 0011's composite keys (``key``) refuse in Postgres is refused here."""
    if rule_version_id is None:
        return
    version = tables.versions.get(rule_version_id)
    if version is None:
        raise UnknownRuleVersionError(str(rule_version_id))
    if version.candidate_id != candidate_id:
        drafted_from = "no candidate" if version.candidate_id is None else version.candidate_id
        raise InvariantViolationError(
            f"rule version {rule_version_id} was drafted from {drafted_from}, not rule candidate "
            f"{candidate_id} ({key})"
        )


def _closed(tables: _Tables, rule_version_id: RuleVersionId, version: _Version) -> bool:
    """``intake.version_closed``: drafted from a rule candidate that was rejected, never
    published."""
    if version.candidate_id is None:
        return False
    candidate = tables.rule_candidates.get(version.candidate_id)
    return version_closed(_version_record(tables, rule_version_id, version), candidate)


def _versions_of(tables: _Tables, rule: _Rule) -> list[tuple[RuleVersionId, _Version]]:
    """Every version of the rule, by number."""
    found = [(v_id, v) for v_id, v in tables.versions.items() if v.rule_id == rule.rule_id]
    return sorted(found, key=lambda item: item[1].version)


def _latest_open(tables: _Tables, rule: _Rule) -> tuple[RuleVersionId, _Version] | None:
    """The rule's latest version, a closed draft skipped; None when it has no other."""
    open_versions = [item for item in _versions_of(tables, rule) if not _closed(tables, *item)]
    return open_versions[-1] if open_versions else None


def _seed_version(rule: _Rule, seeded: SeedRule, number: int) -> _Version:
    """A draft version holding what the seed calendar says about a rule."""
    source: dict[str, object] = dict(seeded.source.to_mapping())
    return _Version(
        rule_id=rule.rule_id,
        rule_key=rule.rule_key,
        version=number,
        status=RuleVersionStatus.DRAFT,
        title=seeded.title,
        summary=seeded.summary,
        specification=specification_to_mapping(seeded.specification),
        obligation_template=seeded.obligation_template.to_mapping(),
        recurrence=None if seeded.recurrence is None else seeded.recurrence.to_mapping(),
        effective_from=seeded.effective_from,
        effective_to=None,
        source=source,
        seed_status=seeded.seed_status,
        todo=seeded.todo,
    )


def _seed_content_of(version: _Version) -> dict[str, object]:
    """A stored version in the form ``seed_content`` gives a seed rule, to compare the two."""
    return {
        "title": version.title,
        "summary": version.summary,
        "specification": version.specification,
        "obligation_template": version.obligation_template,
        "recurrence": version.recurrence,
        "effective_from": version.effective_from,
        "source": version.source,
        "seed_status": version.seed_status.value,
        "todo": list(version.todo),
    }


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

    def add(self, citation: CitationRecord) -> bool:
        if citation.citation_id in self._tables.citations:
            return False
        self._tables.citations[citation.citation_id] = _Citation(
            rule_version_id=citation.rule_version_id,
            clause_id=citation.clause_id,
            quote=citation.quote,
            verified=citation.verified,
            match_score=citation.match_score,
            verified_at=citation.verified_at,
        )
        return True


class MemoryReviewTaskRepository:
    """The review tasks under the table's rules: at most one task per version that is not
    decided, and one per candidate (the partial unique indexes), a decided task never changes
    and a task takes its version once (the trigger), and a candidate task's version was drafted
    from its candidate (the composite key)."""

    def __init__(self, tables: _Tables) -> None:
        self._tables = tables

    def add(self, task: ReviewTask) -> bool:
        if task.rule_version_id is not None and task.rule_version_id not in self._tables.versions:
            raise UnknownRuleVersionError(str(task.rule_version_id))
        if task.candidate_id is not None and task.candidate_id not in self._tables.rule_candidates:
            raise RuleCandidateNotFoundError(f"rule candidate {task.candidate_id} is not stored")
        if task.candidate_id is not None:
            _require_drafted_from(
                self._tables, task.rule_version_id, task.candidate_id, TASK_VERSION_KEY
            )
        if task.task_id in self._tables.review_tasks:
            return False
        if task.undecided and any(
            stored.undecided
            and (
                (
                    task.rule_version_id is not None
                    and stored.rule_version_id == task.rule_version_id
                )
                or (task.candidate_id is not None and stored.candidate_id == task.candidate_id)
            )
            for stored in self._tables.review_tasks.values()
        ):
            return False
        self._tables.review_tasks[task.task_id] = task
        return True

    def get(self, task_id: UUID) -> ReviewTask | None:
        return self._tables.review_tasks.get(task_id)

    def lock(self, task_id: UUID) -> ReviewTask | None:
        """Units of work already run one at a time here."""
        return self.get(task_id)

    def save(self, task: ReviewTask) -> None:
        stored = self._tables.review_tasks.get(task.task_id)
        if stored is None:
            raise ReviewTaskNotFoundError(f"review task {task.task_id} is not stored")
        if not stored.undecided:
            raise ReviewTaskClosedError(f"review task {task.task_id}: a decided task never changes")
        identity = ("kind", "candidate_id", "regulator", "opened_at")
        if any(getattr(stored, name) != getattr(task, name) for name in identity):
            raise InvariantViolationError(
                f"review task {task.task_id} keeps its kind, candidate, regulator and opening time"
            )
        if stored.rule_version_id is not None and stored.rule_version_id != task.rule_version_id:
            raise InvariantViolationError(
                f"review task {task.task_id} keeps its version once it has one"
            )
        if task.rule_version_id is not None and task.rule_version_id not in self._tables.versions:
            raise UnknownRuleVersionError(str(task.rule_version_id))
        if task.candidate_id is not None:
            _require_drafted_from(
                self._tables, task.rule_version_id, task.candidate_id, TASK_VERSION_KEY
            )
        self._tables.review_tasks[task.task_id] = task

    def page(self, query: TaskQuery) -> Sequence[QueuedTask]:
        found = sorted(
            (task for task in self._tables.review_tasks.values() if query.admits(task)),
            key=queue_position,
        )
        return [self._queued(task) for task in found[: query.limit]]

    def _queued(self, task: ReviewTask) -> QueuedTask:
        candidate = (
            None if task.candidate_id is None else self._tables.rule_candidates[task.candidate_id]
        )
        summary = None if candidate is None else CandidateSummary.of(candidate)
        if task.rule_version_id is None:
            assert candidate is not None, "a task without a version names its candidate"
            return QueuedTask(
                task=task,
                rule_key=candidate.suggested_rule_key,
                version=None,
                title=candidate.title,
                version_status=None,
                high_impact=candidate.high_impact_suggested,
                approvals=0,
                candidate=summary,
            )
        version = self._tables.versions[task.rule_version_id]
        submitted = version.submitted_at
        approvals = (
            0
            if submitted is None
            else len(
                {
                    decision.actor_id
                    for decision in self._tables.decisions
                    if decision.rule_version_id == task.rule_version_id
                    and decision.action is DecisionAction.APPROVED
                    and decision.actor_id is not None
                    and decision.decided_at >= submitted
                }
            )
        )
        return QueuedTask(
            task=task,
            rule_key=version.rule_key,
            version=version.version,
            title=version.title,
            version_status=version.status,
            high_impact=version.high_impact,
            approvals=approvals,
            candidate=summary,
        )

    def of_version(self, rule_version_id: RuleVersionId) -> tuple[ReviewTask, ...]:
        found = [
            task
            for task in self._tables.review_tasks.values()
            if task.rule_version_id == rule_version_id
        ]
        return tuple(sorted(found, key=lambda task: (task.opened_at, task.task_id)))

    def of_candidate(self, candidate_id: UUID) -> tuple[ReviewTask, ...]:
        found = [
            task for task in self._tables.review_tasks.values() if task.candidate_id == candidate_id
        ]
        return tuple(sorted(found, key=lambda task: (task.opened_at, task.task_id)))

    def drafts_without_task(self) -> Sequence[RuleVersionRecord]:
        tasked = {
            task.rule_version_id for task in self._tables.review_tasks.values() if task.undecided
        }
        found = [
            _version_record(self._tables, version_id, version)
            for version_id, version in self._tables.versions.items()
            if version.status is RuleVersionStatus.DRAFT
            and version.seed_status is SeedStatus.NEEDS_REVIEW
            and version.candidate_id is None
            and version_id not in tasked
        ]
        return sorted(found, key=lambda record: (record.rule_key, record.version))

    def stats(self) -> ReviewTaskStats:
        return task_stats(list(self._tables.review_tasks.values()), self._candidate_counts())

    def _candidate_counts(self) -> CandidateCounts:
        edited = {
            decision.rule_version_id
            for decision in self._tables.decisions
            if decision.action is DecisionAction.EDITED
        }
        approved = [
            candidate
            for candidate in self._tables.rule_candidates.values()
            if candidate.status is RuleCandidateStatus.APPROVED
        ]
        return CandidateCounts(
            approved=len(approved),
            approved_without_edits=sum(
                candidate.rule_version_id not in edited for candidate in approved
            ),
            rejected=sum(
                candidate.status is RuleCandidateStatus.REJECTED
                for candidate in self._tables.rule_candidates.values()
            ),
        )


class MemoryEventSink:
    def __init__(self, tables: _Tables) -> None:
        self._tables = tables

    def publish(self, event: RulebookEvent) -> None:
        self._tables.outbox.append(event)


class MemoryRunRepository:
    def __init__(self, tables: _Tables) -> None:
        self._tables = tables

    def record(self, run: ExtractionRun) -> bool:
        if run.run_id in self._tables.runs:
            return False
        self._tables.runs[run.run_id] = run
        return True


class MemoryUnitOfWork:
    def __init__(
        self,
        tables: _Tables,
        clock: Callable[[], datetime] = utc_now,
        audit: list[AuditEntry] | None = None,
    ) -> None:
        self._documents = MemoryDocumentRepository(tables)
        self._entities = MemoryEntityRepository(tables)
        self._mentions = MemoryMentionRepository(tables)
        self._reviews = MemoryReviewRepository(tables, clock)
        self._candidates = MemoryCandidateRepository(tables)
        self._relations = MemoryRelationRepository(tables)
        self._rules = MemoryRuleCatalog(tables)
        self._rule_versions = MemoryRuleVersionRepository(tables)
        self._citations = MemoryCitationRepository(tables)
        self._review_tasks = MemoryReviewTaskRepository(tables)
        self._rule_candidates = MemoryRuleCandidateRepository(tables)
        self._index = MemoryClauseIndex(tables)
        self._runs = MemoryRunRepository(tables)
        self._events = MemoryEventSink(tables)
        self._audit = MemoryAuditSink([] if audit is None else audit)

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
    def review_tasks(self) -> MemoryReviewTaskRepository:
        return self._review_tasks

    @property
    def rule_candidates(self) -> MemoryRuleCandidateRepository:
        return self._rule_candidates

    @property
    def index(self) -> MemoryClauseIndex:
        return self._index

    @property
    def runs(self) -> MemoryRunRepository:
        return self._runs

    @property
    def events(self) -> MemoryEventSink:
        return self._events

    @property
    def audit(self) -> MemoryAuditSink:
        return self._audit


class MemoryKnowledgeStore:
    """``store()`` opens a unit of work on a copy of the tables; a clean exit publishes it.
    ``clock`` stamps review items when they are queued, as ``created_at`` does in Postgres.
    ``audit`` is the log committed audit entries go to: a list of the store's own unless another
    one is shared, as every service shares ``audit.event`` (an in-process journey's)."""

    def __init__(
        self, clock: Callable[[], datetime] = utc_now, *, audit: list[AuditEntry] | None = None
    ) -> None:
        self._tables = _Tables()
        self._audit: list[AuditEntry] = [] if audit is None else audit
        self._lock = threading.Lock()
        self._clock = clock

    def __call__(self) -> AbstractContextManager[KnowledgeUnitOfWork]:
        return self._open()

    @contextmanager
    def _open(self) -> Iterator[KnowledgeUnitOfWork]:
        with self._lock:
            working = self._tables.copy()
            unit = MemoryUnitOfWork(working, self._clock, self._audit)
            yield unit
            unit.audit.commit()
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
        high_impact: bool = False,
    ) -> tuple[RuleId, RuleVersionId]:
        """A rule with one version, for tests and demos (the seed command writes real ones).
        The version's content defaults to empty mappings: nothing here is a regulatory fact."""
        rule_id = RuleId(uuid4())
        with self._lock:
            self._tables.rules[rule_key] = _Rule(rule_id.value, rule_key, regulator, level)
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
            high_impact=high_impact,
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
        high_impact: bool = False,
    ) -> RuleVersionId:
        """The next version of a rule ``add_rule`` created. A status past draft is set as is,
        without the review flow; tests that exercise the flow start from a draft."""
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
                high_impact=high_impact,
            )
        return version_id

    def apply_seed(self, calendar: SeedCalendar) -> SeedOutcome:
        """The seed calendar's rules as draft versions, the way ``rulebook-seed`` writes them
        into Postgres (``SqlAlchemySeedRepository``), rule by rule:

        - a rule with no version, or only closed drafts (``intake.version_closed``), gets the
          next number;
        - the seed's own draft (its latest version not drafted from a candidate, while it is a
          draft) is updated in place, even beside a candidate's draft, unless an analyst edited
          it through its review task (``kept_edited``);
        - otherwise the rule's latest version, a closed draft skipped, decides: one drafted from
          a candidate or edited by an analyst is left alone (``kept_edited``), and one past
          draft gets a new draft version after it when its content differs (``seed_status`` is
          left out of that comparison).

        Everything written is a draft that needs review; this is what
        ``CW_RULEBOOK_SEED_ON_START`` loads in local and test."""
        created_rules: list[str] = []
        created_versions: list[str] = []
        updated: list[str] = []
        unchanged: list[str] = []
        kept: list[str] = []
        with self._lock:
            for rule in calendar.rules:
                stored = self._tables.rules.get(rule.rule_key)
                if stored is None:
                    stored = _Rule(uuid4(), rule.rule_key, rule.regulator, rule.level)
                    self._tables.rules[rule.rule_key] = stored
                    created_rules.append(rule.rule_key)
                content = seed_content(rule)
                versions = _versions_of(self._tables, stored)
                number = 1 + (versions[-1][1].version if versions else 0)
                current = [item for item in versions if not _closed(self._tables, *item)]
                own = next(
                    (item for item in reversed(current) if item[1].candidate_id is None), None
                )
                if not current:
                    self._tables.versions[RuleVersionId.new()] = _seed_version(stored, rule, number)
                    created_versions.append(f"{rule.rule_key}@{number}")
                elif own is not None and own[1].status is RuleVersionStatus.DRAFT:
                    own_id, draft = own
                    if self._edited(own_id):
                        kept.append(rule.rule_key)
                    elif _seed_content_of(draft) == content:
                        unchanged.append(rule.rule_key)
                    else:
                        seeded = _seed_version(stored, rule, draft.version)
                        self._tables.versions[own_id] = replace(
                            draft, **{key: getattr(seeded, key) for key in SEED_CONTENT_KEYS}
                        )
                        updated.append(f"{rule.rule_key}@{draft.version}")
                elif current[-1][1].candidate_id is not None or self._edited(current[-1][0]):
                    kept.append(rule.rule_key)
                elif reviewed_content(_seed_content_of(current[-1][1])) == reviewed_content(
                    content
                ):
                    unchanged.append(rule.rule_key)
                else:
                    self._tables.versions[RuleVersionId.new()] = _seed_version(stored, rule, number)
                    created_versions.append(f"{rule.rule_key}@{number}")
        return SeedOutcome(
            tuple(created_rules),
            tuple(created_versions),
            tuple(updated),
            tuple(unchanged),
            tuple(kept),
        )

    def _edited(self, rule_version_id: RuleVersionId) -> bool:
        """Whether an analyst edited the version through its review task."""
        return any(
            decision.rule_version_id == rule_version_id and decision.action is DecisionAction.EDITED
            for decision in self._tables.decisions
        )

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

    def events(self) -> list[RulebookEvent]:
        """The committed outbox, oldest first."""
        with self._lock:
            return list(self._tables.outbox)

    def audit_entries(self, action: str | None = None) -> list[AuditEntry]:
        """The committed audit log, oldest first; one action's when it is named."""
        with self._lock:
            return [entry for entry in self._audit if action in (None, entry.action)]

    def decisions(self, rule_version_id: RuleVersionId | None = None) -> list[RuleVersionDecision]:
        """The committed decision audit, oldest first; one version's when it is named."""
        with self._lock:
            return [
                decision
                for decision in self._tables.decisions
                if rule_version_id in (None, decision.rule_version_id)
            ]

    def review_tasks(self, rule_version_id: RuleVersionId | None = None) -> list[ReviewTask]:
        """The committed review tasks, oldest first; one version's when it is named."""
        with self._lock:
            found = [
                task
                for task in self._tables.review_tasks.values()
                if rule_version_id in (None, task.rule_version_id)
            ]
        return sorted(found, key=lambda task: (task.opened_at, task.task_id))

    def rule_candidates(self) -> list[RuleCandidate]:
        """The committed rule candidates, oldest first."""
        with self._lock:
            found = list(self._tables.rule_candidates.values())
        return sorted(found, key=lambda candidate: (candidate.created_at, candidate.candidate_id))
