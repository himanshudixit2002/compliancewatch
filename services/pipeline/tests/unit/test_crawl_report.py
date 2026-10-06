"""The crawl report and its F1 check: runs and failures per source, the longest gap between
successful listings, the detection delay of dated documents, the command's output and exit."""

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from domain_kernel.documents import document_id_for
from pipeline import crawl_report
from pipeline.application.report import CrawlReport, detection_delay, longest_gap
from pipeline.application.sources import SyncSources
from pipeline.domain.crawl import CrawlCounts, CrawlRun, CrawlTrigger
from pipeline.domain.raw_documents import RawDocumentRecord
from pipeline.infrastructure.adapters import SOURCES
from pipeline.infrastructure.memory import MemoryStore
from pipeline.infrastructure.raw_store import storage_key_for

NOW = datetime(2026, 10, 6, 6, 0, tzinfo=UTC)
START = NOW - timedelta(days=2)


def synced() -> MemoryStore:
    store = MemoryStore()
    SyncSources(store, [s.definition() for s in SOURCES.values()], clock=lambda: START).run()
    return store


def crawled(store: MemoryStore, key: str, at: datetime, *, error: str = "", **counts: int) -> None:
    run = CrawlRun.start(key, at).finish(
        at + timedelta(minutes=2), CrawlCounts(**counts), error=error
    )
    with store() as unit:
        unit.crawl_runs.add(run)


def kept(store: MemoryStore, key: str, published: date | None, fetched: datetime) -> None:
    content = f"{key}{published}{fetched}".encode()
    digest = hashlib.sha256(content).hexdigest()
    with store() as unit:
        unit.documents.add(
            RawDocumentRecord(
                document_id=document_id_for(digest),
                source_key=key,
                source_url=f"https://example.invalid/{digest[:8]}",
                fetched_at=fetched,
                content_type="application/pdf",
                size=len(content),
                sha256=digest,
                storage_key=storage_key_for(digest),
                published_on=published,
            )
        )


def every(hours: float) -> list[datetime]:
    moments, at = [], START
    while at < NOW:
        moments.append(at)
        at += timedelta(hours=hours)
    return moments


def test_the_longest_gap_counts_from_the_start_of_the_window_to_now() -> None:
    assert longest_gap([], START, NOW) == timedelta(days=2)
    listings = [START + timedelta(hours=1), START + timedelta(hours=8), NOW - timedelta(hours=2)]
    assert longest_gap(listings, START, NOW) == NOW - timedelta(hours=2) - (
        START + timedelta(hours=8)
    )


def test_the_detection_delay_runs_from_the_start_of_the_publication_day_in_india() -> None:
    record = RawDocumentRecord(
        document_id=document_id_for("a" * 64),
        source_key="cbic_notifications",
        source_url="https://example.invalid/a",
        fetched_at=datetime(2026, 4, 21, 0, 30, tzinfo=UTC),
        content_type="application/pdf",
        size=1,
        sha256="a" * 64,
        storage_key=storage_key_for("a" * 64),
        published_on=date(2026, 4, 21),
    )
    assert detection_delay(record) == timedelta(hours=6)
    assert detection_delay(replace(record, published_on=None)) is None
    early = replace(record, fetched_at=datetime(2026, 4, 20, 12, 0, tzinfo=UTC))
    assert detection_delay(early) == timedelta(0), "listed before its date: no delay"


def test_a_source_listed_every_two_hours_meets_f1_and_a_late_one_does_not() -> None:
    store = synced()
    for at in every(2):
        crawled(store, "cbic_notifications", at, listed=3, stored=1)
    for at in every(2)[:10]:
        crawled(store, "gstn_advisories", at, listed=1)
    crawled(store, "gstn_advisories", NOW - timedelta(hours=1), error="503 from the site")
    kept(store, "cbic_notifications", date(2026, 10, 5), datetime(2026, 10, 4, 23, 30, tzinfo=UTC))
    kept(store, "cbic_notifications", date(2026, 10, 5), datetime(2026, 10, 5, 9, 0, tzinfo=UTC))
    kept(store, "cbic_notifications", None, NOW - timedelta(hours=3))
    result = CrawlReport(store, clock=lambda: NOW).run(days=2)
    cbic = result.source("cbic_notifications")
    assert cbic is not None
    assert (cbic.runs, cbic.completed, cbic.failed_runs, cbic.stored) == (24, 24, 0, 24)
    assert cbic.longest_gap <= timedelta(hours=2, minutes=2)
    assert cbic.meets(result.target)
    assert cbic.detection is not None
    assert (cbic.detection.documents, cbic.detection.within_target) == (2, 1)
    assert cbic.detection.longest == timedelta(hours=14, minutes=30)
    gstn = result.source("gstn_advisories")
    assert gstn is not None
    assert (gstn.runs, gstn.failed_runs) == (11, 1)
    assert gstn.longest_gap > timedelta(hours=6)
    assert not gstn.meets(result.target)
    assert result.source("nowhere") is None
    with pytest.raises(ValueError, match="at least one day"):
        CrawlReport(store).run(days=0)


def backfilled(store: MemoryStore, key: str, at: datetime, **counts: int) -> CrawlRun:
    run = replace(CrawlRun.start(key, at), trigger=CrawlTrigger.BACKFILL).finish(
        at + timedelta(hours=1), CrawlCounts(**counts)
    )
    with store() as unit:
        unit.crawl_runs.add(run)
    return run


def test_a_backfill_is_none_of_the_crawls_the_report_counts() -> None:
    """A backfill's runs close no gap and count in no total, and neither the documents it
    fetched nor the ones published before the window count in the detection delay."""
    store = synced()
    for at in every(2):
        crawled(store, "cbic_notifications", at, listed=3, stored=1)
    run = backfilled(store, "cbic_notifications", NOW - timedelta(hours=5), listed=60, stored=40)
    backfilled(store, "gstn_advisories", NOW - timedelta(hours=30), listed=9, stored=9)
    during = run.started_at + timedelta(minutes=20)
    kept(store, "cbic_notifications", date(2026, 10, 5), during)
    kept(store, "cbic_notifications", date(2020, 11, 10), NOW - timedelta(hours=3))
    # Published the day before the window opened in India: it was not new in the window.
    kept(store, "cbic_notifications", date(2026, 10, 3), NOW - timedelta(hours=3))
    kept(store, "cbic_notifications", date(2026, 10, 5), datetime(2026, 10, 5, 3, 0, tzinfo=UTC))
    result = CrawlReport(store, clock=lambda: NOW).run(days=2)
    cbic = result.source("cbic_notifications")
    assert cbic is not None
    assert (cbic.runs, cbic.completed, cbic.stored) == (24, 24, 24), "no backfill counted"
    assert cbic.detection is not None
    assert (cbic.detection.documents, cbic.detection.longest) == (1, timedelta(hours=8, minutes=30))
    gstn = result.source("gstn_advisories")
    assert gstn is not None
    assert (gstn.runs, gstn.completed, gstn.last_listing) == (0, 0, None)
    assert gstn.longest_gap == timedelta(days=2), "a backfill closes no gap"
    assert not gstn.meets(result.target)


def test_the_command_prints_the_table_and_exits_by_f1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store = synced()
    for at in every(2):
        crawled(store, "cbic_notifications", at, listed=2, stored=1)
    monkeypatch.setattr(crawl_report, "unit_of_work_of", lambda settings: store)
    monkeypatch.setattr(
        crawl_report, "CrawlReport", lambda units: CrawlReport(units, clock=lambda: NOW)
    )
    monkeypatch.setenv("CW_PIPELINE_STORE", "memory")
    assert crawl_report.main(["--days", "2"]) == 0
    out = capsys.readouterr().out
    assert "| cbic_notifications | 24 | 24 | 0 | 24 | 0 |" in out
    assert out.rstrip().endswith("against 6.0 h)")
    assert "F1 cbic_notifications: met" in out
    assert crawl_report.main(["--days", "2", "--f1-source", "gstn_advisories"]) == 1
    assert "F1 gstn_advisories: not met" in capsys.readouterr().out
    assert crawl_report.main(["--days", "2", "--json", "--source", "cbic_notifications"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [s["key"] for s in payload["sources"]] == ["cbic_notifications"]
    assert payload["f1"] == {"source": "cbic_notifications", "met": True}
    assert crawl_report.main(["--f1-source", "nowhere"]) == 1
    assert "F1 nowhere: not met (no such source)" in capsys.readouterr().out


def test_the_command_says_when_it_cannot_read_the_store(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class Away:
        def __call__(self) -> object:
            raise ConnectionError("the database is away")

    monkeypatch.setattr(crawl_report, "unit_of_work_of", lambda settings: Away())
    monkeypatch.setenv("CW_PIPELINE_STORE", "memory")
    assert crawl_report.main([]) == 2
    assert "cannot read the store: ConnectionError" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        crawl_report.main(["--days", "0"])
