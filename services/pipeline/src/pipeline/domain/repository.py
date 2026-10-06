"""What the application layer needs from the pipeline's store, as protocols the infrastructure
implements (Postgres in ``infrastructure.repository``, memory in ``infrastructure.memory``).

The store holds regulatory data, the same for every tenant: a unit of work opens one transaction
with no tenant setting. Its rows, the outbox rows of its events and its audit entries (of no
tenant, in ``audit.event``) commit or roll back together.
"""

from collections.abc import Collection, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from domain_kernel.audit import AuditSink
from domain_kernel.documents import DocumentType
from domain_kernel.ids import DocumentId
from pipeline.domain.classification import Classification
from pipeline.domain.crawl import CrawlRun, CrawlRunId, CrawlStatus, CrawlTrigger
from pipeline.domain.events import DocumentEvent
from pipeline.domain.extraction import ExtractionOutcome, RuleExtraction
from pipeline.domain.outbox import DeadEventKey, OutboxEvent
from pipeline.domain.raw_documents import DocumentStatus, RawDocumentRecord
from pipeline.domain.retry import DocumentRetry
from pipeline.domain.sources import Source
from pipeline.domain.tasks import PipelineTask, TaskId, TaskKind, TaskStatus


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


@dataclass(frozen=True, slots=True)
class FetchKey:
    """Where a page of every source's documents starts: after the document first fetched at
    ``fetched_at`` with ``document_id``. The order is the latest first fetch first, then the id
    from the highest."""

    fetched_at: datetime
    document_id: DocumentId

    @classmethod
    def of(cls, record: RawDocumentRecord) -> "FetchKey":
        return cls(record.fetched_at, record.document_id)


@dataclass(frozen=True, slots=True)
class DocumentQuery:
    """Which of every source's documents a page holds: of ``status`` and ``source_key``, read as
    ``doc_type`` (its classification's type, else its uploader's, else its source's:
    ``of_source_type`` names the sources that publish that type), published from
    ``published_from`` to ``published_to`` (both included; an undated document matches no date),
    after ``after``, at most ``limit``. None leaves a filter out."""

    status: DocumentStatus | None = None
    source_key: str | None = None
    doc_type: DocumentType | None = None
    of_source_type: frozenset[str] = frozenset()
    published_from: date | None = None
    published_to: date | None = None
    after: FetchKey | None = None
    limit: int = 50


@dataclass(frozen=True, slots=True)
class DocumentTally:
    """One source's documents: how many are stored, how many have a parse recorded, and how many
    stand at each status (a status with none is absent)."""

    stored: int = 0
    parsed: int = 0
    statuses: Mapping[DocumentStatus, int] = field(default_factory=dict)

    def at(self, status: DocumentStatus) -> int:
        return self.statuses.get(status, 0)


@dataclass(frozen=True, slots=True)
class RunKey:
    """Where a page of crawl runs starts: after the run started at ``started_at`` with
    ``run_id``. Runs come the latest started first, then by id from the highest."""

    started_at: datetime
    run_id: CrawlRunId

    @classmethod
    def of(cls, run: CrawlRun) -> "RunKey":
        return cls(run.started_at, run.id)


@dataclass(frozen=True, slots=True)
class RunQuery:
    """Which crawl runs a page holds: of ``source_key``, ``status`` and ``trigger`` (None leaves a
    filter out), after ``after``, at most ``limit``."""

    source_key: str | None = None
    status: CrawlStatus | None = None
    trigger: CrawlTrigger | None = None
    after: RunKey | None = None
    limit: int = 50


@dataclass(frozen=True, slots=True)
class TaskKey:
    """Where a page of tasks starts: after the task opened at ``opened_at`` with ``task_id``.
    Tasks come oldest first, then by id."""

    opened_at: datetime
    task_id: TaskId

    @classmethod
    def of(cls, task: PipelineTask) -> "TaskKey":
        return cls(task.opened_at, task.id)


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

    def lock(self, document_id: DocumentId) -> RawDocumentRecord | None:
        """The document, its row held until the unit ends, so two retries of it run one after
        the other."""
        ...

    def add(self, record: RawDocumentRecord) -> bool:
        """Insert the record unless one with its id (its bytes) exists, which is left as it is;
        True when it was inserted. Its source must be stored."""
        ...

    def set_status(self, document_id: DocumentId, status: DocumentStatus) -> bool:
        """Move a stored document to ``status``; False when there is no such document."""
        ...

    def record_parse(
        self, document_id: DocumentId, parser_version: str, *, transcript_key: str = ""
    ) -> bool:
        """Record the document's parse by ``parser_version`` (from the transcript under
        ``transcript_key``, when one is given; a transcript once named stays), and set it
        ``parsed`` when no parse was recorded before (``DocumentStatus.unparsed``): a document
        classified, held for triage, kept for reference or extracted keeps its status. True when
        that changed anything, False when it stood so already or there is no such document."""
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

    def search(self, query: DocumentQuery) -> Sequence[RawDocumentRecord]:
        """Every source's documents the query admits, the latest first fetch first, then by id
        from the highest (``FetchKey``)."""
        ...

    def tally(self) -> Mapping[str, DocumentTally]:
        """Each source's documents counted: stored, parsed, and by status; a source without any
        is absent."""
        ...

    def awaiting_extraction(
        self, prompt_version: str, *, source_key: str | None = None, limit: int = 500
    ) -> Sequence[RawDocumentRecord]:
        """The documents that wait as ``classified`` with no extraction stored for
        ``prompt_version``, of one source or every one, the first fetched first, at most
        ``limit``."""
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

    def page(self, query: RunQuery) -> Sequence[CrawlRun]:
        """The runs the query admits in ``RunKey`` order: the latest started first."""
        ...


class TaskRepository(Protocol):
    def open(self, task: PipelineTask) -> PipelineTask:
        """Insert the open task unless its document has an open task of its kind already, and
        return the open one: this task, or the one found."""
        ...

    def get(self, task_id: TaskId, *, for_update: bool = False) -> PipelineTask | None:
        """The task; ``for_update`` holds it until the unit ends."""
        ...

    def save(self, task: PipelineTask) -> None:
        """Write the status, claim, resolution and note of an existing task."""
        ...

    def open_for(self, document_id: DocumentId, kind: TaskKind) -> PipelineTask | None:
        """The document's open task of ``kind``, if any."""
        ...

    def of_document(self, document_id: DocumentId) -> Sequence[PipelineTask]:
        """Every task of the document, open or closed, oldest first."""
        ...

    def page(
        self,
        *,
        status: TaskStatus | None,
        kind: TaskKind | None,
        after: TaskKey | None,
        limit: int,
    ) -> Sequence[PipelineTask]:
        """The tasks of ``status`` and ``kind`` (None: any) in ``TaskKey`` order, after
        ``after``."""
        ...

    def open_counts(self) -> Mapping[TaskKind, int]:
        """How many tasks of each kind are open; a kind with none is absent."""
        ...

    def oldest_open(self) -> Mapping[TaskKind, datetime]:
        """When the oldest open task of each kind was opened; a kind with none is absent."""
        ...


class ClassificationRepository(Protocol):
    def get(self, document_id: DocumentId) -> Classification | None: ...

    def add(self, classification: Classification) -> bool:
        """Insert the document's classification unless it has one, which is left as it is; True
        when it was inserted."""
        ...

    def save(self, classification: Classification) -> None:
        """Replace the stored classification of the document (a person's triage or type, the
        detector reading it again)."""
        ...

    def of_documents(
        self, document_ids: Collection[DocumentId]
    ) -> Mapping[DocumentId, Classification]:
        """The classifications of those of ``document_ids`` that have one."""
        ...


class ExtractionRepository(Protocol):
    def get(self, document_id: DocumentId, prompt_version: str) -> RuleExtraction | None: ...

    def add(self, extraction: RuleExtraction) -> bool:
        """Insert the extraction unless one of its document and prompt version is stored,
        which is kept as written; True when it was inserted."""
        ...

    def of_documents(
        self, document_ids: Collection[DocumentId], prompt_version: str
    ) -> Mapping[DocumentId, RuleExtraction]:
        """The extractions by ``prompt_version`` of those of ``document_ids`` that have one."""
        ...

    def tally(self, prompt_version: str) -> Mapping[str, Mapping[ExtractionOutcome, int]]:
        """The extractions by ``prompt_version`` of each source's documents, by outcome; a
        source without any is absent."""
        ...


class RetryRepository(Protocol):
    def add(self, retry: DocumentRetry) -> bool:
        """Insert the retry unless its document has a retry of its attempt or of its
        Idempotency-Key; True when it was inserted. A retry is kept as written."""
        ...

    def of_document(self, document_id: DocumentId) -> Sequence[DocumentRetry]:
        """The document's retries by attempt."""
        ...


class OutboxRepository(Protocol):
    """The pipeline's ``outbox_event`` rows, on the unit's connection."""

    def dead(
        self, *, topic: str | None = None, after: DeadEventKey | None = None, limit: int = 50
    ) -> Sequence[OutboxEvent]:
        """The dead rows (of ``topic``), the newest dead first (``DeadEventKey``)."""
        ...

    def get(self, event_id: UUID) -> OutboxEvent | None:
        """One row, whatever its status."""
        ...

    def requeue(self, event_id: UUID, *, at: datetime) -> bool:
        """A dead row back to pending with its attempts reset and due at ``at``; False, with
        nothing changed, for a row that is not dead."""
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
    def tasks(self) -> TaskRepository: ...

    @property
    def classifications(self) -> ClassificationRepository: ...

    @property
    def extractions(self) -> ExtractionRepository: ...

    @property
    def retries(self) -> RetryRepository: ...

    @property
    def outbox(self) -> OutboxRepository: ...

    @property
    def events(self) -> EventSink: ...

    @property
    def audit(self) -> AuditSink: ...


class UnitOfWorkFactory(Protocol):
    """``factory()`` opens one transaction; it commits when the block ends cleanly."""

    def __call__(self) -> AbstractContextManager[UnitOfWork]: ...
