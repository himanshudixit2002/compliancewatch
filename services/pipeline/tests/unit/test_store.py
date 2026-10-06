"""The pipeline's store on its memory implementation: the rows' rules, the repositories, and a
unit of work that publishes its events only when it commits."""

import hashlib
from datetime import UTC, date, datetime, timedelta

import pytest

from domain_kernel.documents import DocumentType, document_id_for
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import DocumentId, SourceId
from pipeline.domain.classification import Classification, Relevance, TypeConfidence
from pipeline.domain.crawl import CrawlCounts, CrawlRun, CrawlStatus
from pipeline.domain.events import DocumentDiscovered
from pipeline.domain.extraction import ExtractionOutcome, RuleExtraction, candidate_id_for
from pipeline.domain.issues import Issue
from pipeline.domain.raw_documents import DocumentStatus, RawDocumentRecord
from pipeline.domain.sources import Source, SourceDefinition
from pipeline.domain.tasks import PipelineTask, TaskKind
from pipeline.infrastructure.memory import MemoryStore
from py_common.audit.testing import audit_entry

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


def test_the_crawl_finds_known_urls_and_counts_documents_per_source() -> None:
    store = MemoryStore()
    first = record(b"first", source_url="https://example.invalid/a.pdf", fetched_at=NOW)
    again = record(
        b"first, corrected",
        source_url="https://example.invalid/a.pdf",
        fetched_at=NOW + timedelta(1),
    )
    other = record(b"other", source_url="https://example.invalid/b.pdf", fetched_at=NOW)
    with store() as unit:
        unit.sources.add(Source.of(DEFINITION, NOW))
        for document in (first, again, other):
            unit.documents.add(document)
        assert unit.sources.get(DEFINITION.key, for_update=True) == unit.sources.get(DEFINITION.key)
        found = unit.documents.find_by_url(DEFINITION.key, "https://example.invalid/a.pdf")
        assert found == again, "the latest fetch of the URL"
        assert unit.documents.find_by_url(DEFINITION.key, "https://example.invalid/c.pdf") is None
        assert (
            unit.documents.find_by_url("gstn_advisories", "https://example.invalid/a.pdf") is None
        )
        known = unit.documents.known_urls(
            DEFINITION.key, ["https://example.invalid/a.pdf", "https://example.invalid/c.pdf"]
        )
        assert known == frozenset({"https://example.invalid/a.pdf"})
        assert (
            unit.documents.known_urls("gstn_advisories", ["https://example.invalid/a.pdf"]) == set()
        )
        assert unit.documents.counts() == {DEFINITION.key: 3}
        since = unit.documents.fetched_since(NOW + timedelta(hours=1))
        assert since == [again]


def test_runs_start_once_and_are_found_per_source() -> None:
    store = MemoryStore()
    first = CrawlRun.start(DEFINITION.key, NOW)
    second = CrawlRun.start(DEFINITION.key, NOW + timedelta(hours=2))
    with store() as unit:
        unit.sources.add(Source.of(DEFINITION, NOW))
        assert unit.crawl_runs.start(first)
        assert not unit.crawl_runs.start(first)
        assert unit.crawl_runs.start(second)
        unit.crawl_runs.save(first.finish(NOW + timedelta(minutes=5), CrawlCounts()))
        assert unit.crawl_runs.running(DEFINITION.key) == [second]
        assert unit.crawl_runs.latest_by_source() == {DEFINITION.key: second}
        assert unit.crawl_runs.started_since(NOW + timedelta(hours=1)) == [second]
        with pytest.raises(KeyError, match="no stored source"):
            unit.crawl_runs.start(CrawlRun.start("gstn_advisories", NOW))


def test_audit_entries_commit_with_the_unit_and_go_with_a_failed_one() -> None:
    store = MemoryStore()
    entry = audit_entry(tenant_id=None)
    with store() as unit:
        unit.audit.write(entry)
    assert store.audit == [entry]

    def write_then_fail() -> None:
        with store() as unit:
            unit.audit.write(audit_entry(tenant_id=None))
            raise RuntimeError("the unit fails")

    with pytest.raises(RuntimeError):
        write_then_fail()
    assert store.audit == [entry]


def test_a_classification_is_added_once_saved_by_a_triage_and_needs_its_rows() -> None:
    store = MemoryStore()
    stored = record(b"%PDF-1.7 classified")
    task = PipelineTask.opened(TaskKind.TRIAGE, stored.document_id, DEFINITION.key, at=NOW)
    first = Classification(
        document_id=stored.document_id,
        doc_type=DocumentType.CIRCULAR,
        relevance=Relevance.RELEVANT,
        confidence=TypeConfidence.CONFLICT,
        reasons=("its opening names it a circular",),
        classified_at=NOW,
        task_id=task.id,
    )
    with store() as unit:
        unit.sources.add(Source.of(DEFINITION, NOW))
        unit.documents.add(stored)
        with pytest.raises(KeyError, match="no such task"):
            unit.classifications.add(first)
        unit.tasks.open(task)
        assert unit.classifications.add(first)
        assert not unit.classifications.add(first)
    triaged = Classification.triaged(
        stored.document_id,
        relevance=Relevance.IRRELEVANT,
        doc_type=DocumentType.CIRCULAR,
        by=None,
        task_id=task.id,
        at=NOW,
        reason="A portal manual",
    )
    with store() as unit:
        unit.classifications.save(triaged)
        with pytest.raises(KeyError, match="no such document"):
            unit.classifications.add(
                Classification.triaged(
                    record(b"never stored").document_id,
                    relevance=Relevance.IRRELEVANT,
                    doc_type=DocumentType.CIRCULAR,
                    by=None,
                    task_id=task.id,
                    at=NOW,
                    reason="A portal manual",
                )
            )
    assert store.classifications[stored.document_id] == triaged


def test_an_extraction_is_kept_as_written_and_a_parse_keeps_a_later_status() -> None:
    store = MemoryStore()
    stored = record(b"%PDF-1.7 extracted")
    prompt = "extraction.rule_candidate@1"
    extraction = RuleExtraction(
        document_id=stored.document_id,
        prompt_version=prompt,
        candidate_id=candidate_id_for(stored.document_id, prompt),
        outcome=ExtractionOutcome.UNPARSEABLE,
        model="fake/echo",
        attempts=2,
        source_key=DEFINITION.key,
        doc_type=DocumentType.NOTIFICATION,
        regulator="CBIC",
        issues=(Issue("output_unparseable", "not JSON"),),
        citation_count=0,
        confidence=0.0,
        needs_review=True,
        answer="not json",
        ontology_version="0.2.0",
        extracted_at=NOW,
    )
    with store() as unit:
        unit.sources.add(Source.of(DEFINITION, NOW))
        unit.documents.add(stored)
        assert unit.extractions.add(extraction)
        assert not unit.extractions.add(extraction)
        assert unit.documents.record_parse(stored.document_id, "pdf@1")
        assert unit.documents.set_status(stored.document_id, DocumentStatus.EXTRACTED)
    with store() as unit:
        assert unit.extractions.get(stored.document_id, prompt) == extraction
        assert not unit.documents.record_parse(stored.document_id, "pdf@1")
        again = unit.documents.get(stored.document_id)
    assert again is not None
    assert again.status is DocumentStatus.EXTRACTED
