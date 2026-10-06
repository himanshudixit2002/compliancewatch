"""The Postgres unit of work: one transaction with the source, document and crawl-run
repositories on it, the outbox writer as the event sink and the audit writer as the audit sink,
so a stored document and the outbox row of its document.discovered commit or roll back together,
and so does an admin's change and its ``audit.event`` row. There is no tenant setting: the
pipeline's data is regulatory, the same for every tenant, and its audit entries have no tenant.

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
    create_engine,
    func,
    or_,
    select,
    text,
    tuple_,
    update,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from domain_kernel.ids import DocumentId
from pipeline.domain.crawl import CrawlCounts, CrawlRun, CrawlRunId, CrawlStatus
from pipeline.domain.events import DocumentEvent
from pipeline.domain.raw_documents import DocumentStatus, RawDocumentRecord
from pipeline.domain.repository import DocumentKey, UnitOfWork, UnitOfWorkFactory
from pipeline.domain.sources import Source
from pipeline.infrastructure.models import CrawlRunRow, RawDocumentRow, SourceRow
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
            .distinct(CrawlRunRow.source_key)
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
