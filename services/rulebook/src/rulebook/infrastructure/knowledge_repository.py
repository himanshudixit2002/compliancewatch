"""The Postgres unit of work for regulator documents and the knowledge tables.

Inserts use ``ON CONFLICT DO NOTHING``: documents, clauses, mentions, review items, candidates,
relations, runs and clause embeddings are keyed by ids every writer derives the same way, so a
repeated insert is a no-op rather than an error. Decisions lock the rows they change
(``SELECT ... FOR UPDATE``).

Clause search runs two queries. The lexical leg matches ``clause.search_vector`` against the
query's terms joined by OR and ranks with ``ts_rank_cd``. The vector leg orders by cosine
distance over the HNSW index with ``hnsw.ef_search`` raised and pgvector's iterative scan on,
so filters applied after the index scan still leave enough rows; iterative scan may return rows
slightly out of order, so the outer query sorts them again.

The review and publish flow locks the versions it changes, and publishing, withdrawing and the
transition sweep also hold an advisory lock for their transaction. Their events go to
``outbox_event`` through py-common's ``OutboxWriter`` on the same connection, so an event
commits or rolls back with the change it describes; the ``rule_version`` trigger checks the
same rules as the use cases. A review task's decision locks the task, then its version, and
commits with the version's transition; the ``review_task`` trigger keeps a decided task as it is.

``ConnectionKnowledgeUnitOfWorkFactory`` makes units of work inside a transaction someone else
owns, such as the inbox transaction of the worker's consumer of rule.candidate.created
(``py_common.outbox.sync``): the candidate, its review task and the ``processed_event`` row then
commit together, or none of them. A unit there neither commits nor rolls back.

A unit's audit entries (``audit``, ``py_common.audit.writer``) go to ``audit.event`` on the same
connection, as platform rows: regulatory data belongs to no tenant.
"""

from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Self
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    CompoundSelect,
    Connection,
    Date,
    Engine,
    Float,
    Select,
    String,
    Text,
    Uuid,
    and_,
    bindparam,
    cast,
    create_engine,
    delete,
    func,
    literal,
    literal_column,
    null,
    or_,
    select,
    text,
    tuple_,
    union_all,
    update,
)
from sqlalchemy.dialects.postgresql import TSQUERY, insert
from sqlalchemy.orm import Session, aliased
from sqlalchemy.pool import NullPool

from domain_kernel.documents import DocumentType
from domain_kernel.ids import (
    CanonicalEntityId,
    ClauseId,
    DocumentId,
    RuleId,
    RuleVersionId,
    SourceId,
    UserId,
)
from domain_kernel.knowledge import EntityRef, EntityType, RelationKind, RuleRelation
from domain_kernel.ontology import AttributeLevel
from domain_kernel.status import RuleVersionStatus
from domain_kernel.vectors import ClauseFilter, Vector
from py_common.audit.writer import PostgresAuditSink
from py_common.outbox import OutboxWriter
from rulebook.domain.alignment import ReviewReason
from rulebook.domain.changes import CHANGE_ACTIONS, ChangeEntry, ChangeQuery, RuleChangeKind
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
    CandidateOutcome,
    CandidateSummary,
    RuleCandidate,
    RuleCandidateStatus,
    RuleRejectReason,
)
from rulebook.domain.publication import (
    REPLACING,
    DecisionAction,
    PendingReplacement,
    RuleVersionDecision,
)
from rulebook.domain.relations import (
    CandidateIssue,
    CandidateRejectReason,
    CandidateStatus,
    RelationCandidate,
)
from rulebook.domain.repository import KnowledgeUnitOfWork
from rulebook.domain.review import (
    EntityRejectReason,
    EntityReviewItem,
    MentionGroup,
    Resolution,
    ReviewQueueStats,
    ReviewStatus,
)
from rulebook.domain.review_tasks import (
    UNDECIDED,
    CandidateCounts,
    QueuedTask,
    RegulatorCounts,
    ReviewDecision,
    ReviewTask,
    ReviewTaskKind,
    ReviewTaskStats,
    ReviewTaskStatus,
    TaskKey,
    TaskQuery,
)
from rulebook.domain.rule_versions import (
    CITING_STATUSES,
    IN_FORCE_STATUSES,
    CitationRecord,
    RuleHead,
    RuleVersionRecord,
    VersionPage,
)
from rulebook.domain.runs import ExtractionRun, RuleSummary
from rulebook.domain.search import CitedClause, ClauseEmbedding
from rulebook.domain.seed import SeedStatus
from rulebook.infrastructure.models import (
    CanonicalEntityRow,
    CitationRow,
    ClauseEmbeddingRow,
    ClauseEntityRow,
    ClauseRow,
    DocumentRow,
    EntityReviewRow,
    ExtractionRunRow,
    RelationCandidateRow,
    ReviewTaskRow,
    RuleCandidateRow,
    RuleRelationRow,
    RuleRow,
    RuleVersionDecisionRow,
    RuleVersionRow,
)

EXAMPLES_PER_GROUP = 5
SUPERSESSION_LOCK = 0x72756C6573757073
"""Advisory lock key held for the rest of a transaction that approves a supersession."""
PUBLICATION_LOCK = 0x72756C657075626C
"""Advisory lock key held for the rest of a transaction that publishes, withdraws or sweeps."""
PUBLISHED_STATUSES = sorted(status.value for status in IN_FORCE_STATUSES)
CITING_STATUS_VALUES = sorted(status.value for status in CITING_STATUSES)
REPLACING_KINDS = sorted(kind.value for kind in REPLACING)
CHANGE_ACTION_VALUES = sorted(action.value for action in CHANGE_ACTIONS)
ENGLISH: ColumnElement[str] = literal_column("'english'::regconfig")
HNSW_EF_SEARCH = 100
"""Candidates the HNSW scan keeps (pgvector's default is 40): at least the largest pool."""


class SqlAlchemyDocumentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, document_id: DocumentId) -> StoredDocument | None:
        row = self._session.get(DocumentRow, document_id.value)
        return None if row is None else _to_document(row)

    def add(self, document: StoredDocument) -> bool:
        statement = (
            insert(DocumentRow)
            .values(_document_values(document))
            .on_conflict_do_nothing()
            .returning(DocumentRow.id)
        )
        return self._session.execute(statement).first() is not None

    def clauses(self, document_id: DocumentId) -> tuple[StoredClause, ...]:
        statement = (
            select(ClauseRow)
            .where(ClauseRow.document_id == document_id.value)
            .order_by(ClauseRow.ordinal)
        )
        return tuple(_to_clause(row) for row in self._session.scalars(statement))

    def add_clauses(self, clauses: Sequence[StoredClause]) -> None:
        if not clauses:
            return
        values = [
            {
                "id": clause.clause_id.value,
                "document_id": clause.document_id.value,
                "clause_ref": clause.clause_ref,
                "ordinal": clause.ordinal,
                "text": clause.text,
                "text_sha256": clause.text_sha256,
                "page": clause.page,
            }
            for clause in clauses
        ]
        self._session.execute(insert(ClauseRow).values(values).on_conflict_do_nothing())

    def clause(self, clause_id: ClauseId) -> ClauseDetail | None:
        found = self._session.execute(
            select(ClauseRow, DocumentRow)
            .join(DocumentRow, DocumentRow.id == ClauseRow.document_id)
            .where(ClauseRow.id == clause_id.value)
        ).first()
        return None if found is None else ClauseDetail(_to_clause(found[0]), _to_document(found[1]))


class SqlAlchemyEntityRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def by_name(self, entity_type: EntityType, name: str) -> CanonicalEntityId | None:
        found = self._session.scalar(
            select(CanonicalEntityRow.id).where(
                CanonicalEntityRow.type == entity_type.value,
                CanonicalEntityRow.canonical_name == name,
            )
        )
        return None if found is None else CanonicalEntityId(found)

    def by_alias(self, entity_type: EntityType, alias: str) -> Sequence[CanonicalEntityId]:
        statement = (
            select(CanonicalEntityRow.id)
            .where(
                CanonicalEntityRow.type == entity_type.value,
                CanonicalEntityRow.aliases.contains([alias]),
            )
            .order_by(CanonicalEntityRow.id)
        )
        return [CanonicalEntityId(found) for found in self._session.scalars(statement)]

    def get(self, entity_id: CanonicalEntityId) -> tuple[EntityType, str] | None:
        row = self._session.get(CanonicalEntityRow, entity_id.value)
        return None if row is None else (EntityType(row.type), row.canonical_name)

    def create_or_get(self, entity_type: EntityType, name: str) -> tuple[CanonicalEntityId, bool]:
        new_id = CanonicalEntityId.new()
        inserted = self._session.execute(
            insert(CanonicalEntityRow)
            .values(id=new_id.value, type=entity_type.value, canonical_name=name)
            .on_conflict_do_nothing()
            .returning(CanonicalEntityRow.id)
        ).first()
        if inserted is not None:
            return new_id, True
        existing = self.by_name(entity_type, name)
        if existing is None:
            raise RuntimeError(f"{entity_type.value} {name!r} neither inserted nor found")
        return existing, False

    def add_alias(self, entity_id: CanonicalEntityId, alias: str) -> bool:
        statement = (
            update(CanonicalEntityRow)
            .where(
                CanonicalEntityRow.id == entity_id.value,
                ~CanonicalEntityRow.aliases.contains([alias]),
            )
            .values(aliases=func.array_append(CanonicalEntityRow.aliases, alias))
            .returning(CanonicalEntityRow.id)
        )
        return self._session.execute(statement).first() is not None

    def describe(self, entity_id: CanonicalEntityId) -> EntityRecord | None:
        row = self._session.get(CanonicalEntityRow, entity_id.value)
        if row is None:
            return None
        return EntityRecord(
            CanonicalEntityId(row.id), EntityType(row.type), row.canonical_name, tuple(row.aliases)
        )


class SqlAlchemyMentionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

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
        statement = (
            insert(ClauseEntityRow)
            .values(
                clause_id=clause_id.value,
                entity_id=entity_id.value,
                mention_text=mention_text,
                span_start=span_start,
                span_end=span_end,
                method=method,
                extractor=extractor,
            )
            .on_conflict_do_nothing()
            .returning(ClauseEntityRow.clause_id)
        )
        return self._session.execute(statement).first() is not None

    def entity_at(
        self, clause_id: ClauseId, span_start: int, entity_type: EntityType
    ) -> CanonicalEntityId | None:
        found = self._session.scalar(
            select(ClauseEntityRow.entity_id)
            .join(CanonicalEntityRow, CanonicalEntityRow.id == ClauseEntityRow.entity_id)
            .where(
                ClauseEntityRow.clause_id == clause_id.value,
                ClauseEntityRow.span_start == span_start,
                CanonicalEntityRow.type == entity_type.value,
            )
            .order_by(ClauseEntityRow.entity_id)
            .limit(1)
        )
        return None if found is None else CanonicalEntityId(found)

    def clauses_mentioning(
        self, entity_id: CanonicalEntityId, as_of: date | None, limit: int
    ) -> Sequence[MentionedClause]:
        mentioned = select(ClauseEntityRow.clause_id).where(
            ClauseEntityRow.entity_id == entity_id.value
        )
        statement = (
            select(ClauseRow, DocumentRow)
            .join(DocumentRow, DocumentRow.id == ClauseRow.document_id)
            .where(ClauseRow.id.in_(mentioned))
            .order_by(
                DocumentRow.published_at.desc().nulls_last(), DocumentRow.id, ClauseRow.ordinal
            )
            .limit(limit)
        )
        if as_of is not None:
            statement = statement.where(DocumentRow.published_at <= as_of)
        rows = self._session.execute(statement).all()
        spans: dict[UUID, list[MentionSpan]] = {}
        for clause_id, mention_text, span_start, span_end in self._session.execute(
            select(
                ClauseEntityRow.clause_id,
                ClauseEntityRow.mention_text,
                ClauseEntityRow.span_start,
                ClauseEntityRow.span_end,
            )
            .where(
                ClauseEntityRow.entity_id == entity_id.value,
                ClauseEntityRow.clause_id.in_([clause.id for clause, _ in rows]),
            )
            .order_by(ClauseEntityRow.clause_id, ClauseEntityRow.span_start)
        ).all():
            spans.setdefault(clause_id, []).append(MentionSpan(mention_text, span_start, span_end))
        out = _out_of_force(self._session, [clause.id for clause, _ in rows], as_of)
        return [
            MentionedClause(
                ClauseDetail(_to_clause(clause), _to_document(document)),
                tuple(spans[clause.id]),
                clause.id in out,
            )
            for clause, document in rows
        ]


class SqlAlchemyReviewRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def enqueue(self, item: EntityReviewItem) -> bool:
        statement = (
            insert(EntityReviewRow)
            .values(_review_values(item))
            .on_conflict_do_nothing()
            .returning(EntityReviewRow.id)
        )
        return self._session.execute(statement).first() is not None

    def open_groups(
        self, entity_type: EntityType | None, limit: int, after: tuple[str, str] | None
    ) -> Sequence[MentionGroup]:
        key = tuple_(EntityReviewRow.entity_type, EntityReviewRow.proposed_name)
        statement = (
            select(EntityReviewRow.entity_type, EntityReviewRow.proposed_name, func.count())
            .where(EntityReviewRow.status == ReviewStatus.OPEN.value)
            .group_by(EntityReviewRow.entity_type, EntityReviewRow.proposed_name)
            .order_by(EntityReviewRow.entity_type, EntityReviewRow.proposed_name)
            .limit(limit)
        )
        if entity_type is not None:
            statement = statement.where(EntityReviewRow.entity_type == entity_type.value)
        if after is not None:
            statement = statement.where(key > tuple_(*after))
        groups: list[MentionGroup] = []
        for group_type, name, count in self._session.execute(statement).all():
            examples = self._session.scalars(
                select(EntityReviewRow)
                .where(
                    EntityReviewRow.status == ReviewStatus.OPEN.value,
                    EntityReviewRow.entity_type == group_type,
                    EntityReviewRow.proposed_name == name,
                )
                .order_by(EntityReviewRow.document_id, EntityReviewRow.clause_id)
                .limit(EXAMPLES_PER_GROUP)
            )
            groups.append(
                MentionGroup(
                    entity_type=EntityType(group_type),
                    proposed_name=name,
                    open_count=int(count),
                    examples=tuple(_to_review(row) for row in examples),
                )
            )
        return groups

    def lock_group(
        self, entity_type: EntityType, proposed_name: str
    ) -> tuple[EntityReviewItem, ...]:
        statement = (
            select(EntityReviewRow)
            .where(
                EntityReviewRow.entity_type == entity_type.value,
                EntityReviewRow.proposed_name == proposed_name,
            )
            .order_by(EntityReviewRow.id)
            .with_for_update()
        )
        return tuple(_to_review(row) for row in self._session.scalars(statement))

    def group_items(
        self, entity_type: EntityType, proposed_name: str
    ) -> tuple[EntityReviewItem, ...]:
        statement = (
            select(EntityReviewRow)
            .where(
                EntityReviewRow.status == ReviewStatus.OPEN.value,
                EntityReviewRow.entity_type == entity_type.value,
                EntityReviewRow.proposed_name == proposed_name,
            )
            .order_by(EntityReviewRow.id)
        )
        return tuple(_to_review(row) for row in self._session.scalars(statement))

    def save(self, item: EntityReviewItem) -> None:
        self._session.execute(
            update(EntityReviewRow)
            .where(EntityReviewRow.id == item.review_id)
            .values(
                status=item.status.value,
                resolution=None if item.resolution is None else item.resolution.value,
                resolved_entity_id=None
                if item.resolved_entity_id is None
                else item.resolved_entity_id.value,
                reject_reason=None if item.reject_reason is None else item.reject_reason.value,
                decided_by=item.decided_by,
                decided_at=item.decided_at,
                note=item.note,
            )
        )

    def queue_stats(self) -> ReviewQueueStats:
        statement = (
            select(EntityReviewRow.entity_type, func.count(), func.min(EntityReviewRow.created_at))
            .where(EntityReviewRow.status == ReviewStatus.OPEN.value)
            .group_by(EntityReviewRow.entity_type)
        )
        rows = self._session.execute(statement).all()
        return ReviewQueueStats(
            by_type={EntityType(entity_type): int(count) for entity_type, count, _ in rows},
            oldest_open_at=min((oldest.astimezone(UTC) for _, _, oldest in rows), default=None),
        )


class SqlAlchemyCandidateRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, candidate: RelationCandidate) -> bool:
        statement = (
            insert(RelationCandidateRow)
            .values(_candidate_values(candidate))
            .on_conflict_do_nothing()
            .returning(RelationCandidateRow.id)
        )
        return self._session.execute(statement).first() is not None

    def lock(self, candidate_id: UUID) -> RelationCandidate | None:
        row = self._session.scalar(
            select(RelationCandidateRow)
            .where(RelationCandidateRow.id == candidate_id)
            .with_for_update()
        )
        return None if row is None else _to_candidate(row)

    def page(
        self,
        status: CandidateStatus | None,
        document_id: DocumentId | None,
        limit: int,
        after: UUID | None,
    ) -> Sequence[RelationCandidate]:
        statement = select(RelationCandidateRow).order_by(RelationCandidateRow.id).limit(limit)
        if status is not None:
            statement = statement.where(RelationCandidateRow.status == status.value)
        if document_id is not None:
            statement = statement.where(RelationCandidateRow.document_id == document_id.value)
        if after is not None:
            statement = statement.where(RelationCandidateRow.id > after)
        return [_to_candidate(row) for row in self._session.scalars(statement)]

    def save(self, candidate: RelationCandidate) -> None:
        values = _candidate_values(candidate)
        values.pop("id")
        self._session.execute(
            update(RelationCandidateRow)
            .where(RelationCandidateRow.id == candidate.candidate_id)
            .values(values)
        )

    def set_target_entity(
        self, entity_type: EntityType, name: str, entity_id: CanonicalEntityId
    ) -> int:
        result = self._session.execute(
            update(RelationCandidateRow)
            .where(
                RelationCandidateRow.status == CandidateStatus.OPEN.value,
                RelationCandidateRow.target_entity_id.is_(None),
                RelationCandidateRow.target_type == entity_type.value,
                RelationCandidateRow.target_name == name,
            )
            .values(target_entity_id=entity_id.value)
            .returning(RelationCandidateRow.id)
        )
        return len(result.all())

    def set_target_entity_at(
        self,
        clause_id: ClauseId,
        span_start: int,
        entity_type: EntityType,
        entity_id: CanonicalEntityId,
    ) -> int:
        result = self._session.execute(
            update(RelationCandidateRow)
            .where(
                RelationCandidateRow.status == CandidateStatus.OPEN.value,
                RelationCandidateRow.target_entity_id.is_(None),
                RelationCandidateRow.target_type == entity_type.value,
                RelationCandidateRow.target_clause_id == clause_id.value,
                RelationCandidateRow.target_span_start == span_start,
            )
            .values(target_entity_id=entity_id.value)
            .returning(RelationCandidateRow.id)
        )
        return len(result.all())


class SqlAlchemyRelationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, relation: RuleRelation, *, relation_id: UUID, candidate_id: UUID | None) -> bool:
        target = relation.target
        statement = (
            insert(RuleRelationRow)
            .values(
                id=relation_id,
                from_rule_version_id=relation.from_rule_version_id.value,
                relation=relation.relation.value,
                to_kind=relation.to_kind,
                to_ref=relation.to_ref,
                to_entity_id=target.entity_id.value
                if isinstance(target, EntityRef) and target.entity_id is not None
                else None,
                to_rule_version_id=target.value if isinstance(target, RuleVersionId) else None,
                clause_id=relation.evidence_clause_id.value,
                candidate_id=candidate_id,
            )
            .on_conflict_do_nothing()
            .returning(RuleRelationRow.id)
        )
        return self._session.execute(statement).first() is not None

    def supersedes_edges(self) -> Mapping[RuleVersionId, frozenset[RuleVersionId]]:
        rows = self._session.execute(
            select(RuleRelationRow.from_rule_version_id, RuleRelationRow.to_rule_version_id).where(
                RuleRelationRow.relation == RelationKind.SUPERSEDES.value,
                RuleRelationRow.to_rule_version_id.is_not(None),
            )
        ).all()
        edges: dict[RuleVersionId, set[RuleVersionId]] = {}
        for source, target in rows:
            if target is not None:
                edges.setdefault(RuleVersionId(source), set()).add(RuleVersionId(target))
        return {source: frozenset(targets) for source, targets in edges.items()}

    def lock_supersession(self) -> None:
        self._session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": SUPERSESSION_LOCK}
        )

    def remove_approved(self, rule_version_id: RuleVersionId) -> tuple[UUID, ...]:
        removed = self._session.scalars(
            delete(RuleRelationRow)
            .where(
                RuleRelationRow.from_rule_version_id == rule_version_id.value,
                RuleRelationRow.candidate_id.is_not(None),
            )
            .returning(RuleRelationRow.candidate_id)
        ).all()
        return tuple(sorted((candidate for candidate in removed if candidate), key=str))

    def find(self, query: RelationQuery) -> Sequence[RelationRecord]:
        statement = (
            select(
                RuleRelationRow,
                ClauseRow.clause_ref,
                ClauseRow.document_id,
                RelationCandidateRow.period_label,
                RelationCandidateRow.new_due_on,
            )
            .join(ClauseRow, ClauseRow.id == RuleRelationRow.clause_id)
            .outerjoin(
                RelationCandidateRow, RelationCandidateRow.id == RuleRelationRow.candidate_id
            )
            .order_by(RuleRelationRow.id)
            .limit(query.limit)
        )
        if query.from_rule_version_id is not None:
            statement = statement.where(
                RuleRelationRow.from_rule_version_id == query.from_rule_version_id.value
            )
        if query.to_rule_version_id is not None:
            statement = statement.where(
                RuleRelationRow.to_rule_version_id == query.to_rule_version_id.value
            )
        if query.to_entity_id is not None:
            statement = statement.where(RuleRelationRow.to_entity_id == query.to_entity_id.value)
        if query.relation is not None:
            statement = statement.where(RuleRelationRow.relation == query.relation.value)
        if query.published_only:
            statement = statement.join(
                RuleVersionRow, RuleVersionRow.id == RuleRelationRow.from_rule_version_id
            ).where(RuleVersionRow.status.in_(PUBLISHED_STATUSES))
        return [
            RelationRecord(
                relation_id=row.id,
                from_rule_version_id=RuleVersionId(row.from_rule_version_id),
                relation=RelationKind(row.relation),
                to_kind=row.to_kind,
                to_ref=row.to_ref,
                to_rule_version_id=None
                if row.to_rule_version_id is None
                else RuleVersionId(row.to_rule_version_id),
                to_entity_id=None
                if row.to_entity_id is None
                else CanonicalEntityId(row.to_entity_id),
                evidence_clause_id=ClauseId(row.clause_id),
                evidence_clause_ref=clause_ref,
                evidence_document_id=DocumentId(document_id),
                candidate_id=row.candidate_id,
                period_label=period_label,
                new_due_on=new_due_on,
            )
            for row, clause_ref, document_id, period_label, new_due_on in self._session.execute(
                statement
            ).all()
        ]


class SqlAlchemyRuleCatalog:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_rules(self) -> tuple[RuleSummary, ...]:
        latest = (
            select(RuleVersionRow.rule_id, func.max(RuleVersionRow.version).label("version"))
            .where(~closed_version())
            .group_by(RuleVersionRow.rule_id)
            .subquery()
        )
        statement = (
            select(RuleRow.rule_key, RuleRow.id, RuleRow.regulator, RuleVersionRow.title)
            .join(latest, latest.c.rule_id == RuleRow.id)
            .join(
                RuleVersionRow,
                and_(
                    RuleVersionRow.rule_id == RuleRow.id,
                    RuleVersionRow.version == latest.c.version,
                ),
            )
            .order_by(RuleRow.rule_key)
        )
        return tuple(
            RuleSummary(rule_key, rule_id, regulator, title)
            for rule_key, rule_id, regulator, title in self._session.execute(statement).all()
        )

    def rule_id(self, rule_key: str) -> UUID | None:
        found: UUID | None = self._session.scalar(
            select(RuleRow.id).where(RuleRow.rule_key == rule_key)
        )
        return found

    def version_status(self, rule_version_id: RuleVersionId) -> RuleVersionStatus | None:
        found = self._session.scalar(
            select(RuleVersionRow.status).where(RuleVersionRow.id == rule_version_id.value)
        )
        return None if found is None else RuleVersionStatus(found)


class SqlAlchemyRuleVersionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def in_force(self, as_of: date, page: VersionPage) -> Sequence[RuleVersionRecord]:
        return self._page(_in_force_on(as_of), page)

    def ended(self, since: date, page: VersionPage) -> Sequence[RuleVersionRecord]:
        return self._page(_ended_since(since), page)

    def _page(self, listed: ColumnElement[bool], page: VersionPage) -> list[RuleVersionRecord]:
        statement = (
            _versions()
            .where(listed)
            .order_by(RuleRow.rule_key, RuleVersionRow.version)
            .limit(page.limit)
        )
        if page.status is not None:
            statement = statement.where(RuleVersionRow.status == page.status.value)
        if page.rule_key is not None:
            statement = statement.where(RuleRow.rule_key == page.rule_key)
        if page.regulator is not None:
            statement = statement.where(RuleRow.regulator == page.regulator)
        if page.after is not None:
            statement = statement.where(_after(page.after, page.after_version))
        return [_to_version(*row) for row in self._session.execute(statement).all()]

    def get(self, rule_version_id: RuleVersionId) -> RuleVersionRecord | None:
        row = self._session.execute(
            _versions().where(RuleVersionRow.id == rule_version_id.value)
        ).first()
        return None if row is None else _to_version(*row)

    def lock(self, rule_version_id: RuleVersionId) -> RuleVersionRecord | None:
        row = self._session.execute(
            _versions()
            .where(RuleVersionRow.id == rule_version_id.value)
            .with_for_update(of=RuleVersionRow)
        ).first()
        return None if row is None else _to_version(*row)

    def lock_many(
        self, rule_version_ids: Sequence[RuleVersionId]
    ) -> Mapping[RuleVersionId, RuleVersionRecord]:
        ids = sorted({version.value for version in rule_version_ids}, key=str)
        if not ids:
            return {}
        rows = self._session.execute(
            _versions()
            .where(RuleVersionRow.id.in_(ids))
            .order_by(RuleVersionRow.id)
            .with_for_update(of=RuleVersionRow)
        ).all()
        records = [_to_version(*row) for row in rows]
        return {record.rule_version_id: record for record in records}

    def of_rule(self, rule_id: RuleId) -> Sequence[RuleVersionRecord]:
        rows = self._session.execute(
            _versions()
            .where(RuleVersionRow.rule_id == rule_id.value)
            .order_by(RuleVersionRow.version)
        ).all()
        return [_to_version(*row) for row in rows]

    def save_lifecycle(self, record: RuleVersionRecord) -> None:
        row = self._session.get(RuleVersionRow, record.rule_version_id.value)
        if row is None:
            raise UnknownRuleVersionError(str(record.rule_version_id))
        row.status = record.status.value
        row.seed_status = record.seed_status.value
        row.effective_to = record.effective_to
        row.published_at = record.published_at
        row.submitted_at = record.submitted_at
        row.high_impact = record.high_impact
        self._session.flush()

    def save_draft(self, record: RuleVersionRecord) -> None:
        row = self._session.get(RuleVersionRow, record.rule_version_id.value)
        if row is None:
            raise UnknownRuleVersionError(str(record.rule_version_id))
        row.title = record.title
        row.summary = record.summary
        row.specification = dict(record.specification)
        row.obligation_template = dict(record.obligation_template)
        row.recurrence = None if record.recurrence is None else dict(record.recurrence)
        row.effective_from = record.effective_from
        row.effective_to = record.effective_to
        row.todo = list(record.todo)
        self._session.flush()

    def record_decision(self, decision: RuleVersionDecision) -> None:
        self._session.execute(
            insert(RuleVersionDecisionRow).values(
                id=decision.decision_id,
                rule_version_id=decision.rule_version_id.value,
                action=decision.action.value,
                from_status=decision.from_status.value,
                to_status=decision.to_status.value,
                actor_id=None if decision.actor_id is None else decision.actor_id.value,
                caused_by_rule_version_id=None
                if decision.caused_by is None
                else decision.caused_by.value,
                note=decision.note,
                decided_at=decision.decided_at,
            )
        )

    def decisions(self, rule_version_id: RuleVersionId) -> tuple[RuleVersionDecision, ...]:
        rows = self._session.execute(
            select(RuleVersionDecisionRow.__table__)
            .where(RuleVersionDecisionRow.rule_version_id == rule_version_id.value)
            .order_by(RuleVersionDecisionRow.decided_at, RuleVersionDecisionRow.id)
        ).all()
        return tuple(
            RuleVersionDecision(
                decision_id=row.id,
                rule_version_id=RuleVersionId(row.rule_version_id),
                action=DecisionAction(row.action),
                from_status=RuleVersionStatus(row.from_status),
                to_status=RuleVersionStatus(row.to_status),
                decided_at=row.decided_at,
                actor_id=None if row.actor_id is None else UserId(row.actor_id),
                caused_by=None
                if row.caused_by_rule_version_id is None
                else RuleVersionId(row.caused_by_rule_version_id),
                note=row.note,
            )
            for row in rows
        )

    def approvers(self, rule_version_id: RuleVersionId, since: datetime) -> frozenset[UserId]:
        found = self._session.scalars(
            select(RuleVersionDecisionRow.actor_id)
            .where(
                RuleVersionDecisionRow.rule_version_id == rule_version_id.value,
                RuleVersionDecisionRow.action == DecisionAction.APPROVED.value,
                RuleVersionDecisionRow.actor_id.is_not(None),
                RuleVersionDecisionRow.decided_at >= since,
            )
            .distinct()
        )
        return frozenset(UserId(actor) for actor in found if actor is not None)

    def replaced_by_others(
        self, rule_version_ids: Sequence[RuleVersionId], excluding: RuleVersionId
    ) -> frozenset[RuleVersionId]:
        if not rule_version_ids:
            return frozenset()
        found = self._session.scalars(
            select(RuleRelationRow.to_rule_version_id)
            .join(RuleVersionRow, RuleVersionRow.id == RuleRelationRow.from_rule_version_id)
            .where(
                RuleRelationRow.relation.in_(REPLACING_KINDS),
                RuleRelationRow.to_rule_version_id.in_([v.value for v in rule_version_ids]),
                RuleRelationRow.from_rule_version_id != excluding.value,
                RuleVersionRow.status.in_(PUBLISHED_STATUSES),
            )
            .distinct()
        )
        return frozenset(RuleVersionId(target) for target in found if target is not None)

    def pending_replacements(self, today: date) -> Sequence[PendingReplacement]:
        replacing = aliased(RuleVersionRow)
        target = aliased(RuleVersionRow)
        rows = self._session.execute(
            select(
                RuleRelationRow.relation,
                target.id,
                target.rule_id,
                replacing.id,
                replacing.effective_from,
            )
            .join(replacing, replacing.id == RuleRelationRow.from_rule_version_id)
            .join(target, target.id == RuleRelationRow.to_rule_version_id)
            .where(
                RuleRelationRow.relation.in_(REPLACING_KINDS),
                replacing.status.in_(PUBLISHED_STATUSES),
                replacing.effective_from <= today,
                target.status == RuleVersionStatus.PUBLISHED.value,
            )
            .order_by(replacing.effective_from, target.id, replacing.id)
        ).all()
        return [
            PendingReplacement(
                relation=RelationKind(relation),
                target_id=RuleVersionId(target_id),
                target_rule_id=RuleId(target_rule_id),
                replacing_id=RuleVersionId(replacing_id),
                replacing_from=replacing_from,
            )
            for relation, target_id, target_rule_id, replacing_id, replacing_from in rows
        ]

    def lock_publication(self) -> None:
        self._session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": PUBLICATION_LOCK})

    def changes(self, query: ChangeQuery) -> Sequence[ChangeEntry]:
        changes = _changes().subquery("changes")
        statement = (
            select(changes)
            .join(RuleVersionRow, RuleVersionRow.id == changes.c.rule_version_id)
            .join(RuleRow, RuleRow.id == RuleVersionRow.rule_id)
            .order_by(changes.c.changed_at.desc(), changes.c.change_id.desc())
            .limit(query.limit)
        )
        if query.since is not None:
            statement = statement.where(changes.c.changed_at >= query.since)
        if query.regulator is not None:
            statement = statement.where(RuleRow.regulator == query.regulator)
        if query.after is not None:
            statement = statement.where(
                tuple_(changes.c.changed_at, changes.c.change_id)
                < tuple_(query.after.changed_at, query.after.change_id)
            )
        return [
            ChangeEntry(
                change_id=row.change_id,
                kind=RuleChangeKind(row.kind),
                changed_at=row.changed_at.astimezone(UTC),
                rule_version_id=RuleVersionId(row.rule_version_id),
                caused_by=None if row.caused_by is None else RuleVersionId(row.caused_by),
                period_label=row.period_label,
                new_due_on=row.new_due_on,
                evidence_clause_id=None
                if row.evidence_clause_id is None
                else ClauseId(row.evidence_clause_id),
            )
            for row in self._session.execute(statement).all()
        ]

    def lock_rule(self, rule_key: str) -> RuleHead | None:
        rule = self._session.execute(
            select(RuleRow.id, RuleRow.regulator, RuleRow.level)
            .where(RuleRow.rule_key == rule_key)
            .with_for_update()
        ).first()
        if rule is None:
            return None
        last = self._session.scalar(
            select(func.max(RuleVersionRow.version)).where(RuleVersionRow.rule_id == rule.id)
        )
        return RuleHead(
            rule_id=RuleId(rule.id),
            rule_key=rule_key,
            regulator=rule.regulator,
            level=AttributeLevel(rule.level),
            last_version=int(last or 0),
        )

    def add_rule_and_version(self, record: RuleVersionRecord, *, new_rule: bool) -> None:
        if new_rule:
            inserted = self._session.execute(
                insert(RuleRow)
                .values(
                    id=record.rule_id.value,
                    rule_key=record.rule_key,
                    regulator=record.regulator,
                    level=record.level.value,
                )
                .on_conflict_do_nothing()
                .returning(RuleRow.id)
            ).first()
            if inserted is None:
                raise RuleKeyTakenError(record.rule_key)
        self._session.execute(
            insert(RuleVersionRow).values(
                id=record.rule_version_id.value,
                rule_id=record.rule_id.value,
                version=record.version,
                status=record.status.value,
                title=record.title,
                summary=record.summary,
                specification=dict(record.specification),
                obligation_template=dict(record.obligation_template),
                recurrence=None if record.recurrence is None else dict(record.recurrence),
                effective_from=record.effective_from,
                effective_to=record.effective_to,
                source=dict(record.source),
                seed_status=record.seed_status.value,
                todo=list(record.todo),
                high_impact=record.high_impact,
                candidate_id=record.candidate_id,
            )
        )


class SqlAlchemyCitationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def for_version(self, rule_version_id: RuleVersionId) -> tuple[CitationRecord, ...]:
        statement = (
            select(CitationRow, ClauseRow.clause_ref, ClauseRow.document_id)
            .join(ClauseRow, ClauseRow.id == CitationRow.clause_id)
            .where(CitationRow.rule_version_id == rule_version_id.value)
            .order_by(ClauseRow.document_id, ClauseRow.ordinal, CitationRow.id)
        )
        return tuple(
            CitationRecord(
                citation_id=row.id,
                rule_version_id=RuleVersionId(row.rule_version_id),
                clause_id=ClauseId(row.clause_id),
                document_id=DocumentId(document_id),
                clause_ref=clause_ref,
                quote=row.quote,
                verified=row.verified,
                match_score=None if row.match_score is None else float(row.match_score),
                verified_at=row.verified_at,
            )
            for row, clause_ref, document_id in self._session.execute(statement).all()
        )

    def add(self, citation: CitationRecord) -> bool:
        statement = (
            insert(CitationRow)
            .values(
                id=citation.citation_id,
                rule_version_id=citation.rule_version_id.value,
                clause_id=citation.clause_id.value,
                quote=citation.quote,
                verified=citation.verified,
                match_score=None if citation.match_score is None else _score(citation.match_score),
                verified_at=citation.verified_at,
            )
            .on_conflict_do_nothing()
            .returning(CitationRow.id)
        )
        return self._session.execute(statement).first() is not None


REVIEW_TASKS = ReviewTaskRow.__table__
UNDECIDED_STATUSES = sorted(status.value for status in UNDECIDED)


class SqlAlchemyRuleCandidateRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, candidate: RuleCandidate) -> bool:
        statement = (
            insert(RuleCandidateRow)
            .values(_rule_candidate_values(candidate))
            .on_conflict_do_nothing()
            .returning(RuleCandidateRow.id)
        )
        return self._session.execute(statement).first() is not None

    def get(self, candidate_id: UUID) -> RuleCandidate | None:
        row = self._session.scalar(
            select(RuleCandidateRow).where(RuleCandidateRow.id == candidate_id)
        )
        return None if row is None else _to_rule_candidate(row)

    def lock(self, candidate_id: UUID) -> RuleCandidate | None:
        row = self._session.scalar(
            select(RuleCandidateRow).where(RuleCandidateRow.id == candidate_id).with_for_update()
        )
        return None if row is None else _to_rule_candidate(row)

    def save(self, candidate: RuleCandidate) -> None:
        saved = self._session.execute(
            update(RuleCandidateRow)
            .where(RuleCandidateRow.id == candidate.candidate_id)
            .values(
                status=candidate.status.value,
                rule_version_id=None
                if candidate.rule_version_id is None
                else candidate.rule_version_id.value,
                reject_reason=None
                if candidate.reject_reason is None
                else candidate.reject_reason.value,
                decided_by=None if candidate.decided_by is None else candidate.decided_by.value,
                decided_at=candidate.decided_at,
            )
            .returning(RuleCandidateRow.id)
        ).first()
        if saved is None:
            raise RuleCandidateNotFoundError(
                f"rule candidate {candidate.candidate_id} is not stored"
            )

    def decided_since(self, since: datetime) -> Sequence[RuleCandidate]:
        rows = self._session.scalars(
            select(RuleCandidateRow)
            .where(RuleCandidateRow.decided_at >= since)
            .order_by(RuleCandidateRow.decided_at, RuleCandidateRow.id)
        ).all()
        return [_to_rule_candidate(row) for row in rows]


class SqlAlchemyReviewTaskRepository:
    """Review tasks read and written as plain rows (never ORM objects), so a task written in a
    transaction reads back as written in the same one. ``add`` leaves it to the partial unique
    index to keep one task per version that is not decided, so two concurrent seed requests
    open one task between them."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, task: ReviewTask) -> bool:
        statement = (
            insert(ReviewTaskRow)
            .values(_task_values(task))
            .on_conflict_do_nothing()
            .returning(ReviewTaskRow.id)
        )
        return self._session.execute(statement).first() is not None

    def get(self, task_id: UUID) -> ReviewTask | None:
        row = self._session.execute(
            select(REVIEW_TASKS).where(REVIEW_TASKS.c.id == task_id)
        ).first()
        return None if row is None else _to_task(row)

    def lock(self, task_id: UUID) -> ReviewTask | None:
        row = self._session.execute(
            select(REVIEW_TASKS).where(REVIEW_TASKS.c.id == task_id).with_for_update()
        ).first()
        return None if row is None else _to_task(row)

    def save(self, task: ReviewTask) -> None:
        values = _task_values(task)
        for fixed in ("id", "kind", "candidate_id", "regulator", "opened_at"):
            values.pop(fixed)
        saved = self._session.execute(
            update(ReviewTaskRow)
            .where(ReviewTaskRow.id == task.task_id, ReviewTaskRow.status.in_(UNDECIDED_STATUSES))
            .values(values)
            .returning(ReviewTaskRow.id)
        ).first()
        if saved is None:
            if self.get(task.task_id) is None:
                raise ReviewTaskNotFoundError(f"review task {task.task_id} is not stored")
            raise ReviewTaskClosedError(f"review task {task.task_id}: a decided task never changes")

    def page(self, query: TaskQuery) -> Sequence[QueuedTask]:
        approvals = (
            select(func.count(func.distinct(RuleVersionDecisionRow.actor_id)))
            .where(
                RuleVersionDecisionRow.rule_version_id == REVIEW_TASKS.c.rule_version_id,
                RuleVersionDecisionRow.action == DecisionAction.APPROVED.value,
                RuleVersionDecisionRow.actor_id.is_not(None),
                RuleVersionDecisionRow.decided_at >= RuleVersionRow.submitted_at,
            )
            .correlate(REVIEW_TASKS, RuleVersionRow)
            .scalar_subquery()
        )
        statement = (
            select(
                REVIEW_TASKS,
                RuleRow.rule_key,
                RuleVersionRow.version,
                RuleVersionRow.title,
                RuleVersionRow.status.label("version_status"),
                RuleVersionRow.high_impact,
                approvals.label("approvals"),
                RuleCandidateRow,
            )
            .outerjoin(RuleVersionRow, RuleVersionRow.id == REVIEW_TASKS.c.rule_version_id)
            .outerjoin(RuleRow, RuleRow.id == RuleVersionRow.rule_id)
            .outerjoin(RuleCandidateRow, RuleCandidateRow.id == REVIEW_TASKS.c.candidate_id)
            .order_by(
                REVIEW_TASKS.c.regulator,
                REVIEW_TASKS.c.priority.desc(),
                REVIEW_TASKS.c.opened_at,
                REVIEW_TASKS.c.id,
            )
            .limit(query.limit)
        )
        if query.status is not None:
            statement = statement.where(REVIEW_TASKS.c.status == query.status.value)
        if query.regulator is not None:
            statement = statement.where(func.lower(REVIEW_TASKS.c.regulator) == query.regulator)
        if query.kind is not None:
            statement = statement.where(REVIEW_TASKS.c.kind == query.kind.value)
        if query.after is not None:
            statement = statement.where(_after_task(query.after))
        return [_to_queued(row) for row in self._session.execute(statement).all()]

    def of_version(self, rule_version_id: RuleVersionId) -> tuple[ReviewTask, ...]:
        rows = self._session.execute(
            select(REVIEW_TASKS)
            .where(REVIEW_TASKS.c.rule_version_id == rule_version_id.value)
            .order_by(REVIEW_TASKS.c.opened_at, REVIEW_TASKS.c.id)
        ).all()
        return tuple(_to_task(row) for row in rows)

    def of_candidate(self, candidate_id: UUID) -> tuple[ReviewTask, ...]:
        rows = self._session.execute(
            select(REVIEW_TASKS)
            .where(REVIEW_TASKS.c.candidate_id == candidate_id)
            .order_by(REVIEW_TASKS.c.opened_at, REVIEW_TASKS.c.id)
        ).all()
        return tuple(_to_task(row) for row in rows)

    def drafts_without_task(self) -> Sequence[RuleVersionRecord]:
        undecided = select(REVIEW_TASKS.c.id).where(
            REVIEW_TASKS.c.rule_version_id == RuleVersionRow.id,
            REVIEW_TASKS.c.status.in_(UNDECIDED_STATUSES),
        )
        rows = self._session.execute(
            _versions()
            .where(
                RuleVersionRow.status == RuleVersionStatus.DRAFT.value,
                RuleVersionRow.seed_status == SeedStatus.NEEDS_REVIEW.value,
                RuleVersionRow.candidate_id.is_(None),
                ~undecided.exists(),
            )
            .order_by(RuleRow.rule_key, RuleVersionRow.version)
        ).all()
        return [_to_version(*row) for row in rows]

    def stats(self) -> ReviewTaskStats:
        counts: dict[str, dict[str, int]] = {}
        for regulator, status, count in self._session.execute(
            select(REVIEW_TASKS.c.regulator, REVIEW_TASKS.c.status, func.count()).group_by(
                REVIEW_TASKS.c.regulator, REVIEW_TASKS.c.status
            )
        ).all():
            counts.setdefault(regulator, {})[status] = int(count)
        decided = REVIEW_TASKS.c.status == ReviewTaskStatus.DECIDED.value
        decisions = {
            ReviewDecision(decision): int(count)
            for decision, count in self._session.execute(
                select(REVIEW_TASKS.c.decision, func.count())
                .where(decided)
                .group_by(REVIEW_TASKS.c.decision)
            ).all()
        }
        waited = func.extract("epoch", REVIEW_TASKS.c.decided_at - REVIEW_TASKS.c.opened_at)
        median = self._session.scalar(
            select(func.percentile_cont(0.5).within_group(waited)).where(decided)
        )
        oldest = self._session.scalar(
            select(func.min(REVIEW_TASKS.c.opened_at)).where(
                REVIEW_TASKS.c.status.in_(UNDECIDED_STATUSES)
            )
        )
        return ReviewTaskStats(
            by_regulator=tuple(
                RegulatorCounts(
                    regulator,
                    open=by_status.get(ReviewTaskStatus.OPEN.value, 0),
                    claimed=by_status.get(ReviewTaskStatus.CLAIMED.value, 0),
                    decided=by_status.get(ReviewTaskStatus.DECIDED.value, 0),
                )
                for regulator, by_status in sorted(counts.items())
            ),
            decisions=decisions,
            median_seconds_to_decide=None if median is None else float(median),
            oldest_open_at=None if oldest is None else oldest.astimezone(UTC),
            candidates=self._candidate_counts(),
        )

    def _candidate_counts(self) -> CandidateCounts:
        approved = RuleCandidateRow.status == RuleCandidateStatus.APPROVED.value
        edited = select(RuleVersionDecisionRow.id).where(
            RuleVersionDecisionRow.rule_version_id == RuleCandidateRow.rule_version_id,
            RuleVersionDecisionRow.action == DecisionAction.EDITED.value,
        )
        row = self._session.execute(
            select(
                func.count(RuleCandidateRow.id).filter(approved),
                func.count(RuleCandidateRow.id).filter(and_(approved, ~edited.exists())),
                func.count(RuleCandidateRow.id).filter(
                    RuleCandidateRow.status == RuleCandidateStatus.REJECTED.value
                ),
            )
        ).one()
        return CandidateCounts(
            approved=int(row[0]), approved_without_edits=int(row[1]), rejected=int(row[2])
        )


class SqlAlchemyEventSink:
    """Writes each event into ``outbox_event`` on the unit of work's connection, keyed by its
    rule, so the event commits or rolls back with the change it describes."""

    def __init__(self, session: Session, writer: OutboxWriter) -> None:
        self._session = session
        self._writer = writer

    def publish(self, event: RulebookEvent) -> None:
        self._writer.write(self._session.connection(), event, partition_key=event.partition_key)


class SqlAlchemyClauseIndex:
    def __init__(self, session: Session) -> None:
        self._session = session

    def store(self, model: str, embeddings: Sequence[ClauseEmbedding]) -> tuple[int, int]:
        if not embeddings:
            return 0, 0
        values = [
            {"clause_id": e.clause_id.value, "model": model, "embedding": e.vector}
            for e in embeddings
        ]
        inserted = self._session.execute(
            insert(ClauseEmbeddingRow)
            .values(values)
            .on_conflict_do_nothing()
            .returning(ClauseEmbeddingRow.clause_id)
        ).all()
        return len(inserted), len(embeddings) - len(inserted)

    def unknown_clauses(self, clause_ids: Sequence[ClauseId]) -> frozenset[ClauseId]:
        found = set(
            self._session.scalars(
                select(ClauseRow.id).where(ClauseRow.id.in_([c.value for c in clause_ids]))
            )
        )
        return frozenset(c for c in clause_ids if c.value not in found)

    def unembedded(
        self, model: str, document_id: DocumentId | None, limit: int, after: ClauseId | None
    ) -> Sequence[ClauseDetail]:
        embedded = select(ClauseEmbeddingRow.clause_id).where(
            ClauseEmbeddingRow.clause_id == ClauseRow.id, ClauseEmbeddingRow.model == model
        )
        statement = (
            select(ClauseRow, DocumentRow)
            .join(DocumentRow, DocumentRow.id == ClauseRow.document_id)
            .where(~embedded.exists())
            .order_by(ClauseRow.id)
            .limit(limit)
        )
        if document_id is not None:
            statement = statement.where(ClauseRow.document_id == document_id.value)
        if after is not None:
            statement = statement.where(ClauseRow.id > after.value)
        return [
            ClauseDetail(_to_clause(clause), _to_document(document))
            for clause, document in self._session.execute(statement).all()
        ]

    def lexical(self, text: str, filters: ClauseFilter, pool: int) -> Sequence[ClauseId]:
        query = _any_term(text)
        if not self._session.scalar(select(func.numnode(query))):
            return []
        statement = (
            select(ClauseRow.id)
            .join(DocumentRow, DocumentRow.id == ClauseRow.document_id)
            .where(ClauseRow.search_vector.bool_op("@@")(query))
            .order_by(func.ts_rank_cd(ClauseRow.search_vector, query).desc(), ClauseRow.id)
            .limit(pool)
        )
        return [ClauseId(found) for found in self._session.scalars(_filtered(statement, filters))]

    def nearest(
        self, vector: Vector, model: str, filters: ClauseFilter, pool: int
    ) -> Sequence[ClauseId]:
        # set_config(..., true) is SET LOCAL with the value as a bind parameter.
        self._session.execute(
            text("SELECT set_config('hnsw.ef_search', :value, true)"),
            {"value": str(HNSW_EF_SEARCH)},
        )
        self._session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
        distance = ClauseEmbeddingRow.embedding.op("<=>", return_type=Float())(
            bindparam("query_vector", vector, type_=ClauseEmbeddingRow.embedding.type)
        )
        ranked = _filtered(
            select(ClauseEmbeddingRow.clause_id, distance.label("distance"))
            .join(ClauseRow, ClauseRow.id == ClauseEmbeddingRow.clause_id)
            .join(DocumentRow, DocumentRow.id == ClauseRow.document_id)
            .where(ClauseEmbeddingRow.model == model)
            .order_by(distance)
            .limit(pool),
            filters,
        ).subquery()
        nearest: Select[UUID] = select(ranked.c.clause_id).order_by(
            ranked.c.distance, ranked.c.clause_id
        )
        return [ClauseId(found) for found in self._session.scalars(nearest)]

    def hits(
        self, clause_ids: Sequence[ClauseId], as_of: date | None
    ) -> Mapping[ClauseId, CitedClause]:
        ids = [clause_id.value for clause_id in clause_ids]
        if not ids:
            return {}
        citing = (
            select(CitationRow.clause_id, CitationRow.rule_version_id)
            .join(RuleVersionRow, RuleVersionRow.id == CitationRow.rule_version_id)
            .where(
                CitationRow.clause_id.in_(ids),
                CitationRow.verified.is_(True),
                RuleVersionRow.status.in_(PUBLISHED_STATUSES),
            )
            .distinct()
            .order_by(CitationRow.clause_id, CitationRow.rule_version_id)
        )
        if as_of is not None:
            citing = citing.where(_in_force_on(as_of))
        cited_by: dict[UUID, list[RuleVersionId]] = {}
        for clause_id, rule_version_id in self._session.execute(citing).all():
            cited_by.setdefault(clause_id, []).append(RuleVersionId(rule_version_id))
        rows = self._session.execute(
            select(ClauseRow, DocumentRow)
            .join(DocumentRow, DocumentRow.id == ClauseRow.document_id)
            .where(ClauseRow.id.in_(ids))
        ).all()
        out = _out_of_force(self._session, ids, as_of)
        return {
            ClauseId(clause.id): CitedClause(
                ClauseDetail(_to_clause(clause), _to_document(document)),
                tuple(cited_by.get(clause.id, ())),
                clause.id in out,
            )
            for clause, document in rows
        }


class SqlAlchemyRunRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def record(self, run: ExtractionRun) -> bool:
        statement = (
            insert(ExtractionRunRow)
            .values(
                id=run.run_id,
                document_id=run.document_id.value,
                stage=run.stage,
                extractor=run.extractor,
                model=run.model,
                outcome=run.outcome,
                counts=dict(run.counts),
                issues=[dict(issue) for issue in run.issues],
            )
            .on_conflict_do_nothing()
            .returning(ExtractionRunRow.id)
        )
        return self._session.execute(statement).first() is not None


class SqlAlchemyKnowledgeUnitOfWork:
    def __init__(self, session: Session, writer: OutboxWriter) -> None:
        self._documents = SqlAlchemyDocumentRepository(session)
        self._entities = SqlAlchemyEntityRepository(session)
        self._mentions = SqlAlchemyMentionRepository(session)
        self._reviews = SqlAlchemyReviewRepository(session)
        self._candidates = SqlAlchemyCandidateRepository(session)
        self._relations = SqlAlchemyRelationRepository(session)
        self._rules = SqlAlchemyRuleCatalog(session)
        self._rule_versions = SqlAlchemyRuleVersionRepository(session)
        self._citations = SqlAlchemyCitationRepository(session)
        self._review_tasks = SqlAlchemyReviewTaskRepository(session)
        self._rule_candidates = SqlAlchemyRuleCandidateRepository(session)
        self._index = SqlAlchemyClauseIndex(session)
        self._runs = SqlAlchemyRunRepository(session)
        self._events = SqlAlchemyEventSink(session, writer)
        self._audit = PostgresAuditSink(session.connection())

    @property
    def documents(self) -> SqlAlchemyDocumentRepository:
        return self._documents

    @property
    def entities(self) -> SqlAlchemyEntityRepository:
        return self._entities

    @property
    def mentions(self) -> SqlAlchemyMentionRepository:
        return self._mentions

    @property
    def reviews(self) -> SqlAlchemyReviewRepository:
        return self._reviews

    @property
    def candidates(self) -> SqlAlchemyCandidateRepository:
        return self._candidates

    @property
    def relations(self) -> SqlAlchemyRelationRepository:
        return self._relations

    @property
    def rules(self) -> SqlAlchemyRuleCatalog:
        return self._rules

    @property
    def rule_versions(self) -> SqlAlchemyRuleVersionRepository:
        return self._rule_versions

    @property
    def citations(self) -> SqlAlchemyCitationRepository:
        return self._citations

    @property
    def review_tasks(self) -> SqlAlchemyReviewTaskRepository:
        return self._review_tasks

    @property
    def rule_candidates(self) -> SqlAlchemyRuleCandidateRepository:
        return self._rule_candidates

    @property
    def index(self) -> SqlAlchemyClauseIndex:
        return self._index

    @property
    def runs(self) -> SqlAlchemyRunRepository:
        return self._runs

    @property
    def events(self) -> SqlAlchemyEventSink:
        return self._events

    @property
    def audit(self) -> PostgresAuditSink:
        """Audit entries on the unit's connection, so they commit with its changes."""
        return self._audit


class PostgresKnowledgeUnitOfWorkFactory:
    """``factory()`` opens one transaction; the block's clean exit commits it."""

    def __init__(self, engine: Engine, *, writer: OutboxWriter | None = None) -> None:
        self._engine = engine
        self._writer = writer or OutboxWriter()

    @classmethod
    def from_url(cls, database_url: str) -> Self:
        return cls(create_engine(database_url, poolclass=NullPool))

    @property
    def engine(self) -> Engine:
        return self._engine

    def __call__(self) -> AbstractContextManager[KnowledgeUnitOfWork]:
        return self._open()

    @contextmanager
    def _open(self) -> Iterator[KnowledgeUnitOfWork]:
        with Session(self._engine, expire_on_commit=False) as session, session.begin():
            yield SqlAlchemyKnowledgeUnitOfWork(session, self._writer)

    def ping(self) -> bool:
        with self._engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True

    @staticmethod
    def on_connection(
        connection: Connection, *, writer: OutboxWriter | None = None
    ) -> "ConnectionKnowledgeUnitOfWorkFactory":
        """Units of work inside the transaction of ``connection``, which its owner commits."""
        return ConnectionKnowledgeUnitOfWorkFactory(connection, writer or OutboxWriter())


class ConnectionKnowledgeUnitOfWorkFactory:
    """Units of work inside the transaction of ``connection``, begun on it when it has none
    yet. A unit neither commits nor rolls back: the owner of the connection does, so whatever
    the units wrote commits with what the owner writes (a consumer's ``processed_event`` row)."""

    def __init__(self, connection: Connection, writer: OutboxWriter) -> None:
        self._connection = connection
        self._writer = writer

    def __call__(self) -> AbstractContextManager[KnowledgeUnitOfWork]:
        return self._open()

    @contextmanager
    def _open(self) -> Iterator[KnowledgeUnitOfWork]:
        if not self._connection.in_transaction():
            # A session given a connection with no transaction would begin one of its own and
            # roll it back when it closes; begun here, the session joins it, and the owner of
            # the connection still ends it.
            self._connection.begin()
        with Session(bind=self._connection, expire_on_commit=False) as session:
            yield SqlAlchemyKnowledgeUnitOfWork(session, self._writer)
            session.flush()


def _document_values(document: StoredDocument) -> dict[str, object]:
    return {
        "id": document.document_id.value,
        "source_id": document.source_id.value,
        "sha256": document.sha256,
        "regulator": document.regulator,
        "doc_type": document.doc_type.value,
        "external_ref": document.external_ref,
        "url": document.url,
        "title": document.title,
        "language": document.language,
        "media_type": document.media_type,
        "parser_version": document.parser_version,
        "published_at": document.published_at,
        "fetched_at": document.fetched_at,
        "raw_uri": document.raw_uri,
    }


def _to_document(row: DocumentRow) -> StoredDocument:
    return StoredDocument(
        document_id=DocumentId(row.id),
        source_id=SourceId(row.source_id),
        sha256=row.sha256,
        regulator=row.regulator,
        doc_type=DocumentType(row.doc_type),
        url=row.url,
        language=row.language,
        media_type=row.media_type,
        parser_version=row.parser_version,
        fetched_at=row.fetched_at,
        external_ref=row.external_ref,
        title=row.title,
        published_at=row.published_at,
        raw_uri=row.raw_uri,
    )


def _to_clause(row: ClauseRow) -> StoredClause:
    return StoredClause(
        clause_id=ClauseId(row.id),
        document_id=DocumentId(row.document_id),
        clause_ref=row.clause_ref,
        ordinal=row.ordinal,
        text=row.text,
        text_sha256=row.text_sha256,
        page=row.page,
    )


def _any_term(text: str) -> ColumnElement[str]:
    """``plainto_tsquery`` with its ANDs turned into ORs: a clause that matches any term is a
    candidate, and ``ts_rank_cd`` ranks the ones matching more terms, closer together, higher."""
    return cast(func.replace(cast(func.plainto_tsquery(ENGLISH, text), Text), "&", "|"), TSQUERY)


def _filtered[*Row](statement: Select[*Row], filters: ClauseFilter) -> Select[*Row]:
    """The statement (already joined to ``document``) restricted to the filters; ``as_of``
    keeps documents published on or before it, so an undated document is left out."""
    if filters.regulator is not None:
        statement = statement.where(DocumentRow.regulator == filters.regulator)
    if filters.doc_types:
        statement = statement.where(
            DocumentRow.doc_type.in_(sorted(doc_type.value for doc_type in filters.doc_types))
        )
    if filters.as_of is not None:
        statement = statement.where(DocumentRow.published_at <= filters.as_of)
    return statement


def _in_force_on(as_of: date) -> ColumnElement[bool]:
    """``rule_versions.in_force`` in SQL: published or superseded, and ``as_of`` in the
    half-open effective period."""
    return and_(
        RuleVersionRow.status.in_(PUBLISHED_STATUSES),
        RuleVersionRow.effective_from <= as_of,
        or_(RuleVersionRow.effective_to.is_(None), RuleVersionRow.effective_to > as_of),
    )


def _ended_since(since: date) -> ColumnElement[bool]:
    """``rule_versions.ended_since`` in SQL: published or superseded, and an ``effective_to``
    on or after ``since``."""
    return and_(
        RuleVersionRow.status.in_(PUBLISHED_STATUSES),
        RuleVersionRow.effective_to.is_not(None),
        RuleVersionRow.effective_to >= since,
    )


def closed_version() -> ColumnElement[bool]:
    """``intake.version_closed`` in SQL, over the ``rule_version`` row of the enclosing query:
    drafted from a rule candidate that was rejected, and never published. The seed command
    skips such a version too (``seed_repository``)."""
    rejected = select(RuleCandidateRow.id).where(
        RuleCandidateRow.id == RuleVersionRow.candidate_id,
        RuleCandidateRow.status == RuleCandidateStatus.REJECTED.value,
    )
    return and_(RuleVersionRow.published_at.is_(None), rejected.exists())


def _after(rule_key: str, version: int | None) -> ColumnElement[bool]:
    """``VersionPage.follows`` in SQL: a later rule key, or a later version of ``rule_key``."""
    if version is None:
        return RuleRow.rule_key > rule_key
    return or_(
        RuleRow.rule_key > rule_key,
        and_(RuleRow.rule_key == rule_key, RuleVersionRow.version > version),
    )


def _out_of_force(session: Session, clause_ids: Sequence[UUID], as_of: date | None) -> set[UUID]:
    """``rule_versions.out_of_force`` in SQL: the clauses among ``clause_ids`` cited with a
    verified quote by a version published at some time, none of them in force on ``as_of``."""
    if as_of is None or not clause_ids:
        return set()
    found = session.scalars(
        select(CitationRow.clause_id)
        .join(RuleVersionRow, RuleVersionRow.id == CitationRow.rule_version_id)
        .where(
            CitationRow.clause_id.in_(clause_ids),
            CitationRow.verified.is_(True),
            RuleVersionRow.status.in_(CITING_STATUS_VALUES),
        )
        .group_by(CitationRow.clause_id)
        .having(func.bool_or(_in_force_on(as_of)).is_(False))
    )
    return set(found)


def _changes() -> CompoundSelect[Any]:
    """Every change the decision log records (``rulebook.domain.changes``): the published,
    superseded and withdrawn decisions, and one deadline change per extends_deadline relation to
    a version from each published one, whose id is the first 32 hex digits of the SHA-256 of
    ``<decision id>:<relation id>`` (``deadline_change_id``)."""
    decision = aliased(RuleVersionDecisionRow)
    logged = select(
        decision.id.label("change_id"),
        decision.action.label("kind"),
        decision.decided_at.label("changed_at"),
        decision.rule_version_id.label("rule_version_id"),
        decision.caused_by_rule_version_id.label("caused_by"),
        cast(null(), String).label("period_label"),
        cast(null(), Date).label("new_due_on"),
        cast(null(), Uuid).label("evidence_clause_id"),
    ).where(decision.action.in_(CHANGE_ACTION_VALUES))
    published = aliased(RuleVersionDecisionRow)
    derived = func.concat(cast(published.id, Text), ":", cast(RuleRelationRow.id, Text))
    digest = func.encode(func.sha256(func.convert_to(derived, "UTF8")), "hex")
    extended = (
        select(
            cast(func.substr(digest, 1, 32), Uuid).label("change_id"),
            literal(RuleChangeKind.DEADLINE_CHANGED.value, String).label("kind"),
            published.decided_at.label("changed_at"),
            RuleRelationRow.to_rule_version_id.label("rule_version_id"),
            published.rule_version_id.label("caused_by"),
            RelationCandidateRow.period_label.label("period_label"),
            RelationCandidateRow.new_due_on.label("new_due_on"),
            RuleRelationRow.clause_id.label("evidence_clause_id"),
        )
        .join(
            RuleRelationRow,
            and_(
                RuleRelationRow.from_rule_version_id == published.rule_version_id,
                RuleRelationRow.relation == RelationKind.EXTENDS_DEADLINE.value,
                RuleRelationRow.to_rule_version_id.is_not(None),
            ),
        )
        .outerjoin(RelationCandidateRow, RelationCandidateRow.id == RuleRelationRow.candidate_id)
        .where(published.action == DecisionAction.PUBLISHED.value)
    )
    return union_all(logged, extended)


def _versions() -> Select[RuleVersionRow, str, str, str]:
    return select(RuleVersionRow, RuleRow.rule_key, RuleRow.regulator, RuleRow.level).join(
        RuleRow, RuleRow.id == RuleVersionRow.rule_id
    )


def _to_version(
    row: RuleVersionRow, rule_key: str, regulator: str, level: str
) -> RuleVersionRecord:
    return RuleVersionRecord(
        rule_version_id=RuleVersionId(row.id),
        rule_id=RuleId(row.rule_id),
        rule_key=rule_key,
        regulator=regulator,
        level=AttributeLevel(level),
        version=row.version,
        status=RuleVersionStatus(row.status),
        title=row.title,
        summary=row.summary,
        specification=row.specification,
        obligation_template=row.obligation_template,
        recurrence=row.recurrence,
        effective_from=row.effective_from,
        effective_to=row.effective_to,
        source=row.source,
        seed_status=SeedStatus(row.seed_status),
        todo=tuple(str(item) for item in row.todo),
        published_at=row.published_at,
        high_impact=row.high_impact,
        submitted_at=row.submitted_at,
        candidate_id=row.candidate_id,
    )


def _task_values(task: ReviewTask) -> dict[str, object]:
    return {
        "id": task.task_id,
        "rule_version_id": None if task.rule_version_id is None else task.rule_version_id.value,
        "kind": task.kind.value,
        "priority": task.priority,
        "regulator": task.regulator,
        "status": task.status.value,
        "claimed_by": None if task.claimed_by is None else task.claimed_by.value,
        "claimed_at": task.claimed_at,
        "opened_at": task.opened_at,
        "decided_by": None if task.decided_by is None else task.decided_by.value,
        "decided_at": task.decided_at,
        "decision": None if task.decision is None else task.decision.value,
        "note": task.note,
        "candidate_id": task.candidate_id,
    }


def _to_task(row: Any) -> ReviewTask:
    return ReviewTask(
        task_id=row.id,
        rule_version_id=None if row.rule_version_id is None else RuleVersionId(row.rule_version_id),
        kind=ReviewTaskKind(row.kind),
        priority=row.priority,
        regulator=row.regulator,
        opened_at=row.opened_at,
        status=ReviewTaskStatus(row.status),
        claimed_by=None if row.claimed_by is None else UserId(row.claimed_by),
        claimed_at=row.claimed_at,
        decided_by=None if row.decided_by is None else UserId(row.decided_by),
        decided_at=row.decided_at,
        decision=None if row.decision is None else ReviewDecision(row.decision),
        note=row.note,
        candidate_id=row.candidate_id,
    )


def _to_queued(row: Any) -> QueuedTask:
    """A row of the queue's page: the task, its version's summary when it has one, and its
    candidate when it is a candidate task."""
    task = _to_task(row)
    candidate = None if row.RuleCandidateRow is None else _to_rule_candidate(row.RuleCandidateRow)
    summary = None if candidate is None else CandidateSummary.of(candidate)
    if row.version is None:
        return QueuedTask(
            task=task,
            rule_key=None if candidate is None else candidate.suggested_rule_key,
            version=None,
            title="" if candidate is None else candidate.title,
            version_status=None,
            high_impact=candidate is not None and candidate.high_impact_suggested,
            approvals=0,
            candidate=summary,
        )
    return QueuedTask(
        task=task,
        rule_key=row.rule_key,
        version=row.version,
        title=row.title,
        version_status=RuleVersionStatus(row.version_status),
        high_impact=row.high_impact,
        approvals=int(row.approvals or 0),
        candidate=summary,
    )


def _rule_candidate_values(candidate: RuleCandidate) -> dict[str, Any]:
    return {
        "id": candidate.candidate_id,
        "document_id": candidate.document_id.value,
        "regulator": candidate.regulator,
        "model": candidate.model,
        "prompt_version": candidate.prompt_version,
        "confidence": _score(candidate.confidence),
        "citation_count": candidate.citation_count,
        "needs_review": candidate.needs_review,
        "outcome": candidate.outcome.value,
        "payload": dict(candidate.payload),
        "status": candidate.status.value,
        "reject_reason": None if candidate.reject_reason is None else candidate.reject_reason.value,
        "rule_version_id": None
        if candidate.rule_version_id is None
        else candidate.rule_version_id.value,
        "suggested_rule_key": candidate.suggested_rule_key,
        "high_impact_suggested": candidate.high_impact_suggested,
        "event_id": candidate.event_id,
        "created_at": candidate.created_at,
        "decided_by": None if candidate.decided_by is None else candidate.decided_by.value,
        "decided_at": candidate.decided_at,
    }


def _to_rule_candidate(row: RuleCandidateRow) -> RuleCandidate:
    return RuleCandidate(
        candidate_id=row.id,
        document_id=DocumentId(row.document_id),
        regulator=row.regulator,
        model=row.model,
        prompt_version=row.prompt_version,
        confidence=float(row.confidence),
        citation_count=row.citation_count,
        needs_review=row.needs_review,
        outcome=CandidateOutcome(row.outcome),
        payload=row.payload,
        event_id=row.event_id,
        created_at=row.created_at.astimezone(UTC),
        suggested_rule_key=row.suggested_rule_key,
        high_impact_suggested=row.high_impact_suggested,
        status=RuleCandidateStatus(row.status),
        reject_reason=None if row.reject_reason is None else RuleRejectReason(row.reject_reason),
        rule_version_id=None if row.rule_version_id is None else RuleVersionId(row.rule_version_id),
        decided_by=None if row.decided_by is None else UserId(row.decided_by),
        decided_at=None if row.decided_at is None else row.decided_at.astimezone(UTC),
    )


def _after_task(key: TaskKey) -> ColumnElement[bool]:
    """``queue_position(task) > key.position`` in SQL: a later regulator, a lower priority, a
    later opening, or a later id, in that order."""
    tasks = REVIEW_TASKS.c
    return or_(
        tasks.regulator > key.regulator,
        and_(
            tasks.regulator == key.regulator,
            or_(
                tasks.priority < key.priority,
                and_(
                    tasks.priority == key.priority,
                    tuple_(tasks.opened_at, tasks.id) > tuple_(key.opened_at, key.task_id),
                ),
            ),
        ),
    )


def _review_values(item: EntityReviewItem) -> dict[str, object]:
    return {
        "id": item.review_id,
        "document_id": item.document_id.value,
        "clause_id": item.clause_id.value,
        "entity_type": item.entity_type.value,
        "mention_text": item.mention_text,
        "span_start": item.span_start,
        "span_end": item.span_end,
        "proposed_name": item.proposed_name,
        "reason": item.reason.value,
        "extractor": item.extractor,
        "status": item.status.value,
        "resolution": None if item.resolution is None else item.resolution.value,
        "resolved_entity_id": None
        if item.resolved_entity_id is None
        else item.resolved_entity_id.value,
        "reject_reason": None if item.reject_reason is None else item.reject_reason.value,
        "decided_by": item.decided_by,
        "decided_at": item.decided_at,
        "note": item.note,
    }


def _to_review(row: EntityReviewRow) -> EntityReviewItem:
    return EntityReviewItem(
        review_id=row.id,
        document_id=DocumentId(row.document_id),
        clause_id=ClauseId(row.clause_id),
        entity_type=EntityType(row.entity_type),
        mention_text=row.mention_text,
        span_start=row.span_start,
        span_end=row.span_end,
        proposed_name=row.proposed_name,
        reason=ReviewReason(row.reason),
        extractor=row.extractor,
        status=ReviewStatus(row.status),
        resolution=None if row.resolution is None else Resolution(row.resolution),
        resolved_entity_id=None
        if row.resolved_entity_id is None
        else CanonicalEntityId(row.resolved_entity_id),
        reject_reason=None if row.reject_reason is None else EntityRejectReason(row.reject_reason),
        decided_by=row.decided_by,
        decided_at=row.decided_at,
        note=row.note,
    )


def _score(value: float) -> Decimal:
    return Decimal(str(round(value, 3)))


def _candidate_values(candidate: RelationCandidate) -> dict[str, Any]:
    return {
        "id": candidate.candidate_id,
        "document_id": candidate.document_id.value,
        "relation": candidate.relation.value,
        "target_type": candidate.target_type.value,
        "target_name": candidate.target_name,
        "target_clause_id": candidate.target_clause_id.value,
        "target_span_start": candidate.target_span_start,
        "target_span_end": candidate.target_span_end,
        "target_entity_id": None
        if candidate.target_entity_id is None
        else candidate.target_entity_id.value,
        "target_rule_key": candidate.target_rule_key,
        "target_rule_id": candidate.target_rule_id,
        "evidence_clause_id": candidate.evidence_clause_id.value,
        "evidence_quote": candidate.evidence_quote,
        "quote_score": _score(candidate.quote_score),
        "period_label": candidate.period_label,
        "new_due_on": candidate.new_due_on,
        "method": candidate.method,
        "prompt_version": candidate.prompt_version,
        "model": candidate.model,
        "confidence": _score(candidate.confidence),
        "issues": [{"code": i.code, "detail": i.detail} for i in candidate.issues],
        "needs_review": candidate.needs_review,
        "status": candidate.status.value,
        "reject_reason": None if candidate.reject_reason is None else candidate.reject_reason.value,
        "decided_by": candidate.decided_by,
        "decided_at": candidate.decided_at,
        "note": candidate.note,
    }


def _to_candidate(row: RelationCandidateRow) -> RelationCandidate:
    issues = tuple(
        CandidateIssue(str(issue["code"]), str(issue["detail"]))
        for issue in row.issues
        if isinstance(issue, dict)
    )
    return RelationCandidate(
        candidate_id=row.id,
        document_id=DocumentId(row.document_id),
        relation=RelationKind(row.relation),
        target_type=EntityType(row.target_type),
        target_name=row.target_name,
        target_clause_id=ClauseId(row.target_clause_id),
        target_span_start=row.target_span_start,
        target_span_end=row.target_span_end,
        evidence_clause_id=ClauseId(row.evidence_clause_id),
        evidence_quote=row.evidence_quote,
        quote_score=float(row.quote_score),
        prompt_version=row.prompt_version,
        confidence=float(row.confidence),
        needs_review=row.needs_review,
        model=row.model,
        method=row.method,
        target_entity_id=None
        if row.target_entity_id is None
        else CanonicalEntityId(row.target_entity_id),
        target_rule_key=row.target_rule_key,
        target_rule_id=row.target_rule_id,
        period_label=row.period_label,
        new_due_on=row.new_due_on,
        issues=issues,
        status=CandidateStatus(row.status),
        reject_reason=None
        if row.reject_reason is None
        else CandidateRejectReason(row.reject_reason),
        decided_by=row.decided_by,
        decided_at=row.decided_at,
        note=row.note,
    )
