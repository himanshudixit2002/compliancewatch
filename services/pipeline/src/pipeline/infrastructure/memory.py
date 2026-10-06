"""In-memory store and unit of work: the fakes for tests, demos and the app before Postgres.

A unit of work works on copies of the sources, documents, crawl runs, tasks, classifications,
extractions and retries and replaces the stored ones when the block exits cleanly; its events,
its requeues and its audit entries wait until then too, so they are published exactly when the
rows they describe are. Each published event is also a row of the store's outbox
(``MemoryStore.outbox``, py-common's ``MemoryOutboxStore``), which a relay can drive and whose
dead rows the operations routes list and requeue. Units run one at
a time (a store-level lock held from open to commit or rollback), so two overlapping units cannot
both start from the same copy, and a unit that reads a source "for update" holds nothing more. The
store keeps the same rules the tables do: a document's source must be stored, a document never
changes but for its status and its parse, a task's document must be stored, a document has at most
one open task of a kind, a classification's or an extraction's document must be stored, and an
extraction is kept as written.
"""

import threading
from collections.abc import Collection, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import replace
from datetime import datetime
from uuid import UUID

from domain_kernel.audit import AuditEntry
from domain_kernel.events import utc_now
from domain_kernel.ids import DocumentId
from pipeline.domain.classification import Classification
from pipeline.domain.crawl import CrawlRun, CrawlRunId, CrawlStatus
from pipeline.domain.events import DocumentEvent
from pipeline.domain.extraction import ExtractionOutcome, RuleExtraction
from pipeline.domain.outbox import DeadEventKey, OutboxEvent
from pipeline.domain.raw_documents import DocumentStatus, RawDocumentRecord
from pipeline.domain.repository import (
    DocumentKey,
    DocumentQuery,
    DocumentTally,
    FetchKey,
    RunKey,
    RunQuery,
    TaskKey,
    UnitOfWork,
)
from pipeline.domain.retry import DocumentRetry
from pipeline.domain.sources import Source
from pipeline.domain.tasks import PipelineTask, TaskId, TaskKind, TaskStatus
from pipeline.infrastructure.repository import outbox_event_of
from py_common.audit import MemoryAuditSink
from py_common.events import to_message
from py_common.outbox.admin import DeadKey
from py_common.outbox.testing import MemoryOutboxStore


class MemorySourceRepository:
    def __init__(self, sources: dict[str, Source]) -> None:
        self._sources = sources

    def get(self, key: str, *, for_update: bool = False) -> Source | None:
        return self._sources.get(key)

    def add(self, source: Source) -> bool:
        if source.key in self._sources:
            return False
        self._sources[source.key] = source
        return True

    def save(self, source: Source) -> None:
        if source.key not in self._sources:
            raise KeyError(f"no source {source.key!r} to save")
        self._sources[source.key] = replace(source, created_at=self._sources[source.key].created_at)

    def list(self) -> Sequence[Source]:
        return [self._sources[key] for key in sorted(self._sources)]


class MemoryRawDocumentRepository:
    def __init__(
        self,
        documents: dict[DocumentId, RawDocumentRecord],
        sources: dict[str, Source],
        classifications: dict[DocumentId, Classification] | None = None,
        extractions: dict[tuple[DocumentId, str], RuleExtraction] | None = None,
    ) -> None:
        self._documents = documents
        self._sources = sources
        self._classifications = {} if classifications is None else classifications
        self._extractions = {} if extractions is None else extractions

    def get(self, document_id: DocumentId) -> RawDocumentRecord | None:
        return self._documents.get(document_id)

    def lock(self, document_id: DocumentId) -> RawDocumentRecord | None:
        return self._documents.get(document_id)

    def add(self, record: RawDocumentRecord) -> bool:
        if record.source_key not in self._sources:
            raise KeyError(f"document {record.document_id} names no stored source")
        if record.document_id in self._documents:
            return False
        self._documents[record.document_id] = record
        return True

    def set_status(self, document_id: DocumentId, status: DocumentStatus) -> bool:
        stored = self._documents.get(document_id)
        if stored is None:
            return False
        self._documents[document_id] = replace(stored, status=status)
        return True

    def record_parse(
        self, document_id: DocumentId, parser_version: str, *, transcript_key: str = ""
    ) -> bool:
        stored = self._documents.get(document_id)
        if stored is None:
            return False
        parsed = replace(
            stored,
            status=DocumentStatus.PARSED if stored.status.unparsed else stored.status,
            parser_version=parser_version,
            transcript_key=stored.transcript_key or transcript_key,
        )
        if parsed == stored:
            return False
        self._documents[document_id] = parsed
        return True

    def recent(self, source_key: str, *, limit: int) -> Sequence[RawDocumentRecord]:
        found = [d for d in self._documents.values() if d.source_key == source_key]
        return sorted(found, key=_recent_order)[:limit]

    def page(
        self, source_key: str, *, after: DocumentKey | None, limit: int
    ) -> Sequence[RawDocumentRecord]:
        found = sorted(
            (d for d in self._documents.values() if d.source_key == source_key),
            key=lambda record: _page_order(DocumentKey.of(record)),
        )
        if after is not None:
            start = _page_order(after)
            found = [d for d in found if _page_order(DocumentKey.of(d)) > start]
        return found[:limit]

    def find_by_url(self, source_key: str, url: str) -> RawDocumentRecord | None:
        found = [
            d
            for d in self._documents.values()
            if d.source_key == source_key and d.source_url == url
        ]
        return max(found, key=lambda d: (d.fetched_at, d.document_id.value.int), default=None)

    def known_urls(self, source_key: str, urls: Collection[str]) -> frozenset[str]:
        wanted = set(urls)
        return frozenset(
            d.source_url
            for d in self._documents.values()
            if d.source_key == source_key and d.source_url in wanted
        )

    def counts(self) -> Mapping[str, int]:
        found: dict[str, int] = {}
        for document in self._documents.values():
            found[document.source_key] = found.get(document.source_key, 0) + 1
        return found

    def fetched_since(self, moment: datetime) -> Sequence[RawDocumentRecord]:
        found = [d for d in self._documents.values() if d.fetched_at >= moment]
        return sorted(found, key=lambda d: (d.fetched_at, d.document_id.value.int))

    def search(self, query: DocumentQuery) -> Sequence[RawDocumentRecord]:
        found = sorted(
            (d for d in self._documents.values() if self._admits(query, d)),
            key=lambda d: _fetch_order(FetchKey.of(d)),
            reverse=True,
        )
        if query.after is not None:
            start = _fetch_order(query.after)
            found = [d for d in found if _fetch_order(FetchKey.of(d)) < start]
        return found[: query.limit]

    def _admits(self, query: DocumentQuery, record: RawDocumentRecord) -> bool:
        published = record.published_on
        if query.status not in (None, record.status):
            return False
        if query.source_key not in (None, record.source_key):
            return False
        if query.published_from is not None and (
            published is None or published < query.published_from
        ):
            return False
        if query.published_to is not None and (published is None or published > query.published_to):
            return False
        if query.doc_type is None:
            return True
        classification = self._classifications.get(record.document_id)
        read_as = classification.doc_type if classification is not None else record.doc_type
        if read_as is not None:
            return read_as is query.doc_type
        return record.source_key in query.of_source_type

    def tally(self) -> Mapping[str, DocumentTally]:
        counted: dict[str, tuple[int, int, dict[DocumentStatus, int]]] = {}
        for record in self._documents.values():
            stored, parsed, statuses = counted.get(record.source_key, (0, 0, {}))
            statuses[record.status] = statuses.get(record.status, 0) + 1
            counted[record.source_key] = (
                stored + 1,
                parsed + bool(record.parser_version),
                statuses,
            )
        return {
            key: DocumentTally(stored, parsed, statuses)
            for key, (stored, parsed, statuses) in counted.items()
        }

    def awaiting_extraction(
        self, prompt_version: str, *, source_key: str | None = None, limit: int = 500
    ) -> Sequence[RawDocumentRecord]:
        found = [
            d
            for d in self._documents.values()
            if d.status is DocumentStatus.CLASSIFIED
            and source_key in (None, d.source_key)
            and (d.document_id, prompt_version) not in self._extractions
        ]
        return sorted(found, key=lambda d: (d.fetched_at, d.document_id.value.int))[:limit]

    def awaiting_counts(self, prompt_version: str) -> Mapping[str, int]:
        counted: dict[str, int] = {}
        for document in self.awaiting_extraction(prompt_version, limit=len(self._documents)):
            counted[document.source_key] = counted.get(document.source_key, 0) + 1
        return counted


def _fetch_order(key: FetchKey) -> tuple[float, int]:
    """``FetchKey``'s order, read backwards: uuids compare as their 128-bit integers."""
    return (key.fetched_at.timestamp(), key.document_id.value.int)


def _recent_order(record: RawDocumentRecord) -> tuple[bool, int, float, int]:
    """The Postgres order: the newest publication first with undated ones last, then the latest
    fetch, then the id."""
    published = 0 if record.published_on is None else record.published_on.toordinal()
    return (
        record.published_on is None,
        -published,
        -record.fetched_at.timestamp(),
        record.document_id.value.int,
    )


def _page_order(key: DocumentKey) -> tuple[bool, int, float, int]:
    """``DocumentKey``'s order, which Postgres reads with the id from the highest: uuids compare
    as their 128-bit integers."""
    published = 0 if key.published_on is None else key.published_on.toordinal()
    return (
        key.published_on is None,
        -published,
        -key.fetched_at.timestamp(),
        -key.document_id.value.int,
    )


class MemoryCrawlRunRepository:
    def __init__(self, runs: dict[CrawlRunId, CrawlRun], sources: dict[str, Source]) -> None:
        self._runs = runs
        self._sources = sources

    def add(self, run: CrawlRun) -> None:
        if run.source_key not in self._sources:
            raise KeyError(f"crawl run {run.id} names no stored source")
        if run.id in self._runs:
            raise ValueError(f"duplicate crawl run {run.id}")
        self._runs[run.id] = run

    def start(self, run: CrawlRun) -> bool:
        if run.id in self._runs:
            return False
        self.add(run)
        return True

    def get(self, run_id: CrawlRunId) -> CrawlRun | None:
        return self._runs.get(run_id)

    def save(self, run: CrawlRun) -> None:
        if run.id not in self._runs:
            raise KeyError(f"no crawl run {run.id} to save")
        self._runs[run.id] = run

    def latest(self, source_key: str) -> CrawlRun | None:
        found = [run for run in self._runs.values() if run.source_key == source_key]
        return max(found, key=_started, default=None)

    def latest_by_source(self) -> Mapping[str, CrawlRun]:
        latest: dict[str, CrawlRun] = {}
        for run in sorted(self._runs.values(), key=_started):
            latest[run.source_key] = run
        return latest

    def running(self, source_key: str) -> Sequence[CrawlRun]:
        found = [
            run
            for run in self._runs.values()
            if run.source_key == source_key and run.status is CrawlStatus.RUNNING
        ]
        return sorted(found, key=_started)

    def started_since(self, moment: datetime) -> Sequence[CrawlRun]:
        return sorted(
            (run for run in self._runs.values() if run.started_at >= moment), key=_started
        )

    def page(self, query: RunQuery) -> Sequence[CrawlRun]:
        found = sorted(
            (
                run
                for run in self._runs.values()
                if query.source_key in (None, run.source_key)
                and query.status in (None, run.status)
                and query.trigger in (None, run.trigger)
            ),
            key=_started,
            reverse=True,
        )
        if query.after is not None:
            start = _started_key(query.after)
            found = [run for run in found if _started(run) < start]
        return found[: query.limit]


def _started(run: CrawlRun) -> tuple[datetime, int]:
    return (run.started_at, run.id.value.int)


def _started_key(key: RunKey) -> tuple[datetime, int]:
    return (key.started_at, key.run_id.value.int)


class MemoryTaskRepository:
    def __init__(
        self,
        tasks: dict[TaskId, PipelineTask],
        documents: dict[DocumentId, RawDocumentRecord],
        sources: dict[str, Source],
    ) -> None:
        self._tasks = tasks
        self._documents = documents
        self._sources = sources

    def open(self, task: PipelineTask) -> PipelineTask:
        if task.document_id not in self._documents or task.source_key not in self._sources:
            raise KeyError(f"task {task.id} names no stored document or source")
        found = self.open_for(task.document_id, task.kind)
        if found is not None:
            return found
        if task.id in self._tasks or not task.is_open:
            raise ValueError(f"task {task.id} is stored already or not open")
        self._tasks[task.id] = task
        return task

    def get(self, task_id: TaskId, *, for_update: bool = False) -> PipelineTask | None:
        return self._tasks.get(task_id)

    def save(self, task: PipelineTask) -> None:
        stored = self._tasks.get(task.id)
        if stored is None:
            raise KeyError(f"no task {task.id} to save")
        self._tasks[task.id] = replace(
            task,
            kind=stored.kind,
            document_id=stored.document_id,
            source_key=stored.source_key,
            opened_at=stored.opened_at,
            reason=stored.reason,
        )

    def open_for(self, document_id: DocumentId, kind: TaskKind) -> PipelineTask | None:
        return next(
            (
                task
                for task in self._tasks.values()
                if task.document_id == document_id and task.kind is kind and task.is_open
            ),
            None,
        )

    def of_document(self, document_id: DocumentId) -> Sequence[PipelineTask]:
        return sorted(
            (task for task in self._tasks.values() if task.document_id == document_id),
            key=_task_order,
        )

    def page(
        self,
        *,
        status: TaskStatus | None,
        kind: TaskKind | None,
        after: TaskKey | None,
        limit: int,
    ) -> Sequence[PipelineTask]:
        found = sorted(
            (
                task
                for task in self._tasks.values()
                if (status is None or task.status is status) and (kind is None or task.kind is kind)
            ),
            key=_task_order,
        )
        if after is not None:
            start = (after.opened_at, after.task_id.value.int)
            found = [task for task in found if _task_order(task) > start]
        return found[:limit]

    def open_counts(self) -> Mapping[TaskKind, int]:
        counts: dict[TaskKind, int] = {}
        for task in self._tasks.values():
            if task.is_open:
                counts[task.kind] = counts.get(task.kind, 0) + 1
        return counts

    def oldest_open(self) -> Mapping[TaskKind, datetime]:
        oldest: dict[TaskKind, datetime] = {}
        for task in self._tasks.values():
            if task.is_open and (task.kind not in oldest or task.opened_at < oldest[task.kind]):
                oldest[task.kind] = task.opened_at
        return oldest


def _task_order(task: PipelineTask) -> tuple[datetime, int]:
    return (task.opened_at, task.id.value.int)


class MemoryClassificationRepository:
    def __init__(
        self,
        classifications: dict[DocumentId, Classification],
        documents: dict[DocumentId, RawDocumentRecord],
        tasks: dict[TaskId, PipelineTask],
    ) -> None:
        self._classifications = classifications
        self._documents = documents
        self._tasks = tasks

    def get(self, document_id: DocumentId) -> Classification | None:
        return self._classifications.get(document_id)

    def add(self, classification: Classification) -> bool:
        self._check(classification)
        if classification.document_id in self._classifications:
            return False
        self._classifications[classification.document_id] = classification
        return True

    def save(self, classification: Classification) -> None:
        self._check(classification)
        if classification.document_id not in self._classifications:
            raise KeyError(f"no classification of {classification.document_id} to save")
        self._classifications[classification.document_id] = classification

    def of_documents(
        self, document_ids: Collection[DocumentId]
    ) -> Mapping[DocumentId, Classification]:
        return {
            document_id: self._classifications[document_id]
            for document_id in document_ids
            if document_id in self._classifications
        }

    def _check(self, classification: Classification) -> None:
        if classification.document_id not in self._documents:
            raise KeyError(f"classification of {classification.document_id}: no such document")
        if classification.task_id is not None and classification.task_id not in self._tasks:
            raise KeyError(f"classification of {classification.document_id}: no such task")


class MemoryExtractionRepository:
    def __init__(
        self,
        extractions: dict[tuple[DocumentId, str], RuleExtraction],
        documents: dict[DocumentId, RawDocumentRecord],
    ) -> None:
        self._extractions = extractions
        self._documents = documents

    def get(self, document_id: DocumentId, prompt_version: str) -> RuleExtraction | None:
        return self._extractions.get((document_id, prompt_version))

    def add(self, extraction: RuleExtraction) -> bool:
        if extraction.document_id not in self._documents:
            raise KeyError(f"extraction of {extraction.document_id}: no such document")
        key = (extraction.document_id, extraction.prompt_version)
        if key in self._extractions:
            return False
        if any(
            stored.candidate_id == extraction.candidate_id for stored in self._extractions.values()
        ):
            raise ValueError(f"candidate {extraction.candidate_id} is stored already")
        self._extractions[key] = extraction
        return True

    def of_documents(
        self, document_ids: Collection[DocumentId], prompt_version: str
    ) -> Mapping[DocumentId, RuleExtraction]:
        return {
            document_id: self._extractions[document_id, prompt_version]
            for document_id in document_ids
            if (document_id, prompt_version) in self._extractions
        }

    def tally(self, prompt_version: str) -> Mapping[str, Mapping[ExtractionOutcome, int]]:
        counted: dict[str, dict[ExtractionOutcome, int]] = {}
        for (_, prompt), extraction in self._extractions.items():
            if prompt == prompt_version:
                outcomes = counted.setdefault(extraction.source_key, {})
                outcomes[extraction.outcome] = outcomes.get(extraction.outcome, 0) + 1
        return counted


class MemoryRetryRepository:
    def __init__(
        self,
        retries: dict[tuple[DocumentId, int], DocumentRetry],
        documents: dict[DocumentId, RawDocumentRecord],
    ) -> None:
        self._retries = retries
        self._documents = documents

    def add(self, retry: DocumentRetry) -> bool:
        if retry.document_id not in self._documents:
            raise KeyError(f"retry of {retry.document_id}: no such document")
        taken = any(
            stored.id == retry.id
            or (
                stored.document_id == retry.document_id
                and stored.idempotency_key == retry.idempotency_key
            )
            for stored in self._retries.values()
        )
        if taken or (retry.document_id, retry.attempt) in self._retries:
            return False
        self._retries[retry.document_id, retry.attempt] = retry
        return True

    def of_document(self, document_id: DocumentId) -> Sequence[DocumentRetry]:
        return sorted(
            (retry for retry in self._retries.values() if retry.document_id == document_id),
            key=lambda retry: retry.attempt,
        )


class MemoryOutboxRepository:
    """The store's outbox: reads at once, requeues when the unit commits."""

    def __init__(self, outbox: MemoryOutboxStore) -> None:
        self._outbox = outbox
        self.requeued: dict[UUID, datetime] = {}

    def dead(
        self, *, topic: str | None = None, after: DeadEventKey | None = None, limit: int = 50
    ) -> Sequence[OutboxEvent]:
        key = None if after is None else DeadKey(after.dead_at, after.event_id)
        rows = self._outbox.dead(topic=topic, after=key, limit=limit + len(self.requeued))
        return [outbox_event_of(row) for row in rows if row.event_id not in self.requeued][:limit]

    def get(self, event_id: UUID) -> OutboxEvent | None:
        row = self._outbox.get(event_id)
        if row is None:
            return None
        if event_id in self.requeued:
            row = replace(row, status="pending", attempts=0, available_at=self.requeued[event_id])
        return outbox_event_of(row)

    def requeue(self, event_id: UUID, *, at: datetime) -> bool:
        row = self._outbox.get(event_id)
        if row is None or not row.is_dead or event_id in self.requeued:
            return False
        self.requeued[event_id] = at
        return True

    def commit(self) -> None:
        for event_id, at in self.requeued.items():
            self._outbox.requeue(event_id, at=at)
        self.requeued.clear()


class MemoryEventSink:
    def __init__(
        self, published: list[DocumentEvent], outbox: MemoryOutboxStore | None = None
    ) -> None:
        self._published = published
        self._outbox = outbox
        self.pending: list[DocumentEvent] = []

    def publish(self, event: DocumentEvent) -> None:
        self.pending.append(event)

    def commit(self) -> None:
        self._published.extend(self.pending)
        if self._outbox is not None:
            now = utc_now()
            for event in self.pending:
                self._outbox.add(
                    to_message(event), partition_key=event.partition_key, available_at=now
                )
        self.pending.clear()


class MemoryUnitOfWork:
    def __init__(self, store: "MemoryStore") -> None:
        self._store = store
        self._sources: dict[str, Source] = {}
        self._documents: dict[DocumentId, RawDocumentRecord] = {}
        self._runs: dict[CrawlRunId, CrawlRun] = {}
        self._tasks: dict[TaskId, PipelineTask] = {}
        self._classifications: dict[DocumentId, Classification] = {}
        self._extractions: dict[tuple[DocumentId, str], RuleExtraction] = {}
        self._retries: dict[tuple[DocumentId, int], DocumentRetry] = {}
        self.sources = MemorySourceRepository(self._sources)
        self.documents = MemoryRawDocumentRepository(
            self._documents, self._sources, self._classifications, self._extractions
        )
        self.crawl_runs = MemoryCrawlRunRepository(self._runs, self._sources)
        self.tasks = MemoryTaskRepository(self._tasks, self._documents, self._sources)
        self.classifications = MemoryClassificationRepository(
            self._classifications, self._documents, self._tasks
        )
        self.extractions = MemoryExtractionRepository(self._extractions, self._documents)
        self.retries = MemoryRetryRepository(self._retries, self._documents)
        self.outbox = MemoryOutboxRepository(store.outbox)
        self.events = MemoryEventSink(store.events, store.outbox)
        self.audit = MemoryAuditSink(store.audit)

    def __enter__(self) -> "MemoryUnitOfWork":
        self._sources.update(self._store.sources)
        self._documents.update(self._store.documents)
        self._runs.update(self._store.crawl_runs)
        self._tasks.update(self._store.tasks)
        self._classifications.update(self._store.classifications)
        self._extractions.update(self._store.extractions)
        self._retries.update(self._store.retries)
        return self

    def __exit__(self, exc_type: object, *exc_info: object) -> None:
        if exc_type is None:
            self._store.sources.clear()
            self._store.sources.update(self._sources)
            self._store.documents.clear()
            self._store.documents.update(self._documents)
            self._store.crawl_runs.clear()
            self._store.crawl_runs.update(self._runs)
            self._store.tasks.clear()
            self._store.tasks.update(self._tasks)
            self._store.classifications.clear()
            self._store.classifications.update(self._classifications)
            self._store.extractions.clear()
            self._store.extractions.update(self._extractions)
            self._store.retries.clear()
            self._store.retries.update(self._retries)
            self.events.commit()
            self.outbox.commit()
            self.audit.commit()
        else:
            self.audit.rollback()


class MemoryStore:
    """Holds the sources, documents, crawl runs, tasks, classifications, extractions, retries,
    published events with their outbox rows, and audit entries; makes units of work."""

    def __init__(self) -> None:
        self.sources: dict[str, Source] = {}
        self.documents: dict[DocumentId, RawDocumentRecord] = {}
        self.crawl_runs: dict[CrawlRunId, CrawlRun] = {}
        self.tasks: dict[TaskId, PipelineTask] = {}
        self.classifications: dict[DocumentId, Classification] = {}
        self.extractions: dict[tuple[DocumentId, str], RuleExtraction] = {}
        self.retries: dict[tuple[DocumentId, int], DocumentRetry] = {}
        self.events: list[DocumentEvent] = []
        self.outbox = MemoryOutboxStore()
        self.audit: list[AuditEntry] = []
        self._lock = threading.Lock()

    def ping(self) -> bool:
        return True

    def __call__(self) -> AbstractContextManager[UnitOfWork]:
        return self._unit()

    @contextmanager
    def _unit(self) -> Iterator[UnitOfWork]:
        with self._lock, MemoryUnitOfWork(self) as unit:
            yield unit
