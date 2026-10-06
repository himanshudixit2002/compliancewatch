"""The pipeline's store on its memory implementation: the rows' rules, the repositories, and a
unit of work that publishes its events only when it commits."""

import hashlib
from datetime import UTC, date, datetime, timedelta

import pytest

from domain_kernel.documents import DocumentType, document_id_for
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import DocumentId, SourceId
from pipeline.domain.crawl import CrawlCounts, CrawlRun, CrawlStatus
from pipeline.domain.events import DocumentDiscovered
from pipeline.domain.raw_documents import DocumentStatus, RawDocumentRecord
from pipeline.domain.sources import Source, SourceDefinition
from pipeline.infrastructure.memory import MemoryStore

NOW = datetime(2026, 10, 6, 4, 30, tzinfo=UTC)
DEFINITION = SourceDefinition(
    key="cbic_notifications",
    adapter_type="cbic",
    parameters={"listing": "notifications", "category": "Central Tax"},
    cadence=timedelta(hours=2),
    regulator="CBIC",
    doc_type=DocumentType.NOTIFICATION,
)


def record(content: bytes, **overrides: object) -> RawDocumentRecord:
    digest = hashlib.sha256(content).hexdigest()
    values: dict[str, object] = {
        "document_id": document_id_for(digest),
        "source_key": DEFINITION.key,
        "source_url": "https://example.invalid/notification.pdf",
        "fetched_at": NOW,
        "content_type": "application/pdf",
        "size": len(content),
        "sha256": digest,
        "storage_key": f"{digest[:2]}/{digest}",
    }
    values.update(overrides)
    return RawDocumentRecord(**values)  # type: ignore[arg-type]


def discovered(stored: RawDocumentRecord) -> DocumentDiscovered:
    return DocumentDiscovered(
        source_id=SourceId.new(),
        document_id=stored.document_id,
        regulator="CBIC",
        url=stored.source_url,
        external_ref="",
        title="",
        published_at=None,
        sha256=stored.sha256,
        media_type=stored.content_type,
        fetched_at=stored.fetched_at,
        raw_uri=f"memory://{stored.storage_key}",
    )


def test_a_source_is_recorded_from_its_definition() -> None:
    source = Source.of(DEFINITION, NOW)
    assert (source.key, source.adapter_type, source.cadence) == (
        "cbic_notifications",
        "cbic",
        timedelta(hours=2),
    )
    assert dict(source.parameters) == {"listing": "notifications", "category": "Central Tax"}
    assert (source.enabled, source.paused, source.last_fetch_at, source.watermark) == (
        True,
        False,
        None,
        None,
    )
    with pytest.raises(TypeError):
        source.parameters["category"] = "Integrated Tax"  # type: ignore[index]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"key": "CBIC notifications"}, "key must match"),
        ({"adapter_type": "cbic-v2"}, "adapter_type must match"),
        ({"cadence": timedelta(seconds=30)}, "cadence must be at least"),
        ({"regulator": " "}, "regulator must not be blank"),
    ],
)
def test_a_definition_refuses_what_the_table_would(change: dict[str, object], message: str) -> None:
    values: dict[str, object] = {
        "key": DEFINITION.key,
        "adapter_type": DEFINITION.adapter_type,
        "parameters": DEFINITION.parameters,
        "cadence": DEFINITION.cadence,
        "regulator": DEFINITION.regulator,
        "doc_type": DEFINITION.doc_type,
    }
    values.update(change)
    with pytest.raises(InvariantViolationError, match=message):
        SourceDefinition(**values)  # type: ignore[arg-type]


def test_a_record_is_keyed_by_its_bytes() -> None:
    stored = record(b"%PDF-1.7 notification")
    assert stored.document_id == document_id_for(stored.sha256)
    assert stored.status is DocumentStatus.DISCOVERED
    with pytest.raises(InvariantViolationError, match="first half of sha256"):
        record(b"%PDF-1.7 notification", document_id=DocumentId.new())
    with pytest.raises(InvariantViolationError, match="size"):
        record(b"x", size=0)


def test_a_crawl_run_finishes_once_and_fails_with_its_error() -> None:
    run = CrawlRun.start(DEFINITION.key, NOW)
    assert (run.status, run.finished_at, run.counts) == (CrawlStatus.RUNNING, None, CrawlCounts())
    done = run.finish(NOW + timedelta(minutes=1), CrawlCounts(listed=3, stored=2, duplicates=1))
    assert (done.status, done.counts.fetched, done.error) == (CrawlStatus.COMPLETED, 3, "")
    failed = run.finish(NOW + timedelta(minutes=1), CrawlCounts(listed=1, failed=1), error="503")
    assert (failed.status, failed.error) == (CrawlStatus.FAILED, "503")
    with pytest.raises(InvariantViolationError, match="already completed"):
        done.finish(NOW + timedelta(minutes=2), CrawlCounts())
    with pytest.raises(InvariantViolationError, match="listed must be at least 0"):
        CrawlCounts(listed=-1)


def test_a_unit_of_work_commits_rows_and_events_together() -> None:
    store = MemoryStore()
    stored = record(b"%PDF-1.7 first")
    with store() as unit:
        assert unit.sources.add(Source.of(DEFINITION, NOW))
        assert unit.documents.add(stored)
        unit.events.publish(discovered(stored))
        assert store.events == [], "events wait for the commit"
    assert [event.document_id for event in store.events] == [stored.document_id]
    assert store.documents == {stored.document_id: stored}

    def write_then_fail() -> None:
        with store() as unit:
            unit.documents.add(record(b"%PDF-1.7 second"))
            unit.events.publish(discovered(record(b"%PDF-1.7 second")))
            raise RuntimeError("the transaction fails")

    with pytest.raises(RuntimeError, match="the transaction fails"):
        write_then_fail()
    assert list(store.documents) == [stored.document_id]
    assert len(store.events) == 1


def test_adding_a_stored_source_or_document_again_changes_nothing() -> None:
    store = MemoryStore()
    stored = record(b"%PDF-1.7 once")
    with store() as unit:
        unit.sources.add(Source.of(DEFINITION, NOW))
        unit.documents.add(stored)
    later = Source.of(DEFINITION, NOW + timedelta(days=1))
    with store() as unit:
        assert unit.sources.add(later) is False
        assert unit.documents.add(record(b"%PDF-1.7 once", title="again")) is False
        source = unit.sources.get(DEFINITION.key)
        document = unit.documents.get(stored.document_id)
    assert source is not None
    assert source.created_at == NOW
    assert document == stored


def test_a_document_needs_its_source() -> None:
    store = MemoryStore()
    with pytest.raises(KeyError, match="no stored source"), store() as unit:
        unit.documents.add(record(b"%PDF-1.7 orphan"))
    assert store.documents == {}


def test_a_document_changes_only_its_status_and_lists_newest_first() -> None:
    store = MemoryStore()
    old = record(b"old", published_on=date(2026, 1, 5))
    new = record(b"new", published_on=date(2026, 9, 1))
    undated = record(b"undated", fetched_at=NOW + timedelta(hours=1))
    with store() as unit:
        unit.sources.add(Source.of(DEFINITION, NOW))
        for document in (old, undated, new):
            unit.documents.add(document)
        assert unit.documents.set_status(new.document_id, DocumentStatus.PARSED)
        assert not unit.documents.set_status(DocumentId.new(), DocumentStatus.FAILED)
        recent = unit.documents.recent(DEFINITION.key, limit=10)
        assert unit.documents.recent("gstn_advisories", limit=10) == []
    assert [d.document_id for d in recent] == [
        new.document_id,
        old.document_id,
        undated.document_id,
    ]
    assert recent[0].status is DocumentStatus.PARSED
    assert store.documents[new.document_id].status is DocumentStatus.PARSED


def test_sources_are_saved_and_listed_by_key() -> None:
    store = MemoryStore()
    gstn = SourceDefinition(
        key="gstn_advisories",
        adapter_type="gstn",
        parameters={},
        cadence=timedelta(hours=3),
        regulator="GSTN",
        doc_type=DocumentType.PRESS_RELEASE,
    )
    with store() as unit:
        unit.sources.add(Source.of(gstn, NOW))
        unit.sources.add(Source.of(DEFINITION, NOW))
    paused = Source(
        key=DEFINITION.key,
        adapter_type="cbic",
        parameters=DEFINITION.parameters,
        cadence=DEFINITION.cadence,
        created_at=NOW,
        updated_at=NOW + timedelta(hours=1),
        paused=True,
        last_fetch_at=NOW,
        watermark={"published_on": "2026-09-30"},
    )
    with store() as unit:
        unit.sources.save(paused)
        listed = unit.sources.list()
    assert [source.key for source in listed] == ["cbic_notifications", "gstn_advisories"]
    assert listed[0].paused
    assert listed[0].watermark == {"published_on": "2026-09-30"}


def test_crawl_runs_are_kept_per_source() -> None:
    store = MemoryStore()
    first = CrawlRun.start(DEFINITION.key, NOW)
    second = CrawlRun.start(DEFINITION.key, NOW + timedelta(hours=2))
    with store() as unit:
        unit.sources.add(Source.of(DEFINITION, NOW))
        unit.crawl_runs.add(first)
        unit.crawl_runs.add(second)
        unit.crawl_runs.save(second.finish(NOW + timedelta(hours=3), CrawlCounts(listed=1)))
        latest = unit.crawl_runs.latest(DEFINITION.key)
        assert unit.crawl_runs.latest("gstn_advisories") is None
        assert unit.crawl_runs.get(first.id) == first
        with pytest.raises(ValueError, match="duplicate"):
            unit.crawl_runs.add(first)
    assert latest is not None
    assert (latest.id, latest.status) == (second.id, CrawlStatus.COMPLETED)
