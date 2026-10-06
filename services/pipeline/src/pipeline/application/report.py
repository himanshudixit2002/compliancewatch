"""How the crawl did over a window of days, per source: the F1 check of the plan, that every new
CBIC notification is detected within 6 hours over 30 days.

For each source the report counts the crawl runs started in the window (completed and failed)
and the documents they stored or failed to, and finds the longest gap between successful
listings, counting from the window's start and up to now: a crawl that lists the source at
least every ``target`` sees every document the site lists within ``target`` of its listing, so
the longest gap is the detection bound. Where documents carry a publication date it also gives
the detection delay, from the start of the publication day in India to the first fetch: an upper
bound, since regulators date their documents and not the hour.

``F1`` is met for a source when it was listed successfully all through the window with no gap
above ``target`` and its last crawl recorded no error.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from itertools import pairwise
from statistics import median
from typing import Final

from domain_kernel.events import utc_now
from pipeline.domain.crawl import CrawlRun, CrawlStatus
from pipeline.domain.raw_documents import RawDocumentRecord
from pipeline.domain.repository import UnitOfWorkFactory
from pipeline.domain.schedule import INDIA
from pipeline.domain.sources import Source

DEFAULT_TARGET: Final = timedelta(hours=6)
DEFAULT_DAYS: Final = 30


@dataclass(frozen=True, slots=True)
class Detection:
    """The detection delays of the documents first fetched in the window with a date."""

    documents: int
    within_target: int
    longest: timedelta
    median: timedelta


@dataclass(frozen=True, slots=True)
class SourceReport:
    key: str
    name: str
    enabled: bool
    paused: bool
    runs: int
    completed: int
    failed_runs: int
    stored: int
    duplicates: int
    failed_documents: int
    first_listing: datetime | None
    last_listing: datetime | None
    longest_gap: timedelta
    last_error: str
    detection: Detection | None

    def meets(self, target: timedelta) -> bool:
        """F1 for this source: listed all through the window, every gap within ``target``, and
        nothing failing now."""
        return self.completed > 0 and self.longest_gap <= target and not self.last_error


@dataclass(frozen=True, slots=True)
class CrawlReportResult:
    since: datetime
    until: datetime
    target: timedelta
    sources: tuple[SourceReport, ...]

    def source(self, key: str) -> SourceReport | None:
        return next((report for report in self.sources if report.key == key), None)


def detection_delay(record: RawDocumentRecord) -> timedelta | None:
    """From the start of the publication day in India to the first fetch; None undated."""
    if record.published_on is None:
        return None
    published = datetime.combine(record.published_on, time(0), tzinfo=INDIA)
    return max(record.fetched_at - published, timedelta(0))


def longest_gap(listings: Sequence[datetime], since: datetime, until: datetime) -> timedelta:
    """The longest time without a successful listing between ``since`` and ``until``."""
    moments = [since, *sorted(moment for moment in listings if since <= moment <= until), until]
    return max(later - earlier for earlier, later in pairwise(moments))


def _detection(records: Sequence[RawDocumentRecord], target: timedelta) -> Detection | None:
    delays = [delay for delay in map(detection_delay, records) if delay is not None]
    if not delays:
        return None
    return Detection(
        documents=len(delays),
        within_target=sum(delay <= target for delay in delays),
        longest=max(delays),
        median=timedelta(seconds=median(delay.total_seconds() for delay in delays)),
    )


def _source_report(
    source: Source,
    runs: Sequence[CrawlRun],
    records: Sequence[RawDocumentRecord],
    *,
    since: datetime,
    until: datetime,
    target: timedelta,
) -> SourceReport:
    completed = [run for run in runs if run.status is CrawlStatus.COMPLETED]
    listings = [run.finished_at for run in completed if run.finished_at is not None]
    return SourceReport(
        key=source.key,
        name=source.label,
        enabled=source.enabled,
        paused=source.paused,
        runs=len(runs),
        completed=len(completed),
        failed_runs=sum(run.status is CrawlStatus.FAILED for run in runs),
        stored=sum(run.counts.stored for run in runs),
        duplicates=sum(run.counts.duplicates for run in runs),
        failed_documents=sum(run.counts.failed for run in runs),
        first_listing=min(listings, default=None),
        last_listing=max(listings, default=None),
        longest_gap=longest_gap(listings, since, until),
        last_error=source.last_error,
        detection=_detection(records, target),
    )


class CrawlReport:
    def __init__(
        self, units: UnitOfWorkFactory, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._units = units
        self._clock = clock

    def run(
        self,
        *,
        days: int = DEFAULT_DAYS,
        target: timedelta = DEFAULT_TARGET,
        keys: Sequence[str] = (),
    ) -> CrawlReportResult:
        if days < 1:
            raise ValueError("a report covers at least one day")
        until = self._clock()
        since = until - timedelta(days=days)
        with self._units() as unit:
            sources = [s for s in unit.sources.list() if not keys or s.key in keys]
            runs = unit.crawl_runs.started_since(since)
            records = unit.documents.fetched_since(since)
        return CrawlReportResult(
            since=since,
            until=until,
            target=target,
            sources=tuple(
                _source_report(
                    source,
                    [run for run in runs if run.source_key == source.key],
                    [record for record in records if record.source_key == source.key],
                    since=since,
                    until=until,
                    target=target,
                )
                for source in sources
            ),
        )
