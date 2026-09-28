"""The Postgres unit of work for regulator documents and the knowledge tables.

Inserts use ``ON CONFLICT DO NOTHING``: documents, clauses, mentions, review items, candidates,
relations and runs are keyed by ids every writer derives the same way, so a repeated insert is a
no-op rather than an error. Decisions lock the rows they change (``SELECT ... FOR UPDATE``).
"""

from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from decimal import Decimal
from typing import Any, Self
from uuid import UUID

from sqlalchemy import Engine, and_, create_engine, func, select, text, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from domain_kernel.documents import DocumentType
from domain_kernel.ids import CanonicalEntityId, ClauseId, DocumentId, RuleVersionId, SourceId
from domain_kernel.knowledge import EntityRef, EntityType, RelationKind, RuleRelation
from domain_kernel.status import RuleVersionStatus
from rulebook.domain.alignment import ReviewReason
from rulebook.domain.documents import StoredClause, StoredDocument
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
    ReviewStatus,
)
from rulebook.domain.runs import ExtractionRun, RuleSummary
from rulebook.infrastructure.models import (
    CanonicalEntityRow,
    ClauseEntityRow,
    ClauseRow,
    DocumentRow,
    EntityReviewRow,
    ExtractionRunRow,
    RelationCandidateRow,
    RuleRelationRow,
    RuleRow,
    RuleVersionRow,
)

EXAMPLES_PER_GROUP = 5


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


class SqlAlchemyRuleCatalog:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_rules(self) -> tuple[RuleSummary, ...]:
        latest = (
            select(RuleVersionRow.rule_id, func.max(RuleVersionRow.version).label("version"))
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
    def __init__(self, session: Session) -> None:
        self._documents = SqlAlchemyDocumentRepository(session)
        self._entities = SqlAlchemyEntityRepository(session)
        self._mentions = SqlAlchemyMentionRepository(session)
        self._reviews = SqlAlchemyReviewRepository(session)
        self._candidates = SqlAlchemyCandidateRepository(session)
        self._relations = SqlAlchemyRelationRepository(session)
        self._rules = SqlAlchemyRuleCatalog(session)
        self._runs = SqlAlchemyRunRepository(session)

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
    def runs(self) -> SqlAlchemyRunRepository:
        return self._runs


class PostgresKnowledgeUnitOfWorkFactory:
    """``factory()`` opens one transaction; the block's clean exit commits it."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

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
            yield SqlAlchemyKnowledgeUnitOfWork(session)

    def ping(self) -> bool:
        with self._engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True


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
