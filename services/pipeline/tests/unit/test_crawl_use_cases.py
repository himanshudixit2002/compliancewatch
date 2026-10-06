"""The crawl's use cases on the memory store: an admin's fetch, the tick, the listing activity
over recorded notifications, and the bookkeeping at the end of a crawl."""

import hashlib
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest

from domain_kernel.audit import AuditActor
from domain_kernel.documents import document_id_for
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import UserId
from pipeline.application.activities import Discovered
from pipeline.application.crawl import (
    ChildOutcome,
    CrawlRequest,
    FetchRequest,
    FinishCrawl,
    FinishRequest,
    ListNewDocuments,
    ListRequest,
    ScheduleCrawls,
    StartCrawl,
    launch,
)
from pipeline.application.sources import FETCH_ACTION, SyncSources
from pipeline.domain.crawl import CrawlCounts, CrawlRun, CrawlRunId, CrawlStatus, Outcome
from pipeline.domain.errors import (
    CrawlDisabledError,
    CrawlRunningError,
    CrawlUnavailableError,
    SourceNotFoundError,
)
from pipeline.domain.ports import CrawlStart
from pipeline.domain.raw_documents import RawDocumentRecord
from pipeline.domain.schedule import (
    ABANDONED_AFTER,
    CrawlTrigger,
    run_id_for,
    scheduled_workflow_id,
)
from pipeline.domain.sources import Source, watermark_of
from pipeline.infrastructure.adapters import SOURCES, StoreCatalog
from pipeline.infrastructure.memory import MemoryStore
from pipeline.infrastructure.raw_store import storage_key_for
from pipeline.testing import MemoryCrawls, recorded_client, recorded_types

NOW = datetime(2026, 10, 6, 6, 0, tzinfo=UTC)
ACTOR = AuditActor.user(UserId(UUID(int=7)))
REASON = "Fetch it now for the test"
RECORDED = "recorded_cbic"
NUMBERS = ["01/2026-Central Tax", "17/2025-Central Tax", "15/2025-Central Tax"]
CBIC_PDF = "https://taxinformation.cbic.gov.in/content/pdf/tax_repository/gst/notifications/"


class Clock:
    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def synced(clock: Clock | None = None) -> MemoryStore:
    store = MemoryStore()
    SyncSources(store, [s.definition() for s in SOURCES.values()], clock=clock or Clock()).run()
    return store


def with_recorded(store: MemoryStore, watermark: date | None = None) -> MemoryStore:
    with store() as unit:
        unit.sources.add(
            Source(
                key=RECORDED,
                adapter_type="recorded",
                parameters={"numbers": NUMBERS},
                cadence=timedelta(hours=2),
                created_at=NOW,
                updated_at=NOW,
                watermark=watermark_of(watermark),
                name="Recorded CBIC notifications",
            )
        )
    return store


def fetch(store: MemoryStore, starter: MemoryCrawls, **overrides: object) -> CrawlStart:
    values: dict[str, object] = {"enabled": True, "clock": Clock()}
    values.update(overrides)
    start = StartCrawl(store, starter, **values)  # type: ignore[arg-type]
    return start.run(FetchRequest("gstn_advisories", ACTOR, REASON, "c0ffee"))


# ---------------------------------------------------------------- an admin's fetch


def test_a_fetch_records_the_run_audits_it_and_starts_its_workflow() -> None:
    store, starter = synced(), MemoryCrawls()
    start = fetch(store, starter, request_ids=lambda: UUID(int=9))
    assert start.workflow_id == f"pipeline-crawl-gstn_advisories-manual-{UUID(int=9).hex}"
    assert (start.run_id, start.trigger) == (run_id_for(start.workflow_id), CrawlTrigger.MANUAL)
    assert starter.started == [start]
    run = store.crawl_runs[start.run_id]
    assert (run.status, run.started_at, run.source_key) == (
        CrawlStatus.RUNNING,
        NOW,
        "gstn_advisories",
    )
    (entry,) = store.audit
    assert (entry.action, entry.subject_id, entry.actor, entry.reason) == (
        FETCH_ACTION,
        "gstn_advisories",
        ACTOR,
        REASON,
    )
    assert entry.after == {"run_id": str(start.run_id), "workflow_id": start.workflow_id}
    assert (entry.tenant_id, entry.correlation_id) == (None, "c0ffee")


def test_a_fetch_is_refused_while_crawling_is_off_or_a_crawl_runs() -> None:
    store, starter = synced(), MemoryCrawls()
    with pytest.raises(CrawlDisabledError):
        fetch(store, starter, enabled=False)
    fetch(store, starter)
    with pytest.raises(CrawlRunningError, match="runs since"):
        fetch(store, starter)
    assert len(starter.started) == 1
    assert len(store.audit) == 1
    with pytest.raises(SourceNotFoundError):
        StartCrawl(store, starter, enabled=True).run(FetchRequest("nowhere", ACTOR, REASON))
    with pytest.raises(InvariantViolationError, match="reason"):
        StartCrawl(store, starter, enabled=True).run(FetchRequest("gstn_advisories", ACTOR, "x"))


def test_a_run_whose_workflow_was_lost_is_closed_and_a_new_one_starts() -> None:
    store, starter = synced(), MemoryCrawls()
    first = fetch(store, starter)
    later = Clock(NOW + ABANDONED_AFTER)
    second = fetch(store, starter, clock=later)
    abandoned = store.crawl_runs[first.run_id]
    assert abandoned.status is CrawlStatus.FAILED
    assert abandoned.error.startswith("abandoned: the crawl did not finish within 3 h")
    assert store.crawl_runs[second.run_id].status is CrawlStatus.RUNNING


def test_a_start_temporal_refuses_closes_the_run_with_why() -> None:
    store = synced()
    starter = MemoryCrawls(fail=ConnectionError("temporal:7233 refused the connection"))
    with pytest.raises(CrawlUnavailableError, match="refused the connection"):
        fetch(store, starter)
    (run,) = store.crawl_runs.values()
    assert run.status is CrawlStatus.FAILED
    assert run.error.startswith("the crawl could not start: ConnectionError")
    assert len(store.audit) == 1, "the request itself stays audited"
    fetch(store, starter)


def test_a_workflow_id_taken_from_before_closes_the_run() -> None:
    store, starter = synced(), MemoryCrawls()
    start = CrawlStart(
        "pipeline-crawl-x-1", CrawlRunId.new(), "gstn_advisories", CrawlTrigger.SCHEDULE
    )
    starter.started.append(start)
    with store() as unit:
        unit.crawl_runs.add(CrawlRun(id=start.run_id, source_key="gstn_advisories", started_at=NOW))
    assert launch(store, starter, start, Clock()) is False
    assert store.crawl_runs[start.run_id].error == "a workflow pipeline-crawl-x-1 exists already"


# ---------------------------------------------------------------- the tick


def test_the_tick_starts_each_due_source_once_per_slot() -> None:
    store, starter = synced(), MemoryCrawls()
    clock = Clock()
    schedule = ScheduleCrawls(store, starter, enabled=True, clock=clock)
    report = schedule.run()
    assert sorted(report.started) == sorted(
        scheduled_workflow_id(key, NOW, spec.cadence) for key, spec in SOURCES.items()
    )
    assert schedule.run().started == (), "a double tick starts nothing twice"
    clock.now = NOW + timedelta(seconds=60)
    assert schedule.run().started == ()
    assert len(starter.started) == len(store.crawl_runs) == len(SOURCES)
    assert {start.trigger for start in starter.started} == {CrawlTrigger.SCHEDULE}


def test_two_ticks_that_both_saw_a_source_due_start_it_once() -> None:
    store, starter = synced(), MemoryCrawls()
    tick_a = ScheduleCrawls(store, starter, enabled=True, clock=Clock())
    tick_b = ScheduleCrawls(store, starter, enabled=True, clock=Clock())
    assert tick_a._start("gstn_advisories", NOW) is not None
    assert tick_b._start("gstn_advisories", NOW) is None
    assert len(starter.started) == 1


def test_a_run_recorded_under_the_slots_id_is_never_started_twice() -> None:
    store, starter = synced(), MemoryCrawls()
    workflow_id = scheduled_workflow_id("gstn_advisories", NOW, timedelta(hours=3))
    with store() as unit:
        run = CrawlRun(id=run_id_for(workflow_id), source_key="gstn_advisories", started_at=NOW)
        assert unit.crawl_runs.start(run)
        assert not unit.crawl_runs.start(run)
    finished = store.crawl_runs[run.id].finish(NOW, CrawlCounts())
    with store() as unit:
        unit.crawl_runs.save(finished)
    tick = ScheduleCrawls(store, starter, enabled=True, clock=Clock())
    assert tick._start("gstn_advisories", NOW + timedelta(hours=3)) is not None
    assert len(starter.started) == 1


def test_the_tick_skips_paused_disabled_and_recently_crawled_sources() -> None:
    store, starter = synced(), MemoryCrawls()
    with store() as unit:
        paused = unit.sources.get("cbic_notifications")
        disabled = unit.sources.get("cbic_circulars")
        assert paused is not None
        assert disabled is not None
        unit.sources.save(paused.edited(NOW, paused=True))
        unit.sources.save(disabled.edited(NOW, enabled=False))
        listed = unit.sources.get("gstn_advisories")
        assert listed is not None
        unit.sources.save(
            listed.crawled(NOW - timedelta(hours=1), listed=True, watermark=None, error="")
        )
    report = ScheduleCrawls(store, starter, enabled=True, clock=Clock()).run()
    assert sorted(start.source_key for start in starter.started) == [
        "gstcouncil_press",
        "mahagst_notifications",
    ]
    assert len(report.started) == 2


def test_the_tick_does_nothing_while_crawling_is_off() -> None:
    store, starter = synced(), MemoryCrawls()
    assert ScheduleCrawls(store, starter, enabled=False).run().started == ()
    assert starter.started == []


def test_a_source_that_fails_to_start_does_not_stop_the_others() -> None:
    store = synced()

    class Flaky(MemoryCrawls):
        def start(self, start: CrawlStart) -> bool:
            if start.source_key == "cbic_circulars":
                raise CrawlUnavailableError("temporal is away")
            return super().start(start)

    starter = Flaky()
    report = ScheduleCrawls(store, starter, enabled=True, clock=Clock()).run()
    assert report.failed == ("cbic_circulars",)
    assert len(starter.started) == len(SOURCES) - 1
    failed = [run for run in store.crawl_runs.values() if run.source_key == "cbic_circulars"]
    assert [run.status for run in failed] == [CrawlStatus.FAILED]


# ---------------------------------------------------------------- the listing


def lister(store: MemoryStore, today: datetime) -> ListNewDocuments:
    catalog = StoreCatalog(store, recorded_client(), types=recorded_types())
    return ListNewDocuments(store, catalog, knowledge=True, clock=lambda: today)


def record(url: str, content: bytes, published: date | None = None) -> RawDocumentRecord:
    digest = hashlib.sha256(content).hexdigest()
    return RawDocumentRecord(
        document_id=document_id_for(digest),
        source_key=RECORDED,
        source_url=url,
        fetched_at=NOW,
        content_type="application/pdf",
        size=len(content),
        sha256=digest,
        storage_key=storage_key_for(digest),
        published_on=published,
    )


async def test_the_listing_starts_a_week_before_the_watermark_and_skips_known_urls() -> None:
    store = with_recorded(synced(), watermark=date(2025, 9, 20))
    with store() as unit:
        unit.documents.add(
            record(CBIC_PDF + "centaltax-15-2025.pdf", b"%PDF 15", date(2025, 9, 17))
        )
    listing = await lister(store, NOW).run(ListRequest(source_key=RECORDED, run_id=UUID(int=1)))
    assert listing.since == date(2025, 9, 13)
    assert (listing.listed, listing.known) == (3, 1)
    assert [d.external_ref for d in listing.new] == ["01/2026-Central Tax", "17/2025-Central Tax"]
    assert listing.known_newest == date(2025, 9, 17)
    assert (listing.deferred, listing.deferred_oldest) == (0, None)
    assert (listing.knowledge, listing.regulator, listing.source_key) == (True, "CBIC", RECORDED)


async def test_a_capped_listing_leaves_the_oldest_for_the_next_crawl() -> None:
    store = with_recorded(synced(), watermark=date(2025, 9, 20))
    request = ListRequest(source_key=RECORDED, run_id=UUID(int=1), limit=1)
    listing = await lister(store, NOW).run(request)
    assert [d.external_ref for d in listing.new] == ["01/2026-Central Tax"]
    assert (listing.deferred, listing.deferred_oldest) == (2, date(2025, 9, 17))


async def test_a_first_listing_reads_the_last_thirty_days() -> None:
    store = with_recorded(synced())
    listing = await lister(store, datetime(2026, 5, 10, tzinfo=UTC)).run(
        ListRequest(source_key=RECORDED, run_id=UUID(int=1))
    )
    assert listing.since == date(2026, 4, 10)
    assert [d.external_ref for d in listing.new] == ["01/2026-Central Tax"]


async def test_listing_a_source_nobody_stored_fails() -> None:
    with pytest.raises(SourceNotFoundError):
        await lister(synced(), NOW).run(ListRequest(source_key="nowhere", run_id=UUID(int=1)))


def test_a_crawl_request_names_a_source_key() -> None:
    with pytest.raises(ValueError, match="source_key"):
        CrawlRequest(source_key="Not A Key", run_id=UUID(int=1))


# ---------------------------------------------------------------- the end of a crawl


def started(store: MemoryStore, key: str = RECORDED) -> CrawlRun:
    run = CrawlRun.start(key, NOW)
    with store() as unit:
        unit.crawl_runs.add(run)
    return run


def child(url: str, kind: Outcome, day: date | None, error: str = "") -> ChildOutcome:
    return ChildOutcome(url=url, published_at=day, outcome=kind, error=error)


def test_a_crawl_that_listed_records_its_counts_listing_and_watermark() -> None:
    store = with_recorded(synced(), watermark=date(2025, 9, 20))
    run = started(store)
    later = NOW + timedelta(minutes=4)
    result = FinishCrawl(store, clock=Clock(later)).finish(
        FinishRequest(
            source_key=RECORDED,
            run_id=run.id.value,
            listed=3,
            known_newest=date(2025, 9, 17),
            outcomes=[
                child("https://example.invalid/a", Outcome.STORED, date(2026, 4, 21)),
                child("https://example.invalid/b", Outcome.DUPLICATE, date(2025, 10, 18)),
            ],
        )
    )
    assert (result.status, result.stored, result.duplicates, result.failed) == (
        CrawlStatus.COMPLETED,
        1,
        1,
        0,
    )
    assert result.watermark == date(2026, 4, 21)
    finished = store.crawl_runs[run.id]
    assert (finished.finished_at, finished.counts) == (
        later,
        CrawlCounts(listed=3, stored=1, duplicates=1),
    )
    source = store.sources[RECORDED]
    assert (source.last_fetch_at, source.watermark_date, source.last_error) == (
        later,
        date(2026, 4, 21),
        "",
    )


def test_a_failed_document_holds_the_watermark_and_names_itself_on_the_source() -> None:
    store = with_recorded(synced(), watermark=date(2025, 9, 20))
    run = started(store)
    result = FinishCrawl(store, clock=Clock()).finish(
        FinishRequest(
            source_key=RECORDED,
            run_id=run.id.value,
            listed=2,
            outcomes=[
                child("https://example.invalid/a", Outcome.STORED, date(2026, 4, 21)),
                child(
                    "https://example.invalid/b",
                    Outcome.FAILED,
                    date(2025, 10, 18),
                    "FetchFailedError: GET failed after 5 tries",
                ),
            ],
        )
    )
    assert (result.status, result.failed, result.watermark) == (
        CrawlStatus.COMPLETED,
        1,
        date(2025, 10, 18),
    )
    assert result.source_error == (
        "1 of 2 new documents failed: https://example.invalid/b: FetchFailedError: GET failed "
        "after 5 tries"
    )


def test_a_failed_ingest_whose_bytes_were_stored_counts_as_stored() -> None:
    store = with_recorded(synced())
    url = CBIC_PDF + "gst-ct-17-2025.pdf"
    with store() as unit:
        unit.documents.add(record(url, b"%PDF 17", date(2025, 10, 18)))
    run = started(store)
    result = FinishCrawl(store, clock=Clock()).finish(
        FinishRequest(
            source_key=RECORDED,
            run_id=run.id.value,
            listed=2,
            outcomes=[
                child(url, Outcome.FAILED, date(2025, 10, 18), "UnparsedDocumentError: scanned"),
                child("https://example.invalid/busy", Outcome.DEFERRED, date(2025, 10, 1)),
            ],
        )
    )
    assert (result.stored, result.failed, result.duplicates) == (1, 0, 0)
    assert result.watermark == date(2025, 10, 1), "the busy one is listed again"
    assert result.source_error == ""


def test_a_listing_that_failed_records_the_error_and_keeps_the_last_listing() -> None:
    store = with_recorded(synced(), watermark=date(2025, 9, 20))
    run = started(store)
    error = "FetchFailedError: GET https://taxinformation.cbic.gov.in failed after 5 tries"
    result = FinishCrawl(store, clock=Clock()).finish(
        FinishRequest(source_key=RECORDED, run_id=run.id.value, error=error)
    )
    assert (result.status, result.error, result.source_error) == (CrawlStatus.FAILED, error, error)
    source = store.sources[RECORDED]
    assert (source.last_fetch_at, source.watermark_date) == (None, date(2025, 9, 20))


def test_a_run_closed_meanwhile_leaves_the_source_alone() -> None:
    store = with_recorded(synced())
    run = started(store)
    with store() as unit:
        unit.crawl_runs.save(run.abandon(NOW + ABANDONED_AFTER, ABANDONED_AFTER))
    result = FinishCrawl(store, clock=Clock()).finish(
        FinishRequest(source_key=RECORDED, run_id=run.id.value, listed=1)
    )
    assert result.status is CrawlStatus.FAILED
    assert store.sources[RECORDED].last_fetch_at is None


def test_a_crawl_started_outside_the_schedule_gets_its_run_recorded() -> None:
    store = with_recorded(synced())
    run_id = CrawlRunId.new()
    result = FinishCrawl(store, clock=Clock()).finish(
        FinishRequest(source_key=RECORDED, run_id=run_id.value, listed=0)
    )
    assert result.status is CrawlStatus.COMPLETED
    assert store.crawl_runs[run_id].status is CrawlStatus.COMPLETED
    with pytest.raises(SourceNotFoundError):
        FinishCrawl(store).finish(FinishRequest(source_key="nowhere", run_id=run_id.value))


async def test_the_activity_runs_the_bookkeeping_on_a_thread() -> None:
    store = with_recorded(synced())
    run = started(store)
    result = await FinishCrawl(store, clock=Clock()).run(
        FinishRequest(
            source_key=RECORDED,
            run_id=run.id.value,
            listed=1,
            outcomes=[child("https://example.invalid/a", Outcome.STORED, None)],
        )
    )
    assert (result.status, result.stored, result.watermark) == (CrawlStatus.COMPLETED, 1, None)


def test_a_listed_document_crosses_the_wire_as_discovered() -> None:
    document = Discovered(source_id=UUID(int=1), url="https://example.invalid/x")
    assert document.published_at is None
