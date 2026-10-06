"""One crawl of one source (the ``crawl_run`` table): when it ran, what it found, how it ended,
and how far it moves the source's watermark.

A run starts ``running`` and finishes ``completed``, or ``failed`` with the error. Its counts
are what the listing returned (``listed``), the documents stored for the first time
(``stored``), the ones fetched again with bytes already stored (``duplicates``) and the ones that
could not be fetched or stored (``failed``). A document whose URL is stored already is listed and
not fetched, so it counts in ``listed`` alone.

A crawl lists the source since a week before its watermark (``listing_since``; the last 30 days
for a source without one), skips the URLs it has stored, and ingests at most
``MAX_NEW_PER_CRAWL`` of the rest, newest first. The watermark then moves to the newest
publication date stored, never past a document that was listed and not stored (one that failed,
one beyond the cap, one another crawl is ingesting), so the next crawl lists it again
(``next_watermark``). Undated documents are listed by every crawl and never hold it back.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Final, Self

from domain_kernel._validation import require_aware, require_instance, require_int, require_text
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import EntityId
from pipeline.domain.sources import MAX_ERROR_CHARS, require_source_key

COUNTS: Final = ("listed", "stored", "duplicates", "failed")
LOOKBACK: Final = timedelta(days=30)
"""How far back the first crawl of a source lists."""
OVERLAP: Final = timedelta(days=7)
"""How far before its watermark every later crawl lists again: a document the site lists late,
dated before the watermark, is still found."""
MAX_NEW_PER_CRAWL: Final = 50
"""The most documents one crawl ingests; the rest wait for the next crawl."""
MAX_SUMMARY_FAILURES: Final = 3
"""How many failed documents the source's ``last_error`` names."""


@dataclass(frozen=True, slots=True)
class CrawlRunId(EntityId):
    """One crawl of one source."""


class CrawlStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class CrawlCounts:
    listed: int = 0
    stored: int = 0
    duplicates: int = 0
    failed: int = 0

    def __post_init__(self) -> None:
        for name in COUNTS:
            require_int(getattr(self, name), name, minimum=0)

    @property
    def fetched(self) -> int:
        """Documents whose bytes were fetched: the new ones and the duplicates."""
        return self.stored + self.duplicates


@dataclass(frozen=True, slots=True)
class CrawlRun:
    id: CrawlRunId
    source_key: str
    started_at: datetime
    status: CrawlStatus = CrawlStatus.RUNNING
    finished_at: datetime | None = None
    counts: CrawlCounts = field(default_factory=CrawlCounts)
    error: str = ""

    def __post_init__(self) -> None:
        require_instance(self.id, CrawlRunId, "id")
        require_source_key(self.source_key)
        require_aware(self.started_at, "started_at")
        require_instance(self.status, CrawlStatus, "status")
        if (self.status is CrawlStatus.RUNNING) != (self.finished_at is None):
            raise InvariantViolationError("a run has finished_at exactly when it is not running")
        if self.finished_at is not None:
            require_aware(self.finished_at, "finished_at")
            if self.finished_at < self.started_at:
                raise InvariantViolationError("finished_at must not be before started_at")
        require_instance(self.counts, CrawlCounts, "counts")
        error = require_instance(self.error, str, "error")
        if len(error) > MAX_ERROR_CHARS:
            raise InvariantViolationError(f"error must be at most {MAX_ERROR_CHARS} chars")
        if (self.status is CrawlStatus.FAILED) != bool(error.strip()):
            raise InvariantViolationError("a run has an error exactly when it failed")

    @classmethod
    def start(cls, source_key: str, now: datetime) -> Self:
        return cls(id=CrawlRunId.new(), source_key=source_key, started_at=now)

    def finish(self, now: datetime, counts: CrawlCounts, *, error: str = "") -> Self:
        """The run ended: completed, or failed with ``error`` (cut to ``MAX_ERROR_CHARS``)."""
        if self.status is not CrawlStatus.RUNNING:
            raise InvariantViolationError(f"crawl run {self.id} has already {self.status.value}")
        cut = error.strip()[:MAX_ERROR_CHARS]
        return type(self)(
            id=self.id,
            source_key=self.source_key,
            started_at=self.started_at,
            status=CrawlStatus.FAILED if cut else CrawlStatus.COMPLETED,
            finished_at=now,
            counts=counts,
            error=cut,
        )

    def abandon(self, now: datetime, after: timedelta) -> Self:
        """The run closed as failed: it was still running ``after`` its start, so its workflow
        is gone (timed out, terminated, or never started)."""
        hours = after.total_seconds() / 3600
        return self.finish(
            now,
            self.counts,
            error=f"abandoned: the crawl did not finish within {hours:g} h of its start",
        )


class Outcome(StrEnum):
    """What became of one new document a crawl listed.

    - ``stored``: its bytes were stored for the first time;
    - ``duplicate``: its bytes were stored already, from another URL or another crawl;
    - ``failed``: it could not be fetched or stored;
    - ``deferred``: it was not ingested this time (another crawl was ingesting it).
    """

    STORED = "stored"
    DUPLICATE = "duplicate"
    FAILED = "failed"
    DEFERRED = "deferred"


@dataclass(frozen=True, slots=True)
class DocumentOutcome:
    url: str
    outcome: Outcome
    published_on: date | None = None
    error: str = ""

    def __post_init__(self) -> None:
        require_text(self.url, "url")
        require_instance(self.outcome, Outcome, "outcome")
        if self.published_on is not None:
            require_instance(self.published_on, date, "published_on")
        require_instance(self.error, str, "error")

    @property
    def kept(self) -> bool:
        """Its bytes are in the store."""
        return self.outcome in (Outcome.STORED, Outcome.DUPLICATE)


def listing_since(watermark: date | None, today: date) -> date:
    """The first publication date a crawl lists: a week before the watermark (never after
    today), or the last 30 days for a source without one."""
    if watermark is None:
        return today - LOOKBACK
    return min(watermark, today) - OVERLAP


def tally(listed: int, outcomes: Iterable[DocumentOutcome]) -> CrawlCounts:
    """The run's counts: everything listed, and the new documents by outcome."""
    found = list(outcomes)
    return CrawlCounts(
        listed=listed,
        stored=sum(item.outcome is Outcome.STORED for item in found),
        duplicates=sum(item.outcome is Outcome.DUPLICATE for item in found),
        failed=sum(item.outcome is Outcome.FAILED for item in found),
    )


def next_watermark(
    previous: date | None,
    outcomes: Iterable[DocumentOutcome],
    *,
    known_newest: date | None = None,
    deferred_oldest: date | None = None,
) -> date | None:
    """Where the watermark moves after a crawl that read the listing.

    It moves to the newest publication date whose document is stored (``known_newest``: the
    newest of the listed documents stored before this crawl), and back to the oldest dated
    document that was listed and is not stored (failed, deferred, or beyond the cap:
    ``deferred_oldest``), so the next crawl lists that one again. With nothing dated it stays.
    """
    found = list(outcomes)
    kept = [item.published_on for item in found if item.kept and item.published_on is not None]
    if known_newest is not None:
        kept.append(known_newest)
    missing = [
        item.published_on for item in found if not item.kept and item.published_on is not None
    ]
    if deferred_oldest is not None:
        missing.append(deferred_oldest)
    newest = max(kept, default=None)
    if missing:
        bound = min(missing)
        return bound if newest is None else min(newest, bound)
    if newest is None:
        return previous
    return newest if previous is None else max(previous, newest)


def failure_summary(outcomes: Sequence[DocumentOutcome]) -> str:
    """What the source's ``last_error`` says after a crawl whose listing went well: empty when
    every new document was kept, else how many failed and the first few with their errors."""
    failed = [item for item in outcomes if item.outcome is Outcome.FAILED]
    if not failed:
        return ""
    noun = "document" if len(outcomes) == 1 else "documents"
    head = f"{len(failed)} of {len(outcomes)} new {noun} failed"
    named = [
        f"{item.url}: {item.error or 'no error given'}" for item in failed[:MAX_SUMMARY_FAILURES]
    ]
    more = len(failed) - len(named)
    tail = f"; and {more} more" if more else ""
    return f"{head}: {'; '.join(named)}{tail}"[:MAX_ERROR_CHARS]
