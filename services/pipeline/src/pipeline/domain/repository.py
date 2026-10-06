"""What the application layer needs from the pipeline's store, as protocols the infrastructure
implements (Postgres in ``infrastructure.repository``, memory in ``infrastructure.memory``).

The store holds regulatory data, the same for every tenant: a unit of work opens one transaction
with no tenant setting. Its rows and the outbox rows of its events commit or roll back together.
"""

from collections.abc import Sequence
from contextlib import AbstractContextManager
from typing import Protocol

from domain_kernel.ids import DocumentId
from pipeline.domain.crawl import CrawlRun, CrawlRunId
from pipeline.domain.events import DocumentEvent
from pipeline.domain.raw_documents import DocumentStatus, RawDocumentRecord
from pipeline.domain.sources import Source


class SourceRepository(Protocol):
    def get(self, key: str) -> Source | None: ...

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


class CrawlRunRepository(Protocol):
    def add(self, run: CrawlRun) -> None: ...

    def get(self, run_id: CrawlRunId) -> CrawlRun | None: ...

    def save(self, run: CrawlRun) -> None:
        """Write the status, end, counts and error of an existing run."""
        ...

    def latest(self, source_key: str) -> CrawlRun | None:
        """The source's most recently started run."""
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


class UnitOfWorkFactory(Protocol):
    """``factory()`` opens one transaction; it commits when the block ends cleanly."""

    def __call__(self) -> AbstractContextManager[UnitOfWork]: ...
