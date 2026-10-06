"""When a source is crawled, under which ids, and how it stands.

The ``source`` table is the only schedule: no Temporal schedule holds a copy. Every minute the
worker's tick asks ``is_due`` of each source, and a source is due when it is enabled and not
paused, no crawl of it is running, and its cadence has passed since its last crawl started
(since its last listing, before its first run). A crawl's workflow id names the source and the
cadence slot the tick saw it due in (``scheduled_workflow_id``), so two ticks of the same slot
ask Temporal for the same workflow, and the second is refused. A crawl an admin starts by hand
has an id of its own (``manual_workflow_id``). Either way the crawl run's id is derived from the
workflow id (``run_id_for``), so the run a start records and the workflow it starts name each
other.

A run still ``running`` ``ABANDONED_AFTER`` its start has lost its workflow, which Temporal ends
at ``CRAWL_TIMEOUT``: the next start closes it as failed (``CrawlRun.abandon``).

How a source stands (``status_of``): ``fetching`` while a crawl runs, else ``paused`` while it
is paused or disabled, ``failing`` when its last crawl recorded an error, ``healthy`` otherwise. Its
freshness (``freshness_of``) is the time since a crawl last listed it, against its cadence:
``fresh`` within one cadence, ``late`` within two, ``stale`` beyond (the SourceStale alert pages
then), ``never`` before the first.
"""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from enum import StrEnum
from typing import Final
from uuid import UUID

from domain_kernel._validation import require_aware, require_instance
from domain_kernel.ids import derive_id
from pipeline.domain.crawl import CrawlRun, CrawlRunId, CrawlStatus
from pipeline.domain.sources import Source, require_source_key

INDIA: Final = timezone(timedelta(hours=5, minutes=30), "IST")
"""India Standard Time: regulators date their documents in it."""
CRAWL_TIMEOUT: Final = timedelta(hours=2)
"""The crawl workflow's execution timeout."""
ABANDONED_AFTER: Final = timedelta(hours=3)
"""A run still running this long after its start has no workflow left."""
INGEST_TIMEOUT: Final = timedelta(hours=1)
"""The execution timeout of each child ingest a crawl starts."""
CHILD_CONCURRENCY: Final = 3
"""The most child ingests one crawl runs at once."""
WORKFLOW_PREFIX: Final = "pipeline-crawl"
INGEST_PREFIX: Final = "pipeline-ingest"
RUN_NAMESPACE: Final = "crawl_run"
LATE_AFTER: Final = 1.0
STALE_AFTER: Final = 2.0
"""Freshness in cadences: beyond one a source is late, beyond two stale."""
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)


class CrawlTrigger(StrEnum):
    """Why a crawl ran: the schedule's tick, or an admin's fetch."""

    SCHEDULE = "schedule"
    MANUAL = "manual"


def run_id_for(workflow_id: str) -> CrawlRunId:
    """The crawl run a workflow records: derived from its id, the same on every call."""
    return derive_id(CrawlRunId, RUN_NAMESPACE, workflow_id)


def slot_start(now: datetime, cadence: timedelta) -> datetime:
    """The start of the cadence slot ``now`` falls in: slots of one cadence from the epoch."""
    require_aware(now, "now")
    seconds = int(cadence.total_seconds())
    if seconds < 1:
        raise ValueError("a cadence is at least a second")
    elapsed = int((now - _EPOCH).total_seconds())
    return _EPOCH + timedelta(seconds=elapsed - elapsed % seconds)


def scheduled_workflow_id(source_key: str, now: datetime, cadence: timedelta) -> str:
    """``pipeline-crawl-<key>-<slot start>``: one per source and cadence slot."""
    start = slot_start(now, cadence)
    return f"{WORKFLOW_PREFIX}-{require_source_key(source_key)}-{start:%Y%m%dT%H%M%SZ}"


def manual_workflow_id(source_key: str, request: UUID) -> str:
    """``pipeline-crawl-<key>-manual-<request>``: one per fetch an admin asks for."""
    require_instance(request, UUID, "request")
    return f"{WORKFLOW_PREFIX}-{require_source_key(source_key)}-manual-{request.hex}"


def ingest_workflow_id(source_key: str, url: str) -> str:
    """``pipeline-ingest-<key>-<first 24 hex digits of the URL's SHA-256>``: one per listed
    document, so a document two crawls list is ingested once."""
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    return f"{INGEST_PREFIX}-{require_source_key(source_key)}-{digest}"


def is_abandoned(run: CrawlRun, now: datetime) -> bool:
    return run.status is CrawlStatus.RUNNING and now - run.started_at >= ABANDONED_AFTER


def is_running(run: CrawlRun | None, now: datetime) -> bool:
    """A crawl runs: the run is running and not abandoned."""
    return run is not None and run.status is CrawlStatus.RUNNING and not is_abandoned(run, now)


def last_attempt(source: Source, latest: CrawlRun | None) -> datetime | None:
    """When the source was last crawled: its latest run's start, else its last listing."""
    if latest is not None:
        return latest.started_at
    return source.last_fetch_at


def is_due(source: Source, latest: CrawlRun | None, now: datetime) -> bool:
    """Whether the tick starts a crawl of the source now."""
    if not source.crawlable or is_running(latest, now):
        return False
    attempted = last_attempt(source, latest)
    return attempted is None or now - attempted >= source.cadence


class SourceStatus(StrEnum):
    HEALTHY = "healthy"
    FETCHING = "fetching"
    FAILING = "failing"
    PAUSED = "paused"


class FreshnessState(StrEnum):
    FRESH = "fresh"
    LATE = "late"
    STALE = "stale"
    NEVER = "never"


@dataclass(frozen=True, slots=True)
class Freshness:
    """The time since a crawl last listed the source, against its cadence. ``age`` and
    ``cadences`` are None before the first listing."""

    state: FreshnessState
    cadence: timedelta
    age: timedelta | None = None

    @property
    def cadences(self) -> float | None:
        if self.age is None:
            return None
        return self.age / self.cadence


def freshness_of(source: Source, now: datetime) -> Freshness:
    if source.last_fetch_at is None:
        return Freshness(FreshnessState.NEVER, source.cadence)
    age = max(now - source.last_fetch_at, timedelta(0))
    ratio = age / source.cadence
    if ratio > STALE_AFTER:
        state = FreshnessState.STALE
    elif ratio > LATE_AFTER:
        state = FreshnessState.LATE
    else:
        state = FreshnessState.FRESH
    return Freshness(state, source.cadence, age)


def staleness_age(source: Source, now: datetime) -> timedelta:
    """What the freshness gauge reports: the time since a crawl last listed the source, or
    since it was added when none has, so a source that never succeeds goes stale too."""
    since = source.last_fetch_at or source.created_at
    return max(now - since, timedelta(0))


def status_of(source: Source, latest: CrawlRun | None, now: datetime) -> SourceStatus:
    if is_running(latest, now):
        return SourceStatus.FETCHING
    if not source.crawlable:
        return SourceStatus.PAUSED
    if source.last_error:
        return SourceStatus.FAILING
    return SourceStatus.HEALTHY
