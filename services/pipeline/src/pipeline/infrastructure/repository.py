"""The Postgres unit of work: one transaction with the source, document, crawl-run, task,
classification and extraction repositories on it, the outbox writer as the event sink and the audit
writer as the audit sink, so a stored document and the outbox row of its document.discovered commit
or roll back together, and so do a stored extraction and its rule.candidate.created, and an admin's
change and its ``audit.event`` row. There is no tenant setting: the pipeline's data is regulatory,
the same for every tenant, and its audit entries have no tenant.

``PostgresUnitOfWorkFactory.on_connection(connection)`` makes units inside a transaction someone
else owns, such as a consumer's inbox transaction (``py_common.outbox.sync``), so a handler's
writes, their outbox rows and the ``processed_event`` row commit together.
"""

from collections.abc import Collection, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime
from typing import Final, Self

from sqlalchemy import (
    ColumnElement,
    Connection,
    Engine,
    and_,
    case,
    create_engine,
    func,
    or_,
    select,
    text,
    tuple_,
    update,
)
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from domain_kernel.documents import DocumentType
from domain_kernel.ids import CandidateId, DocumentId
from pipeline.domain.classification import Classification, Relevance, TypeConfidence
from pipeline.domain.crawl import CrawlCounts, CrawlRun, CrawlRunId, CrawlStatus
from pipeline.domain.events import DocumentEvent
from pipeline.domain.extraction import ExtractionOutcome, RuleExtraction
from pipeline.domain.issues import Issue
from pipeline.domain.raw_documents import DocumentStatus, RawDocumentRecord
from pipeline.domain.repository import DocumentKey, TaskKey, UnitOfWork, UnitOfWorkFactory
from pipeline.domain.sources import Source
from pipeline.domain.tasks import PipelineTask, TaskId, TaskKind, TaskStatus
from pipeline.infrastructure.models import (
    CrawlRunRow,
    DocumentClassificationRow,
    PipelineTaskRow,
    RawDocumentRow,
    RuleExtractionRow,
    SourceRow,
)
from py_common.audit.writer import PostgresAuditSink
from py_common.outbox import OutboxWriter

URL_CHUNK: Final = 500
"""How many URLs one ``known_urls`` query asks about."""


class SqlAlchemySourceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, key: str, *, for_update: bool = False) -> Source | None:
        if for_update:
            statement = (
                select(SourceRow)
                .where(SourceRow.key == key)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            locked = self._session.scalars(statement).first()
            return None if locked is None else _to_source(locked)
        row = self._session.get(SourceRow, key, populate_existing=True)
        return None if row is None else _to_source(row)

    def add(self, source: Source) -> bool:
        statement = (
            insert(SourceRow)
            .values(**_source_values(source))
            .on_conflict_do_nothing(index_elements=["key"])
            .returning(SourceRow.key)
        )
        return self._session.execute(statement).first() is not None

    def save(self, source: Source) -> None:
        values = _source_values(source)
        del values["key"], values["created_at"]
        self._session.execute(update(SourceRow).where(SourceRow.key == source.key).values(values))

    def list(self) -> Sequence[Source]:
        rows = self._session.scalars(select(SourceRow).order_by(SourceRow.key)).all()
        return [_to_source(row) for row in rows]


def _source_values(source: Source) -> dict[str, object]:
    return {
        "key": source.key,
        "adapter_type": source.adapter_type,
        "parameters": dict(source.parameters),
        "cadence": source.cadence,
        "enabled": source.enabled,
        "paused": source.paused,
        "last_fetch_at": source.last_fetch_at,
        "watermark": None if source.watermark is None else dict(source.watermark),
        "last_error": source.last_error,
        "created_at": source.created_at,
        "updated_at": source.updated_at,
        "name": source.name,
    }


def _to_source(row: SourceRow) -> Source:
    return Source(
        key=row.key,
        adapter_type=row.adapter_type,
        parameters=row.parameters,
        cadence=row.cadence,
        created_at=row.created_at.astimezone(UTC),
        updated_at=row.updated_at.astimezone(UTC),
        enabled=row.enabled,
        paused=row.paused,
        last_fetch_at=_utc(row.last_fetch_at),
        watermark=row.watermark,
        last_error=row.last_error,
        name=row.name,
    )


class SqlAlchemyRawDocumentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, document_id: DocumentId) -> RawDocumentRecord | None:
        row = self._session.get(RawDocumentRow, document_id.value, populate_existing=True)
        return None if row is None else _to_record(row)

    def add(self, record: RawDocumentRecord) -> bool:
        # No conflict target: the id and the digest are both unique, and a row with either is
        # the same bytes, already stored.
        statement = (
            insert(RawDocumentRow)
            .values(
                id=record.document_id.value,
                source_key=record.source_key,
                source_url=record.source_url,
                external_ref=record.external_ref,
                fetched_at=record.fetched_at,
                published_on=record.published_on,
                content_type=record.content_type,
                size=record.size,
                sha256=record.sha256,
                storage_key=record.storage_key,
                title=record.title,
                status=record.status.value,
                parser_version=record.parser_version,
                doc_type=None if record.doc_type is None else record.doc_type.value,
                transcript_key=record.transcript_key or None,
            )
            .on_conflict_do_nothing()
            .returning(RawDocumentRow.id)
        )
        return self._session.execute(statement).first() is not None

    def set_status(self, document_id: DocumentId, status: DocumentStatus) -> bool:
        statement = (
            update(RawDocumentRow)
            .where(RawDocumentRow.id == document_id.value)
            .values(status=status.value)
            .returning(RawDocumentRow.id)
        )
        return self._session.execute(statement).first() is not None

    def record_parse(
        self, document_id: DocumentId, parser_version: str, *, transcript_key: str = ""
    ) -> bool:
        unparsed = RawDocumentRow.status.in_(
            [status.value for status in DocumentStatus if status.unparsed]
        )
        values: dict[str, object] = {
            "status": case((unparsed, DocumentStatus.PARSED.value), else_=RawDocumentRow.status),
            "parser_version": parser_version,
        }
        changed = or_(unparsed, RawDocumentRow.parser_version != parser_version)
        if transcript_key:
            values["transcript_key"] = func.coalesce(RawDocumentRow.transcript_key, transcript_key)
            changed = or_(changed, RawDocumentRow.transcript_key.is_(None))
        statement = (
            update(RawDocumentRow)
            .where(RawDocumentRow.id == document_id.value, changed)
            .values(values)
            .returning(RawDocumentRow.id)
        )
        return self._session.execute(statement).first() is not None

    def recent(self, source_key: str, *, limit: int) -> Sequence[RawDocumentRecord]:
        statement = (
            select(RawDocumentRow)
            .where(RawDocumentRow.source_key == source_key)
            .order_by(
                RawDocumentRow.published_on.desc().nulls_last(),
                RawDocumentRow.fetched_at.desc(),
                RawDocumentRow.id,
            )
            .limit(limit)
        )
        return [_to_record(row) for row in self._session.scalars(statement).all()]

    def page(
        self, source_key: str, *, after: DocumentKey | None, limit: int
    ) -> Sequence[RawDocumentRecord]:
        statement = select(RawDocumentRow).where(RawDocumentRow.source_key == source_key)
        if after is not None:
            statement = statement.where(_after(after))
        statement = statement.order_by(
            RawDocumentRow.published_on.desc().nulls_last(),
            RawDocumentRow.fetched_at.desc(),
            RawDocumentRow.id.desc(),
        ).limit(limit)
        return [_to_record(row) for row in self._session.scalars(statement).all()]

    def find_by_url(self, source_key: str, url: str) -> RawDocumentRecord | None:
        statement = (
            select(RawDocumentRow)
            .where(RawDocumentRow.source_key == source_key, RawDocumentRow.source_url == url)
            .order_by(RawDocumentRow.fetched_at.desc(), RawDocumentRow.id.desc())
            .limit(1)
        )
        row = self._session.scalars(statement).first()
        return None if row is None else _to_record(row)

    def known_urls(self, source_key: str, urls: Collection[str]) -> frozenset[str]:
        wanted = sorted(set(urls))
        found: set[str] = set()
        for start in range(0, len(wanted), URL_CHUNK):
            chunk = wanted[start : start + URL_CHUNK]
            statement = (
                select(RawDocumentRow.source_url)
                .where(
                    RawDocumentRow.source_key == source_key,
                    RawDocumentRow.source_url.in_(chunk),
                )
                .distinct()
            )
            found.update(self._session.scalars(statement).all())
        return frozenset(found)

    def counts(self) -> Mapping[str, int]:
        statement = select(RawDocumentRow.source_key, func.count()).group_by(
            RawDocumentRow.source_key
        )
        return {key: int(count) for key, count in self._session.execute(statement).all()}

    def fetched_since(self, moment: datetime) -> Sequence[RawDocumentRecord]:
        statement = (
            select(RawDocumentRow)
            .where(RawDocumentRow.fetched_at >= moment)
            .order_by(RawDocumentRow.fetched_at, RawDocumentRow.id)
        )
        return [_to_record(row) for row in self._session.scalars(statement).all()]


def _after(key: DocumentKey) -> ColumnElement[bool]:
    """The rows after ``key`` in the page order: newest publication first with the undated
    last, then the latest fetch, then the highest id."""
    later_fetch = tuple_(RawDocumentRow.fetched_at, RawDocumentRow.id) < tuple_(
        key.fetched_at, key.document_id.value
    )
    if key.published_on is None:
        return and_(RawDocumentRow.published_on.is_(None), later_fetch)
    return or_(
        RawDocumentRow.published_on < key.published_on,
        and_(RawDocumentRow.published_on == key.published_on, later_fetch),
        RawDocumentRow.published_on.is_(None),
    )


def _to_record(row: RawDocumentRow) -> RawDocumentRecord:
    return RawDocumentRecord(
        document_id=DocumentId(row.id),
        source_key=row.source_key,
        source_url=row.source_url,
        fetched_at=row.fetched_at.astimezone(UTC),
        content_type=row.content_type,
        size=row.size,
        sha256=row.sha256,
        storage_key=row.storage_key,
        external_ref=row.external_ref,
        title=row.title,
        published_on=row.published_on,
        status=DocumentStatus(row.status),
        parser_version=row.parser_version,
        doc_type=None if row.doc_type is None else DocumentType(row.doc_type),
        transcript_key=row.transcript_key or "",
    )


class SqlAlchemyCrawlRunRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, run: CrawlRun) -> None:
        self._session.add(_to_run_row(run))
        self._session.flush()

    def start(self, run: CrawlRun) -> bool:
        statement = (
            insert(CrawlRunRow)
            .values(**_run_values(run))
            .on_conflict_do_nothing(index_elements=["id"])
            .returning(CrawlRunRow.id)
        )
        return self._session.execute(statement).first() is not None

    def get(self, run_id: CrawlRunId) -> CrawlRun | None:
        row = self._session.get(CrawlRunRow, run_id.value, populate_existing=True)
        return None if row is None else _to_run(row)

    def save(self, run: CrawlRun) -> None:
        self._session.merge(_to_run_row(run))
        self._session.flush()

    def latest(self, source_key: str) -> CrawlRun | None:
        statement = (
            select(CrawlRunRow)
            .where(CrawlRunRow.source_key == source_key)
            .order_by(CrawlRunRow.started_at.desc(), CrawlRunRow.id.desc())
            .limit(1)
        )
        row = self._session.scalars(statement).first()
        return None if row is None else _to_run(row)

    def latest_by_source(self) -> Mapping[str, CrawlRun]:
        statement = (
            select(CrawlRunRow)
            .ext(distinct_on(CrawlRunRow.source_key))
            .order_by(CrawlRunRow.source_key, CrawlRunRow.started_at.desc(), CrawlRunRow.id.desc())
        )
        return {row.source_key: _to_run(row) for row in self._session.scalars(statement).all()}

    def running(self, source_key: str) -> Sequence[CrawlRun]:
        statement = (
            select(CrawlRunRow)
            .where(
                CrawlRunRow.source_key == source_key,
                CrawlRunRow.status == CrawlStatus.RUNNING.value,
            )
            .order_by(CrawlRunRow.started_at, CrawlRunRow.id)
        )
        return [_to_run(row) for row in self._session.scalars(statement).all()]

    def started_since(self, moment: datetime) -> Sequence[CrawlRun]:
        statement = (
            select(CrawlRunRow)
            .where(CrawlRunRow.started_at >= moment)
            .order_by(CrawlRunRow.started_at, CrawlRunRow.id)
        )
        return [_to_run(row) for row in self._session.scalars(statement).all()]


def _run_values(run: CrawlRun) -> dict[str, object]:
    return {
        "id": run.id.value,
        "source_key": run.source_key,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "status": run.status.value,
        "listed": run.counts.listed,
        "stored": run.counts.stored,
        "duplicates": run.counts.duplicates,
        "failed": run.counts.failed,
        "error": run.error,
    }


def _to_run_row(run: CrawlRun) -> CrawlRunRow:
    return CrawlRunRow(**_run_values(run))


def _to_run(row: CrawlRunRow) -> CrawlRun:
    return CrawlRun(
        id=CrawlRunId(row.id),
        source_key=row.source_key,
        started_at=row.started_at.astimezone(UTC),
        status=CrawlStatus(row.status),
        finished_at=_utc(row.finished_at),
        counts=CrawlCounts(
            listed=row.listed, stored=row.stored, duplicates=row.duplicates, failed=row.failed
        ),
        error=row.error,
    )


def _utc(moment: datetime | None) -> datetime | None:
    return None if moment is None else moment.astimezone(UTC)


class SqlAlchemyTaskRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def open(self, task: PipelineTask) -> PipelineTask:
        statement = (
            insert(PipelineTaskRow)
            .values(**_task_values(task))
            .on_conflict_do_nothing(
                index_elements=["document_id", "kind"],
                index_where=PipelineTaskRow.status == TaskStatus.OPEN.value,
            )
            .returning(PipelineTaskRow.id)
        )
        if self._session.execute(statement).first() is not None:
            return task
        found = self.open_for(task.document_id, task.kind)
        if found is None:
            raise RuntimeError(
                f"document {task.document_id} had an open {task.kind.value} task, then none"
            )
        return found

    def get(self, task_id: TaskId, *, for_update: bool = False) -> PipelineTask | None:
        statement = select(PipelineTaskRow).where(PipelineTaskRow.id == task_id.value)
        if for_update:
            statement = statement.with_for_update()
        row = self._session.scalars(statement.execution_options(populate_existing=True)).first()
        return None if row is None else _to_task(row)

    def save(self, task: PipelineTask) -> None:
        values = _task_values(task)
        for fixed in ("id", "kind", "document_id", "source_key", "opened_at", "reason"):
            del values[fixed]
        self._session.execute(
            update(PipelineTaskRow).where(PipelineTaskRow.id == task.id.value).values(values)
        )

    def open_for(self, document_id: DocumentId, kind: TaskKind) -> PipelineTask | None:
        statement = select(PipelineTaskRow).where(
            PipelineTaskRow.document_id == document_id.value,
            PipelineTaskRow.kind == kind.value,
            PipelineTaskRow.status == TaskStatus.OPEN.value,
        )
        row = self._session.scalars(statement).first()
        return None if row is None else _to_task(row)

    def page(
        self,
        *,
        status: TaskStatus | None,
        kind: TaskKind | None,
        after: TaskKey | None,
        limit: int,
    ) -> Sequence[PipelineTask]:
        statement = select(PipelineTaskRow)
        if status is not None:
            statement = statement.where(PipelineTaskRow.status == status.value)
        if kind is not None:
            statement = statement.where(PipelineTaskRow.kind == kind.value)
        if after is not None:
            statement = statement.where(
                tuple_(PipelineTaskRow.opened_at, PipelineTaskRow.id)
                > tuple_(after.opened_at, after.task_id.value)
            )
        statement = statement.order_by(PipelineTaskRow.opened_at, PipelineTaskRow.id).limit(limit)
        return [_to_task(row) for row in self._session.scalars(statement).all()]

    def open_counts(self) -> Mapping[TaskKind, int]:
        statement = (
            select(PipelineTaskRow.kind, func.count())
            .where(PipelineTaskRow.status == TaskStatus.OPEN.value)
            .group_by(PipelineTaskRow.kind)
        )
        return {TaskKind(kind): int(count) for kind, count in self._session.execute(statement)}


def _task_values(task: PipelineTask) -> dict[str, object]:
    return {
        "id": task.id.value,
        "kind": task.kind.value,
        "document_id": task.document_id.value,
        "source_key": task.source_key,
        "status": task.status.value,
        "opened_at": task.opened_at,
        "reason": task.reason,
        "claimed_by": task.claimed_by,
        "resolved_by": task.resolved_by,
        "resolved_at": task.resolved_at,
        "resolution": None if task.resolution is None else dict(task.resolution),
        "note": task.note,
    }


def _to_task(row: PipelineTaskRow) -> PipelineTask:
    return PipelineTask(
        id=TaskId(row.id),
        kind=TaskKind(row.kind),
        document_id=DocumentId(row.document_id),
        source_key=row.source_key,
        opened_at=row.opened_at.astimezone(UTC),
        status=TaskStatus(row.status),
        reason=row.reason,
        claimed_by=row.claimed_by,
        resolved_by=row.resolved_by,
        resolved_at=_utc(row.resolved_at),
        resolution=row.resolution,
        note=row.note,
    )


class SqlAlchemyClassificationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, document_id: DocumentId) -> Classification | None:
        row = self._session.get(
            DocumentClassificationRow, document_id.value, populate_existing=True
        )
        return None if row is None else _to_classification(row)

    def add(self, classification: Classification) -> bool:
        statement = (
            insert(DocumentClassificationRow)
            .values(**_classification_values(classification))
            .on_conflict_do_nothing(index_elements=["document_id"])
            .returning(DocumentClassificationRow.document_id)
        )
        return self._session.execute(statement).first() is not None

    def save(self, classification: Classification) -> None:
        values = _classification_values(classification)
        del values["document_id"]
        self._session.execute(
            update(DocumentClassificationRow)
            .where(DocumentClassificationRow.document_id == classification.document_id.value)
            .values(values)
        )


def _classification_values(classification: Classification) -> dict[str, object]:
    return {
        "document_id": classification.document_id.value,
        "doc_type": classification.doc_type.value,
        "relevance": classification.relevance.value,
        "confidence": classification.confidence.value,
        "reasons": list(classification.reasons),
        "classifier": classification.classifier,
        "decided_by": classification.decided_by,
        "task_id": None if classification.task_id is None else classification.task_id.value,
        "classified_at": classification.classified_at,
    }


def _to_classification(row: DocumentClassificationRow) -> Classification:
    return Classification(
        document_id=DocumentId(row.document_id),
        doc_type=DocumentType(row.doc_type),
        relevance=Relevance(row.relevance),
        confidence=TypeConfidence(row.confidence),
        reasons=tuple(row.reasons),
        classified_at=row.classified_at.astimezone(UTC),
        classifier=row.classifier,
        decided_by=row.decided_by,
        task_id=None if row.task_id is None else TaskId(row.task_id),
    )


class SqlAlchemyExtractionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, document_id: DocumentId, prompt_version: str) -> RuleExtraction | None:
        row = self._session.get(
            RuleExtractionRow, (document_id.value, prompt_version), populate_existing=True
        )
        return None if row is None else _to_extraction(row)

    def add(self, extraction: RuleExtraction) -> bool:
        statement = (
            insert(RuleExtractionRow)
            .values(**_extraction_values(extraction))
            .on_conflict_do_nothing(index_elements=["document_id", "prompt_version"])
            .returning(RuleExtractionRow.document_id)
        )
        return self._session.execute(statement).first() is not None


def _extraction_values(extraction: RuleExtraction) -> dict[str, object]:
    return {
        "document_id": extraction.document_id.value,
        "prompt_version": extraction.prompt_version,
        "candidate_id": extraction.candidate_id.value,
        "outcome": extraction.outcome.value,
        "model": extraction.model,
        "attempts": extraction.attempts,
        "source_key": extraction.source_key,
        "doc_type": extraction.doc_type.value,
        "regulator": extraction.regulator,
        "fields": None if extraction.fields is None else _json(extraction.fields),
        "issues": [
            {"code": issue.code, "detail": issue.detail, "clause_ref": issue.clause_ref}
            for issue in extraction.issues
        ],
        "citation_count": extraction.citation_count,
        "confidence": extraction.confidence,
        "needs_review": extraction.needs_review,
        "answer": extraction.answer,
        "ontology_version": extraction.ontology_version,
        "extracted_at": extraction.extracted_at,
    }


def _json(value: object) -> object:
    """Mappings and sequences as the dicts and lists JSONB takes."""
    if isinstance(value, Mapping):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json(item) for item in value]
    return value


def _to_extraction(row: RuleExtractionRow) -> RuleExtraction:
    return RuleExtraction(
        document_id=DocumentId(row.document_id),
        prompt_version=row.prompt_version,
        candidate_id=CandidateId(row.candidate_id),
        outcome=ExtractionOutcome(row.outcome),
        model=row.model,
        attempts=row.attempts,
        source_key=row.source_key,
        doc_type=DocumentType(row.doc_type),
        regulator=row.regulator,
        issues=tuple(
            Issue(str(item["code"]), str(item["detail"]), _optional_text(item.get("clause_ref")))
            for item in row.issues
        ),
        citation_count=row.citation_count,
        confidence=row.confidence,
        needs_review=row.needs_review,
        answer=row.answer,
        ontology_version=row.ontology_version,
        extracted_at=row.extracted_at.astimezone(UTC),
        fields=row.fields,
    )


def _optional_text(value: object) -> str | None:
    return None if value is None else str(value)


class OutboxSink:
    """Writes each event into ``outbox_event`` on the unit of work's connection, keyed by its
    source, so the event commits or rolls back with the change it describes."""

    def __init__(self, connection: Connection, writer: OutboxWriter) -> None:
        self._connection = connection
        self._writer = writer

    def publish(self, event: DocumentEvent) -> None:
        self._writer.write(self._connection, event, partition_key=event.partition_key)


class SqlAlchemyUnitOfWork:
    def __init__(self, session: Session, writer: OutboxWriter) -> None:
        self.sources = SqlAlchemySourceRepository(session)
        self.documents = SqlAlchemyRawDocumentRepository(session)
        self.crawl_runs = SqlAlchemyCrawlRunRepository(session)
        self.tasks = SqlAlchemyTaskRepository(session)
        self.classifications = SqlAlchemyClassificationRepository(session)
        self.extractions = SqlAlchemyExtractionRepository(session)
        self.events = OutboxSink(session.connection(), writer)
        self.audit = PostgresAuditSink(session.connection())


class ConnectionUnitOfWorkFactory:
    """Units of work inside the transaction of ``connection``, begun on it when it has none yet.
    A unit neither commits nor rolls back: the owner of the connection does."""

    def __init__(self, connection: Connection, writer: OutboxWriter) -> None:
        self._connection = connection
        self._writer = writer

    def __call__(self) -> AbstractContextManager[UnitOfWork]:
        return self._open()

    @contextmanager
    def _open(self) -> Iterator[UnitOfWork]:
        if not self._connection.in_transaction():
            # Begun here, the session joins the transaction and the connection's owner ends it.
            self._connection.begin()
        with Session(bind=self._connection, expire_on_commit=False) as session:
            yield SqlAlchemyUnitOfWork(session, self._writer)
            session.flush()


class PostgresUnitOfWorkFactory:
    """``factory()`` opens one transaction; ``PostgresUnitOfWorkFactory.on_connection(connection)``
    makes units inside a transaction the caller owns."""

    def __init__(self, engine: Engine, *, writer: OutboxWriter | None = None) -> None:
        self._engine = engine
        self._writer = writer or OutboxWriter()

    @classmethod
    def from_url(cls, database_url: str) -> Self:
        return cls(create_engine(database_url, poolclass=NullPool))

    @property
    def engine(self) -> Engine:
        return self._engine

    @staticmethod
    def on_connection(
        connection: Connection, *, writer: OutboxWriter | None = None
    ) -> UnitOfWorkFactory:
        return ConnectionUnitOfWorkFactory(connection, writer or OutboxWriter())

    def __call__(self) -> AbstractContextManager[UnitOfWork]:
        return self._open()

    @contextmanager
    def _open(self) -> Iterator[UnitOfWork]:
        with Session(self._engine, expire_on_commit=False) as session, session.begin():
            yield SqlAlchemyUnitOfWork(session, self._writer)

    def ping(self) -> bool:
        with self._engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
