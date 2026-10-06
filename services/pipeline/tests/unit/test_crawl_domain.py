"""The crawl's rules in the domain: where a listing starts, how the watermark moves, how a run
ends, when a source is due and under which ids, and how a source stands."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest

from domain_kernel.errors import InvariantViolationError
from pipeline.domain.crawl import (
    LOOKBACK,
    MAX_SUMMARY_FAILURES,
    OVERLAP,
    CrawlCounts,
    CrawlRun,
    CrawlStatus,
    CrawlTrigger,
    DocumentOutcome,
    Outcome,
    failure_summary,
    listing_since,
    next_watermark,
    tally,
)
from pipeline.domain.schedule import (
    ABANDONED_AFTER,
    FreshnessState,
    SourceStatus,
    freshness_of,
    ingest_workflow_id,
    is_abandoned,
    is_due,
    is_running,
    manual_workflow_id,
    run_id_for,
    scheduled_workflow_id,
    slot_start,
    staleness_age,
    status_of,
)
from pipeline.domain.sources import (
    MAX_CADENCE,
    Source,
    source_id_of,
    watermark_date,
    watermark_of,
)
from pipeline.infrastructure.adapters import source_id_for

NOW = datetime(2026, 10, 6, 6, 0, tzinfo=UTC)
TODAY = date(2026, 10, 6)


def source(**overrides: object) -> Source:
    values: dict[str, object] = {
        "key": "cbic_notifications",
        "adapter_type": "cbic",
        "parameters": {"listing": "notifications", "category": "Central Tax"},
        "cadence": timedelta(hours=2),
        "created_at": NOW - timedelta(days=10),
        "updated_at": NOW - timedelta(days=10),
        "name": "CBIC Central Tax notifications",
    }
    values.update(overrides)
    return Source(**values)  # type: ignore[arg-type]


def outcome(day: int | None, kind: Outcome, url: str | None = None) -> DocumentOutcome:
    published = None if day is None else date(2026, 9, day)
    return DocumentOutcome(url or f"https://example.invalid/{day}-{kind}", kind, published)


# ---------------------------------------------------------------- listing and watermark


def test_a_first_crawl_lists_the_last_thirty_days_and_later_ones_a_week_back() -> None:
    assert listing_since(None, TODAY) == TODAY - LOOKBACK
    assert listing_since(date(2026, 9, 30), TODAY) == date(2026, 9, 23)
    assert listing_since(date(2027, 1, 1), TODAY) == TODAY - OVERLAP, "never after today"


def test_the_watermark_moves_to_the_newest_document_kept() -> None:
    found = [
        outcome(10, Outcome.STORED),
        outcome(20, Outcome.DUPLICATE),
        outcome(None, Outcome.STORED),
    ]
    assert next_watermark(None, found) == date(2026, 9, 20)
    assert next_watermark(date(2026, 9, 25), found) == date(2026, 9, 25), "never back unless held"
    assert next_watermark(date(2026, 9, 1), [], known_newest=date(2026, 9, 12)) == date(2026, 9, 12)


def test_the_watermark_stays_short_of_a_document_that_is_not_stored() -> None:
    found = [outcome(20, Outcome.STORED), outcome(12, Outcome.FAILED), outcome(25, Outcome.STORED)]
    assert next_watermark(date(2026, 9, 1), found) == date(2026, 9, 12)
    deferred = [outcome(20, Outcome.STORED), outcome(15, Outcome.DEFERRED)]
    assert next_watermark(None, deferred) == date(2026, 9, 15)
    capped = [outcome(28, Outcome.STORED)]
    assert next_watermark(None, capped, deferred_oldest=date(2026, 9, 3)) == date(2026, 9, 3)
    assert next_watermark(date(2026, 9, 20), [outcome(5, Outcome.FAILED)]) == date(2026, 9, 5)


def test_undated_documents_never_hold_the_watermark_and_nothing_dated_keeps_it() -> None:
    assert next_watermark(date(2026, 9, 1), [outcome(None, Outcome.FAILED)]) == date(2026, 9, 1)
    assert next_watermark(None, []) is None


def test_the_counts_and_the_source_error_of_a_crawl() -> None:
    found = [
        outcome(1, Outcome.STORED),
        outcome(2, Outcome.DUPLICATE),
        outcome(3, Outcome.FAILED),
        outcome(4, Outcome.DEFERRED),
    ]
    assert tally(9, found) == CrawlCounts(listed=9, stored=1, duplicates=1, failed=1)
    assert failure_summary([outcome(1, Outcome.STORED)]) == ""
    failed = [
        DocumentOutcome(f"https://example.invalid/{n}", Outcome.FAILED, error=f"boom {n}")
        for n in range(5)
    ]
    summary = failure_summary(failed)
    assert summary.startswith("5 of 5 new documents failed: https://example.invalid/0: boom 0")
    assert summary.endswith(f"; and {5 - MAX_SUMMARY_FAILURES} more")
    one = failure_summary([DocumentOutcome("https://example.invalid/x", Outcome.FAILED)])
    assert one == "1 of 1 new document failed: https://example.invalid/x: no error given"


def test_an_outcome_needs_a_url() -> None:
    with pytest.raises(InvariantViolationError):
        DocumentOutcome(" ", Outcome.STORED)


def test_a_run_left_running_is_closed_as_abandoned() -> None:
    run = CrawlRun.start("cbic_notifications", NOW)
    assert is_running(run, NOW + timedelta(hours=1))
    late = NOW + ABANDONED_AFTER
    assert is_abandoned(run, late)
    assert not is_running(run, late)
    closed = run.abandon(late, ABANDONED_AFTER)
    assert (closed.status, closed.finished_at) == (CrawlStatus.FAILED, late)
    assert closed.error == "abandoned: the crawl did not finish within 3 h of its start"
    assert not is_abandoned(closed, late + timedelta(days=1))


def test_a_watermark_is_stored_as_its_date() -> None:
    assert watermark_of(date(2026, 9, 19)) == {"published_on": "2026-09-19"}
    assert watermark_of(None) is None
    assert watermark_date({"published_on": "2026-09-19"}) == date(2026, 9, 19)
    assert watermark_date({"published_on": "19/09/2026"}) is None
    assert watermark_date({"page": 3}) is None
    assert watermark_date(None) is None


# ---------------------------------------------------------------- the schedule


def test_a_slot_is_a_cadence_long_and_names_the_scheduled_workflow() -> None:
    cadence = timedelta(hours=2)
    assert slot_start(NOW, cadence) == datetime(2026, 10, 6, 6, 0, tzinfo=UTC)
    first = scheduled_workflow_id("cbic_notifications", NOW, cadence)
    assert first == "pipeline-crawl-cbic_notifications-20261006T060000Z"
    assert (
        scheduled_workflow_id("cbic_notifications", NOW + timedelta(minutes=119), cadence) == first
    )
    assert scheduled_workflow_id("cbic_notifications", NOW + timedelta(hours=2), cadence) != first
    with pytest.raises(ValueError, match="at least a second"):
        slot_start(NOW, timedelta(0))


def test_run_ids_follow_from_workflow_ids() -> None:
    manual = manual_workflow_id("gstn_advisories", UUID(int=5))
    assert manual == f"pipeline-crawl-gstn_advisories-manual-{UUID(int=5).hex}"
    assert run_id_for(manual) == run_id_for(manual)
    assert run_id_for(manual) != run_id_for(manual + "x")
    url = "https://taxinformation.cbic.gov.in/content/pdf/x.pdf"
    child = ingest_workflow_id("cbic_notifications", url)
    prefix = "pipeline-ingest-cbic_notifications-"
    assert child.startswith(prefix)
    assert len(child) == len(prefix) + 24
    assert child == ingest_workflow_id("cbic_notifications", url)


def test_the_source_id_is_the_registrys() -> None:
    assert source_id_of("cbic_notifications") == source_id_for("cbic_notifications")


def due(
    found: Source,
    latest: CrawlRun | None,
    now: datetime,
    *,
    listable: bool = True,
    last_crawl: CrawlRun | None = None,
) -> bool:
    """``is_due`` with the latest run as the last crawl too, unless the test names another."""
    crawl = latest if last_crawl is None and latest is not None else last_crawl
    return is_due(found, latest, now, listable=listable, last_crawl=crawl)


def test_a_source_is_due_once_its_cadence_has_passed_since_its_last_crawl() -> None:
    fresh = source()
    assert due(fresh, None, NOW), "never crawled"
    ran = CrawlRun.start(fresh.key, NOW - timedelta(minutes=30)).finish(
        NOW - timedelta(minutes=29), CrawlCounts()
    )
    assert not due(fresh, ran, NOW)
    assert due(fresh, ran, NOW + timedelta(minutes=90))
    listed = source(last_fetch_at=NOW - timedelta(hours=1))
    assert not due(listed, None, NOW)
    assert due(listed, None, NOW + timedelta(hours=1))


def test_a_backfill_holds_the_tick_back_while_it_runs_and_counts_as_no_crawl() -> None:
    """The cadence counts from the schedule's crawl an hour and a half ago, not from the
    backfill that ended a minute ago; a backfill that runs holds the tick back all the same."""
    crawled = source(last_fetch_at=NOW - timedelta(minutes=85))
    scheduled = CrawlRun.start(crawled.key, NOW - timedelta(minutes=90)).finish(
        NOW - timedelta(minutes=85), CrawlCounts()
    )
    backfill = replace(
        CrawlRun.start(crawled.key, NOW - timedelta(minutes=20)), trigger=CrawlTrigger.BACKFILL
    )
    assert not is_due(crawled, backfill, NOW, listable=True, last_crawl=scheduled), "it runs"
    ended = backfill.finish(NOW - timedelta(minutes=1), CrawlCounts(listed=40, stored=40))
    assert not is_due(crawled, ended, NOW, listable=True, last_crawl=scheduled)
    later = NOW + timedelta(minutes=30)
    assert is_due(crawled, ended, later, listable=True, last_crawl=scheduled), (
        "two hours since the schedule's crawl, though the backfill ended 31 minutes ago"
    )
    assert is_due(source(), ended, NOW, listable=True, last_crawl=None), (
        "a source only a backfill crawled was never crawled by the schedule"
    )


def test_a_paused_or_disabled_source_or_one_being_crawled_is_not_due() -> None:
    assert not due(source(paused=True), None, NOW)
    assert not due(source(enabled=False), None, NOW)
    running = CrawlRun.start("cbic_notifications", NOW - timedelta(hours=2, minutes=30))
    assert not due(source(), running, NOW)
    assert due(source(), running, running.started_at + ABANDONED_AFTER)


def test_an_upload_only_source_is_never_due() -> None:
    assert not due(source(), None, NOW, listable=False), "never crawled, and never will be"
    assert not due(source(), None, NOW + timedelta(days=400), listable=False)


def test_how_a_source_stands() -> None:
    running = CrawlRun.start("cbic_notifications", NOW)
    assert status_of(source(), running, NOW) is SourceStatus.FETCHING
    assert status_of(source(paused=True), running, NOW) is SourceStatus.FETCHING
    assert status_of(source(paused=True), None, NOW) is SourceStatus.PAUSED
    assert status_of(source(enabled=False), None, NOW) is SourceStatus.PAUSED
    assert status_of(source(last_error="503 from the site"), None, NOW) is SourceStatus.FAILING
    assert status_of(source(), None, NOW) is SourceStatus.HEALTHY


@pytest.mark.parametrize(
    ("age", "state"),
    [
        (timedelta(0), FreshnessState.FRESH),
        (timedelta(hours=2), FreshnessState.FRESH),
        (timedelta(hours=2, seconds=1), FreshnessState.LATE),
        (timedelta(hours=4), FreshnessState.LATE),
        (timedelta(hours=4, seconds=1), FreshnessState.STALE),
    ],
)
def test_freshness_is_the_age_against_the_cadence(age: timedelta, state: FreshnessState) -> None:
    found = freshness_of(source(last_fetch_at=NOW - age), NOW)
    assert (found.state, found.age, found.cadence) == (state, age, timedelta(hours=2))
    assert found.cadences == age / timedelta(hours=2)


def test_a_source_never_listed_has_no_age_but_goes_stale_from_when_it_was_added() -> None:
    never = freshness_of(source(), NOW)
    assert (never.state, never.age, never.cadences) == (FreshnessState.NEVER, None, None)
    assert staleness_age(source(), NOW) == timedelta(days=10)
    assert staleness_age(source(last_fetch_at=NOW - timedelta(hours=1)), NOW) == timedelta(hours=1)


def test_an_edit_keeps_what_it_does_not_change_and_a_crawl_records_its_end() -> None:
    before = source()
    edited = before.edited(NOW, cadence=timedelta(hours=1), paused=True)
    assert (edited.cadence, edited.paused, edited.enabled, edited.name) == (
        timedelta(hours=1),
        True,
        True,
        before.name,
    )
    assert edited.updated_at == NOW
    with pytest.raises(InvariantViolationError, match="at most"):
        before.edited(NOW, cadence=MAX_CADENCE + timedelta(seconds=1))
    with pytest.raises(InvariantViolationError, match="name"):
        before.edited(NOW, name=" padded ")
    listed = before.crawled(NOW, listed=True, watermark=date(2026, 9, 30), error="")
    assert (listed.last_fetch_at, listed.watermark_date, listed.last_error) == (
        NOW,
        date(2026, 9, 30),
        "",
    )
    failed = listed.crawled(NOW + timedelta(hours=2), listed=False, watermark=None, error="boom")
    assert (failed.last_fetch_at, failed.watermark_date, failed.last_error) == (
        NOW,
        date(2026, 9, 30),
        "boom",
    )
    assert source(name="").label == "cbic_notifications"
