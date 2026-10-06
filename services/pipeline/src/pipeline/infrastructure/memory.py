"""In-memory store and unit of work: the fakes for tests, demos and the app before Postgres.

A unit of work works on copies of the sources, documents, crawl runs and tasks and replaces the
stored ones when the block exits cleanly; its events and audit entries wait until then too, so
they are published exactly when the rows they describe are. Units run one at a time (a
store-level lock held from open to commit or rollback), so two overlapping units cannot both
start from the same copy, and a unit that reads a source "for update" holds nothing more. The
store keeps the same rules the tables do: a document's source must be stored, a document never
changes but for its status and its parse, a task's document must be stored, and a document has
at most one open task of a kind.
"""

import threading
from collections.abc import Collection, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import replace
from datetime import datetime

from domain_kernel.audit import AuditEntry
from domain_kernel.ids import DocumentId
from pipeline.domain.crawl import CrawlRun, CrawlRunId, CrawlStatus
from pipeline.domain.events import DocumentEvent
from pipeline.domain.raw_documents import DocumentStatus, RawDocumentRecord
from pipeline.domain.repository import DocumentKey, TaskKey, UnitOfWork
from pipeline.domain.sources import Source
from pipeline.domain.tasks import PipelineTask, TaskId, TaskKind, TaskStatus
from py_common.audit import MemoryAuditSink


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
        self, documents: dict[DocumentId, RawDocumentRecord], sources: dict[str, Source]
    ) -> None:
        self._documents = documents
        self._sources = sources

    def get(self, document_id: DocumentId) -> RawDocumentRecord | None:
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
            status=DocumentStatus.PARSED,
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


def _started(run: CrawlRun) -> tuple[datetime, int]:
    return (run.started_at, run.id.value.int)


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


def _task_order(task: PipelineTask) -> tuple[datetime, int]:
    return (task.opened_at, task.id.value.int)


class MemoryEventSink:
    def __init__(self, published: list[DocumentEvent]) -> None:
        self._published = published
        self.pending: list[DocumentEvent] = []

    def publish(self, event: DocumentEvent) -> None:
        self.pending.append(event)

    def commit(self) -> None:
        self._published.extend(self.pending)
        self.pending.clear()


class MemoryUnitOfWork:
    def __init__(self, store: "MemoryStore") -> None:
        self._store = store
        self._sources: dict[str, Source] = {}
        self._documents: dict[DocumentId, RawDocumentRecord] = {}
        self._runs: dict[CrawlRunId, CrawlRun] = {}
        self._tasks: dict[TaskId, PipelineTask] = {}
        self.sources = MemorySourceRepository(self._sources)
        self.documents = MemoryRawDocumentRepository(self._documents, self._sources)
        self.crawl_runs = MemoryCrawlRunRepository(self._runs, self._sources)
        self.tasks = MemoryTaskRepository(self._tasks, self._documents, self._sources)
        self.events = MemoryEventSink(store.events)
        self.audit = MemoryAuditSink(store.audit)

    def __enter__(self) -> "MemoryUnitOfWork":
        self._sources.update(self._store.sources)
        self._documents.update(self._store.documents)
        self._runs.update(self._store.crawl_runs)
        self._tasks.update(self._store.tasks)
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
            self.events.commit()
            self.audit.commit()
        else:
            self.audit.rollback()


class MemoryStore:
    """Holds the sources, documents, crawl runs, tasks, published events and audit entries;
    makes units of work."""

    def __init__(self) -> None:
        self.sources: dict[str, Source] = {}
        self.documents: dict[DocumentId, RawDocumentRecord] = {}
        self.crawl_runs: dict[CrawlRunId, CrawlRun] = {}
        self.tasks: dict[TaskId, PipelineTask] = {}
        self.events: list[DocumentEvent] = []
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
