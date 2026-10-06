"""Pipeline tasks: how one opens, resolves and is dismissed, and the memory store's rules, the
same as the table's (one open task of a kind per document, oldest first, a closed one fixed)."""

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from domain_kernel.documents import DocumentType, document_id_for
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import DocumentId
from pipeline.domain.errors import TaskClosedError
from pipeline.domain.raw_documents import DocumentStatus, RawDocumentRecord
from pipeline.domain.repository import TaskKey
from pipeline.domain.sources import Source, SourceDefinition
from pipeline.domain.tasks import PipelineTask, TaskId, TaskKind, TaskStatus
from pipeline.infrastructure.memory import MemoryStore

NOW = datetime(2026, 10, 6, 6, 0, tzinfo=UTC)
ANALYST = UUID(int=11)
SOURCE = SourceDefinition(
    key="cgst_rules",
    adapter_type="upload",
    parameters={"document_type": "statute"},
    cadence=timedelta(days=31),
    regulator="CBIC",
    doc_type=DocumentType.STATUTE,
)


def stored(content: bytes) -> RawDocumentRecord:
    digest = hashlib.sha256(content).hexdigest()
    return RawDocumentRecord(
        document_id=document_id_for(digest),
        source_key=SOURCE.key,
        source_url=f"upload://cgst_rules/{digest[:32]}",
        fetched_at=NOW,
        content_type="application/pdf",
        size=len(content),
        sha256=digest,
        storage_key=f"{digest[:2]}/{digest}",
    )


def task(
    document_id: DocumentId, minutes: int = 0, kind: TaskKind = TaskKind.MANUAL_PARSE
) -> PipelineTask:
    return PipelineTask.opened(
        kind,
        document_id,
        SOURCE.key,
        at=NOW + timedelta(minutes=minutes),
        reason="pdf@1: the PDF has no text layer",
    )


def store_with(*records: RawDocumentRecord) -> MemoryStore:
    store = MemoryStore()
    with store() as unit:
        unit.sources.add(Source.of(SOURCE, NOW))
        for record in records:
            unit.documents.add(record)
    return store


def test_a_task_opens_resolves_and_then_stays_as_it_is() -> None:
    opened = task(stored(b"scan").document_id)
    assert (opened.status, opened.is_open, opened.resolved_at) == (TaskStatus.OPEN, True, None)
    resolved = opened.resolve(ANALYST, NOW + timedelta(hours=1), {"clauses": 4}, " Typed by hand ")
    assert (resolved.status, resolved.resolved_by, resolved.note) == (
        TaskStatus.RESOLVED,
        ANALYST,
        "Typed by hand",
    )
    assert dict(resolved.resolution or {}) == {"clauses": 4}
    with pytest.raises(TaskClosedError, match="is resolved"):
        resolved.dismiss(ANALYST, NOW, "Too late to dismiss")
    dismissed = opened.dismiss(ANALYST, NOW - timedelta(hours=1), "A duplicate scan")
    assert (dismissed.status, dismissed.resolved_at, dismissed.resolution) == (
        TaskStatus.DISMISSED,
        opened.opened_at,
        None,
    )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"status": TaskStatus.RESOLVED}, "open exactly while"),
        ({"resolved_at": NOW}, "open exactly while"),
        ({"resolved_by": ANALYST}, "an open task has no resolved_by"),
        ({"resolution": {"x": 1}}, "only a resolved task"),
        ({"reason": "x" * 2_001}, "reason must be at most"),
        ({"source_key": "Not A Key"}, "source_key must match"),
        ({"opened_at": datetime(2026, 10, 6)}, "timezone"),
    ],
)
def test_a_task_keeps_its_invariants(overrides: dict[str, object], message: str) -> None:
    values: dict[str, object] = {
        "id": TaskId.new(),
        "kind": TaskKind.MANUAL_PARSE,
        "document_id": stored(b"scan").document_id,
        "source_key": SOURCE.key,
        "opened_at": NOW,
    }
    values.update(overrides)
    with pytest.raises(InvariantViolationError, match=message):
        PipelineTask(**values)  # type: ignore[arg-type]


def test_the_memory_store_opens_one_task_of_a_kind_per_document() -> None:
    scans = [stored(f"scan {n}".encode()) for n in range(3)]
    store = store_with(*scans)
    first = task(scans[0].document_id)
    with store() as unit:
        assert unit.tasks.open(first) == first
        assert unit.tasks.open(task(scans[0].document_id, 5)) == first
        assert unit.tasks.open(task(scans[0].document_id, kind=TaskKind.TRIAGE)).kind is (
            TaskKind.TRIAGE
        )
        for n, scan in enumerate(scans[1:], 1):
            unit.tasks.open(task(scan.document_id, n))
        assert unit.tasks.open_counts() == {TaskKind.MANUAL_PARSE: 3, TaskKind.TRIAGE: 1}
        assert unit.tasks.oldest_open() == {TaskKind.MANUAL_PARSE: NOW, TaskKind.TRIAGE: NOW}
    with store() as unit:
        unit.tasks.save(first.dismiss(ANALYST, NOW + timedelta(hours=1), "A duplicate scan"))
        assert unit.tasks.open_for(scans[0].document_id, TaskKind.MANUAL_PARSE) is None
        assert unit.tasks.open_counts()[TaskKind.MANUAL_PARSE] == 2
        assert unit.tasks.oldest_open()[TaskKind.MANUAL_PARSE] == NOW + timedelta(minutes=1)
        pages: list[PipelineTask] = []
        after: TaskKey | None = None
        while page := unit.tasks.page(status=TaskStatus.OPEN, kind=None, after=after, limit=2):
            pages.extend(page)
            after = TaskKey.of(page[-1])
    assert [t.opened_at for t in pages] == sorted(t.opened_at for t in pages)
    assert len(pages) == 3


def test_a_task_needs_its_stored_document() -> None:
    store = store_with()
    with pytest.raises(KeyError, match="no stored document"), store() as unit:
        unit.tasks.open(task(stored(b"never stored").document_id))


def test_a_parse_is_recorded_on_the_document() -> None:
    scan = stored(b"scan")
    store = store_with(scan)
    with store() as unit:
        assert unit.documents.record_parse(scan.document_id, "manual@1", transcript_key="a/b")
        assert not unit.documents.record_parse(scan.document_id, "manual@1", transcript_key="c/d")
        assert unit.documents.record_parse(scan.document_id, "pdf@1")
        recorded = unit.documents.get(scan.document_id)
    assert recorded is not None
    assert (recorded.status, recorded.parser_version, recorded.transcript_key) == (
        DocumentStatus.PARSED,
        "pdf@1",
        "a/b",
    )
