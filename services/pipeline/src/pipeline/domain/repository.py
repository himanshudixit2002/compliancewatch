"""What the application layer needs from the pipeline's store, as protocols the infrastructure
implements (Postgres in ``infrastructure.repository``, memory in ``infrastructure.memory``).

The store holds regulatory data, the same for every tenant: a unit of work opens one transaction
with no tenant setting. Its rows, the outbox rows of its events and its audit entries (of no
tenant, in ``audit.event``) commit or roll back together.
"""

from collections.abc import Collection, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from domain_kernel.audit import AuditSink
from domain_kernel.ids import DocumentId
from pipeline.domain.crawl import CrawlRun, CrawlRunId
from pipeline.domain.events import DocumentEvent
from pipeline.domain.raw_documents import DocumentStatus, RawDocumentRecord
from pipeline.domain.sources import Source


@dataclass(frozen=True, slots=True)
class DocumentKey:
    """Where a page of a source's documents starts: after the document with these values. The
    order is the newest publication first (undated last), then the latest fetch, then the id
    from the highest."""

    published_on: date | None
    fetched_at: datetime
    document_id: DocumentId

    @classmethod
    def of(cls, record: RawDocumentRecord) -> "DocumentKey":
        return cls(record.published_on, record.fetched_at, record.document_id)


class SourceRepository(Protocol):
    def get(self, key: str, *, for_update: bool = False) -> Source | None:
        """The source; ``for_update`` holds it until the unit ends, so two units that start a
        crawl of one source run one after the other."""
        ...

    def add(self, source: Source) -> bool:
        """Insert the source unless one with its key exists, which is left as it is; True when
        it was inserted."""
        ...

    def save(self, source: Source) -> None:
        """Write every column of an existing source."""
        ...

    def list(self) -> Sequence[Source]:
        """Every source, by key."""
        ...


class RawDocumentRepository(Protocol):
    def get(self, document_id: DocumentId) -> RawDocumentRecord | None: ...

    def add(self, record: RawDocumentRecord) -> bool:
        """Insert the record unless one with its id (its bytes) exists, which is left as it is;
        True when it was inserted. Its source must be stored."""
        ...

    def set_status(self, document_id: DocumentId, status: DocumentStatus) -> bool:
        """Move a stored document to ``status``; False when there is no such document."""
        ...

    def recent(self, source_key: str, *, limit: int) -> Sequence[RawDocumentRecord]:
        """The source's documents, newest publication first (undated ones last), then the
        latest fetch first, at most ``limit``."""
        ...

    def page(
        self, source_key: str, *, after: DocumentKey | None, limit: int
    ) -> Sequence[RawDocumentRecord]:
        """The source's documents in ``DocumentKey`` order, starting after ``after``."""
        ...

    def find_by_url(self, source_key: str, url: str) -> RawDocumentRecord | None:
        """The document the source listed at ``url`` that was fetched last, or None."""
        ...

    def known_urls(self, source_key: str, urls: Collection[str]) -> frozenset[str]:
        """Those of ``urls`` a stored document of the source was listed at."""
        ...

    def counts(self) -> Mapping[str, int]:
        """How many documents each source has; a source without any is absent."""
        ...

    def fetched_since(self, moment: datetime) -> Sequence[RawDocumentRecord]:
        """Every document first fetched at or after ``moment``, oldest fetch first."""
        ...


class CrawlRunRepository(Protocol):
    def add(self, run: CrawlRun) -> None: ...

    def start(self, run: CrawlRun) -> bool:
        """Insert the run unless one with its id exists; True when it was inserted."""
        ...

    def get(self, run_id: CrawlRunId) -> CrawlRun | None: ...

    def save(self, run: CrawlRun) -> None:
        """Write the status, end, counts and error of an existing run."""
        ...

    def latest(self, source_key: str) -> CrawlRun | None:
        """The source's most recently started run."""
        ...

    def latest_by_source(self) -> Mapping[str, CrawlRun]:
        """Each source's most recently started run."""
        ...

    def running(self, source_key: str) -> Sequence[CrawlRun]:
        """The source's runs that are still running, oldest first."""
        ...

    def started_since(self, moment: datetime) -> Sequence[CrawlRun]:
        """Every run started at or after ``moment``, oldest first."""
        ...


class EventSink(Protocol):
    """Where events go inside the transaction: the outbox, keyed by the event's source."""

    def publish(self, event: DocumentEvent) -> None: ...


class UnitOfWork(Protocol):
    @property
    def sources(self) -> SourceRepository: ...

    @property
    def documents(self) -> RawDocumentRepository: ...

    @property
    def crawl_runs(self) -> CrawlRunRepository: ...

    @property
    def events(self) -> EventSink: ...

    @property
    def audit(self) -> AuditSink: ...


class UnitOfWorkFactory(Protocol):
    """``factory()`` opens one transaction; it commits when the block ends cleanly."""

    def __call__(self) -> AbstractContextManager[UnitOfWork]: ...
