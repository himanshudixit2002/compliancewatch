"""The crawl: starting one, the worker's tick that starts the ones due, and the two activities of
the crawl workflow (``workflows.crawl_source``).

- ``StartCrawl``: an admin's fetch. In one transaction it locks the source, refuses an
  upload-only one (it lists nothing), closes a run left over from a lost workflow
  (``schedule.ABANDONED_AFTER``), refuses while a crawl runs, records the new run and its
  ``pipeline.source.fetch`` audit entry; then, with the transaction closed, it starts the
  workflow.
- ``ScheduleCrawls``: the tick. For each source ``schedule.is_due`` names (never an upload-only
  one, none while a crawl of it runs, a backfill's included; the cadence counted from its last
  crawl that was not a backfill), it locks the source, checks again, records the run under the
  id derived from the source's cadence slot and starts the workflow of that slot. A second tick
  in the same slot finds the run recorded (or Temporal refuses the id), so it starts nothing.
- ``ListNewDocuments`` (``pipeline.list_new_documents``): the source's listing since a week
  before its watermark, through its adapter, with no transaction open; the URLs the store holds
  are skipped, and at most the crawl's limit of the rest come back, newest first. A backfill
  names its own window instead (``ListingWindow``): from a date below the watermark, up to
  another, only the references its plan names.
- ``FinishCrawl`` (``pipeline.finish_crawl``): the run's counts and end, and the source's last
  listing, watermark and error, in one transaction. A document whose ingest failed or was busy
  elsewhere is looked up by its URL first, since its bytes may be stored all the same. A
  backfill's end records its run only: the source keeps its watermark, last listing and error
  as the schedule's crawls left them (``domain.crawl``).

Neither the tick nor a start ever fetches inside a transaction: the workflow does the fetching,
in its child ingests (``FetchAndStore``).
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import ClassVar, Final
from uuid import UUID, uuid4

from pydantic import Field
from temporalio.common import RetryPolicy

from domain_kernel.audit import AuditActor, AuditEntry
from domain_kernel.documents import DiscoveredDocument
from domain_kernel.events import utc_now
from domain_kernel.ids import SourceId
from pipeline.application.activities import Discovered, Frozen, on_thread
from pipeline.application.sources import (
    FETCH_ACTION,
    SOURCE_SUBJECT,
    require_reason,
)
from pipeline.domain.crawl import (
    MAX_NEW_PER_CRAWL,
    MAX_REFS,
    CrawlRun,
    CrawlRunId,
    CrawlStatus,
    CrawlTrigger,
    DocumentOutcome,
    ListingWindow,
    Outcome,
    failure_summary,
    listing_since,
    next_watermark,
    tally,
)
from pipeline.domain.errors import (
    CrawlDisabledError,
    CrawlRunningError,
    CrawlUnavailableError,
    SourceNotFoundError,
    SourceNotListableError,
)
from pipeline.domain.ports import AdapterTypes, CrawlStart, CrawlStarter, SourceCatalog
from pipeline.domain.repository import UnitOfWork, UnitOfWorkFactory
from pipeline.domain.schedule import (
    ABANDONED_AFTER,
    INDIA,
    is_abandoned,
    is_due,
    manual_workflow_id,
    run_id_for,
    scheduled_workflow_id,
)
from pipeline.domain.sources import SOURCE_KEY_PATTERN, Source, source_id_of
from py_common.logging import get_logger
from py_common.temporal import ActivityBase

log = get_logger(__name__)

MAX_LIMIT: Final = 500
MAX_OUTCOME_ERROR_CHARS: Final = 300


# ---------------------------------------------------------------- starting a crawl


@dataclass(frozen=True, slots=True)
class FetchRequest:
    """An admin's fetch of one source: who asks, why, and the request behind it."""

    source_key: str
    actor: AuditActor
    reason: str
    correlation_id: str | None = None


def close_abandoned(unit: UnitOfWork, source_key: str, now: datetime) -> list[CrawlRun]:
    """Close the source's runs that lost their workflow; the runs still running."""
    running: list[CrawlRun] = []
    for run in unit.crawl_runs.running(source_key):
        if is_abandoned(run, now):
            unit.crawl_runs.save(run.abandon(max(now, run.started_at), ABANDONED_AFTER))
            log.warning("pipeline.crawl_abandoned", source=source_key, run_id=str(run.id))
        else:
            running.append(run)
    return running


def _close(
    units: UnitOfWorkFactory, start: CrawlStart, clock: Callable[[], datetime], why: str
) -> None:
    with units() as unit:
        run = unit.crawl_runs.get(start.run_id)
        if run is not None and run.status is CrawlStatus.RUNNING:
            unit.crawl_runs.save(run.finish(max(clock(), run.started_at), run.counts, error=why))


def launch(
    units: UnitOfWorkFactory,
    starter: CrawlStarter,
    start: CrawlStart,
    clock: Callable[[], datetime],
) -> bool:
    """Start the recorded run's workflow. A start Temporal refuses (``CrawlUnavailableError``)
    or that finds the id taken by a workflow from before closes the run as failed with why."""
    try:
        started = starter.start(start)
    except Exception as exc:
        reason = f"the crawl could not start: {type(exc).__name__}: {exc}"
        _close(units, start, clock, reason)
        log.warning(
            "pipeline.crawl_not_started", source=start.source_key, workflow_id=start.workflow_id
        )
        if isinstance(exc, CrawlUnavailableError):
            raise
        raise CrawlUnavailableError(reason) from exc
    if not started:
        _close(units, start, clock, f"a workflow {start.workflow_id} exists already")
        return False
    log.info(
        "pipeline.crawl_started",
        source=start.source_key,
        workflow_id=start.workflow_id,
        run_id=str(start.run_id),
        trigger=start.trigger.value,
    )
    return True


class StartCrawl:
    """An admin's fetch now: refused while crawling is off (503), for an upload-only source
    (409) or while a crawl of the source runs (409); a paused or disabled source may still be
    fetched by hand."""

    def __init__(
        self,
        units: UnitOfWorkFactory,
        starter: CrawlStarter,
        *,
        types: AdapterTypes,
        enabled: bool,
        clock: Callable[[], datetime] = utc_now,
        request_ids: Callable[[], UUID] = uuid4,
    ) -> None:
        self._units = units
        self._starter = starter
        self._types = types
        self._enabled = enabled
        self._clock = clock
        self._request_ids = request_ids

    @property
    def enabled(self) -> bool:
        return self._enabled

    def run(self, request: FetchRequest) -> CrawlStart:
        if not self._enabled:
            raise CrawlDisabledError()
        reason = require_reason(request.reason)
        key = request.source_key
        workflow_id = manual_workflow_id(key, self._request_ids())
        start = CrawlStart(workflow_id, run_id_for(workflow_id), key, CrawlTrigger.MANUAL)
        now = self._clock()
        with self._units() as unit:
            source = unit.sources.get(key, for_update=True)
            if source is None:
                raise SourceNotFoundError(f"no source has the key {key!r}")
            if not self._types.listable(source.adapter_type):
                raise SourceNotListableError(
                    f"{key} is upload-only ({source.adapter_type}): it lists nothing to crawl; "
                    f"upload its documents to /v1/pipeline/sources/{key}/uploads"
                )
            running = close_abandoned(unit, key, now)
            if running:
                raise CrawlRunningError(
                    f"crawl run {running[0].id} of {key} runs since "
                    f"{running[0].started_at.isoformat()}"
                )
            unit.crawl_runs.add(
                CrawlRun(
                    id=start.run_id,
                    source_key=key,
                    started_at=now,
                    trigger=start.trigger,
                    workflow_id=start.workflow_id,
                )
            )
            unit.audit.write(
                AuditEntry(
                    action=FETCH_ACTION,
                    tenant_id=None,
                    subject_type=SOURCE_SUBJECT,
                    subject_id=key,
                    actor=request.actor,
                    reason=reason,
                    after={"run_id": str(start.run_id), "workflow_id": start.workflow_id},
                    occurred_at=now,
                    correlation_id=request.correlation_id,
                )
            )
        launch(self._units, self._starter, start, self._clock)
        return start


@dataclass(frozen=True, slots=True)
class ScheduleReport:
    started: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()


class ScheduleCrawls:
    """The tick: a crawl of every source that is due, at most one per source and slot."""

    def __init__(
        self,
        units: UnitOfWorkFactory,
        starter: CrawlStarter,
        *,
        types: AdapterTypes,
        enabled: bool,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._units = units
        self._starter = starter
        self._types = types
        self._enabled = enabled
        self._clock = clock

    def run(self) -> ScheduleReport:
        if not self._enabled:
            return ScheduleReport()
        now = self._clock()
        with self._units() as unit:
            sources = unit.sources.list()
            latest = unit.crawl_runs.latest_by_source()
            crawled = unit.crawl_runs.latest_by_source(backfills=False)
        started: list[str] = []
        failed: list[str] = []
        for source in sources:
            listable = self._types.listable(source.adapter_type)
            due = is_due(
                source,
                latest.get(source.key),
                now,
                listable=listable,
                last_crawl=crawled.get(source.key),
            )
            if not due:
                continue
            try:
                start = self._start(source.key, now)
            except Exception as exc:
                failed.append(source.key)
                log.warning(
                    "pipeline.crawl_schedule_failed",
                    source=source.key,
                    error=f"{type(exc).__name__}: {exc}",
                )
                continue
            if start is not None:
                started.append(start.workflow_id)
        if started or failed:
            log.info("pipeline.crawls_scheduled", started=started, failed=failed)
        return ScheduleReport(tuple(started), tuple(failed))

    def _start(self, key: str, now: datetime) -> CrawlStart | None:
        with self._units() as unit:
            source = unit.sources.get(key, for_update=True)
            if source is None:
                return None
            close_abandoned(unit, key, now)
            due = is_due(
                source,
                unit.crawl_runs.latest(key),
                now,
                listable=self._types.listable(source.adapter_type),
                last_crawl=unit.crawl_runs.latest(key, backfills=False),
            )
            if not due:
                return None
            workflow_id = scheduled_workflow_id(key, now, source.cadence)
            start = CrawlStart(workflow_id, run_id_for(workflow_id), key, CrawlTrigger.SCHEDULE)
            recorded = CrawlRun(
                id=start.run_id,
                source_key=key,
                started_at=now,
                trigger=start.trigger,
                workflow_id=start.workflow_id,
            )
            if not unit.crawl_runs.start(recorded):
                return None
        return start if launch(self._units, self._starter, start, self._clock) else None


# ---------------------------------------------------------------- the crawl's activities


class CrawlRequest(Frozen):
    """The input of ``pipeline.crawl_source``: the source, the run its start recorded, why it
    runs, and the most documents it ingests. A backfill also names its listing window:
    ``since`` (below the watermark), ``until`` and the references ``refs`` it takes."""

    source_key: str = Field(pattern=SOURCE_KEY_PATTERN)
    run_id: UUID
    trigger: CrawlTrigger = CrawlTrigger.SCHEDULE
    limit: int = Field(default=MAX_NEW_PER_CRAWL, ge=1, le=MAX_LIMIT)
    since: date | None = None
    until: date | None = None
    refs: list[str] = Field(default_factory=list, max_length=MAX_REFS)

    @property
    def window(self) -> ListingWindow:
        return ListingWindow(self.since, self.until, tuple(self.refs))


class ListRequest(Frozen):
    source_key: str = Field(pattern=SOURCE_KEY_PATTERN)
    run_id: UUID
    limit: int = Field(default=MAX_NEW_PER_CRAWL, ge=1, le=MAX_LIMIT)
    since: date | None = None
    until: date | None = None
    refs: list[str] = Field(default_factory=list, max_length=MAX_REFS)

    @property
    def window(self) -> ListingWindow:
        return ListingWindow(self.since, self.until, tuple(self.refs))


class Listing(Frozen):
    """What the listing gave: the documents to ingest (``new``, at most the limit, newest
    first), what it listed in all, the newest date of the listed documents stored before, and
    the oldest date of the new ones left for the next crawl."""

    source_id: UUID
    source_key: str
    regulator: str
    knowledge: bool
    since: date
    listed: int = Field(ge=0)
    known: int = Field(ge=0)
    new: list[Discovered]
    known_newest: date | None = None
    deferred: int = Field(default=0, ge=0)
    deferred_oldest: date | None = None


class ChildOutcome(Frozen):
    """What became of one child ingest, as the workflow saw it."""

    url: str = Field(min_length=1)
    published_at: date | None = None
    outcome: Outcome
    error: str = Field(default="", max_length=MAX_OUTCOME_ERROR_CHARS)


class FinishRequest(Frozen):
    """The crawl's end: ``error`` when the listing failed, otherwise what it listed and what
    became of each new document, and how many new ones it left for a later crawl. A backfill's
    (``trigger``) leaves its source as it found it."""

    source_key: str = Field(pattern=SOURCE_KEY_PATTERN)
    run_id: UUID
    error: str = ""
    listed: int = Field(default=0, ge=0)
    known_newest: date | None = None
    deferred_oldest: date | None = None
    outcomes: list[ChildOutcome] = Field(default_factory=list)
    trigger: CrawlTrigger = CrawlTrigger.SCHEDULE
    deferred: int = Field(default=0, ge=0)


class CrawlResult(Frozen):
    """How the crawl went; ``deferred`` counts the new documents left for a later crawl."""

    run_id: UUID
    source_key: str
    status: CrawlStatus
    listed: int
    stored: int
    duplicates: int
    failed: int
    error: str = ""
    source_error: str = ""
    watermark: date | None = None
    deferred: int = 0


def india_midnight(day: date) -> datetime:
    """The start of ``day`` in India, as the adapters compare publication dates."""
    return datetime.combine(day, time(0), tzinfo=INDIA)


def _newest_first(document: DiscoveredDocument) -> tuple[bool, int]:
    published = document.published_at
    return (published is None, -published.toordinal() if published is not None else 0)


LIST_RETRIES: Final = RetryPolicy(
    initial_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
    maximum_attempts=3,
    non_retryable_error_types=[
        "UnknownSourceError",
        "SourceNotFoundError",
        "DisallowedByRobotsError",
        "InvariantViolationError",
    ],
)
"""A listing the polite client gave up on (five tries of its own) is tried twice more; the next
tick tries again after a cadence. A source the code cannot read and a path robots.txt disallows
are not retried."""


class ListNewDocuments(ActivityBase[ListRequest, Listing]):
    """The source's new documents since a week before its watermark."""

    name: ClassVar[str] = "pipeline.list_new_documents"
    input_type: ClassVar[type[ListRequest]] = ListRequest
    output_type: ClassVar[type[Listing]] = Listing
    start_to_close: ClassVar[timedelta] = timedelta(minutes=15)
    heartbeat_timeout: ClassVar[timedelta | None] = timedelta(minutes=1)
    retry_policy: ClassVar[RetryPolicy] = LIST_RETRIES

    def __init__(
        self,
        units: UnitOfWorkFactory,
        sources: SourceCatalog,
        *,
        knowledge: bool = False,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._units = units
        self._sources = sources
        self._knowledge = knowledge
        self._clock = clock

    async def run(self, input: ListRequest) -> Listing:
        source = await on_thread(self, lambda: self._source(input.source_key))
        resolved = await on_thread(self, lambda: self._sources.resolve(source_id_of(source.key)))
        window = input.window
        since = window.since or listing_since(
            source.watermark_date, self._clock().astimezone(INDIA).date()
        )
        listed = await on_thread(
            self, lambda: list(resolved.adapter.list_documents(india_midnight(since)))
        )
        unique: dict[str, DiscoveredDocument] = {}
        for document in listed:
            if window.admits(document.published_at, document.ref.external_ref):
                unique.setdefault(document.ref.url, document)
        known = await on_thread(self, lambda: self._known(source.key, list(unique)))
        new = sorted(
            (document for url, document in unique.items() if url not in known),
            key=_newest_first,
        )
        taken, left = new[: input.limit], new[input.limit :]
        known_dates = [
            document.published_at
            for url, document in unique.items()
            if url in known and document.published_at is not None
        ]
        left_dates = [document.published_at for document in left if document.published_at]
        log.info(
            "pipeline.crawl_listed",
            source=source.key,
            since=since.isoformat(),
            listed=len(unique),
            known=len(known),
            new=len(taken),
            deferred=len(left),
        )
        return Listing(
            source_id=resolved.source_id.value,
            source_key=source.key,
            regulator=resolved.definition.regulator,
            knowledge=self._knowledge,
            since=since,
            listed=len(unique),
            known=len(known),
            new=[_discovered(resolved.source_id, document) for document in taken],
            known_newest=max(known_dates, default=None),
            deferred=len(left),
            deferred_oldest=min(left_dates, default=None),
        )

    def _source(self, key: str) -> Source:
        with self._units() as unit:
            source = unit.sources.get(key)
        if source is None:
            raise SourceNotFoundError(f"no source has the key {key!r}")
        return source

    def _known(self, key: str, urls: Sequence[str]) -> frozenset[str]:
        with self._units() as unit:
            return unit.documents.known_urls(key, urls)


def _discovered(source_id: SourceId, document: DiscoveredDocument) -> Discovered:
    return Discovered(
        source_id=source_id.value,
        url=document.ref.url,
        external_ref=document.ref.external_ref,
        title=document.title,
        published_at=document.published_at,
    )


FINISH_RETRIES: Final = RetryPolicy(
    maximum_attempts=20,
    non_retryable_error_types=["InvariantViolationError", "SourceNotFoundError"],
)
"""The bookkeeping waits out a database that is away for a while (about 20 minutes)."""


class FinishCrawl(ActivityBase[FinishRequest, CrawlResult]):
    """Record how the crawl went on its run and its source."""

    name: ClassVar[str] = "pipeline.finish_crawl"
    input_type: ClassVar[type[FinishRequest]] = FinishRequest
    output_type: ClassVar[type[CrawlResult]] = CrawlResult
    start_to_close: ClassVar[timedelta] = timedelta(minutes=2)
    retry_policy: ClassVar[RetryPolicy] = FINISH_RETRIES

    def __init__(
        self, units: UnitOfWorkFactory, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._units = units
        self._clock = clock

    async def run(self, input: FinishRequest) -> CrawlResult:
        return await on_thread(self, lambda: self.finish(input))

    def finish(self, input: FinishRequest) -> CrawlResult:
        key, run_id = input.source_key, CrawlRunId(input.run_id)
        outcomes = self._settled(key, input.outcomes) if not input.error else []
        counts = tally(input.listed, outcomes)
        with self._units() as unit:
            run = unit.crawl_runs.get(run_id)
            source = unit.sources.get(key, for_update=True)
            if source is None:
                raise SourceNotFoundError(f"no source has the key {key!r}")
            if run is None:
                run = CrawlRun(
                    id=run_id, source_key=key, started_at=self._clock(), trigger=input.trigger
                )
                unit.crawl_runs.add(run)
            if run.status is not CrawlStatus.RUNNING:
                # Closed as abandoned meanwhile: a later crawl may have moved the source on.
                log.warning("pipeline.crawl_finished_late", source=key, run_id=str(run_id))
                return _result(run, source, None, input.deferred)
            now = max(self._clock(), run.started_at)
            finished = run.finish(now, counts, error=input.error)
            unit.crawl_runs.save(finished)
            updated = source
            if input.trigger is not CrawlTrigger.BACKFILL:
                updated = _crawled(source, input, outcomes, now)
                unit.sources.save(updated)
        log.info(
            "pipeline.crawl_finished",
            source=key,
            run_id=str(run_id),
            status=finished.status.value,
            listed=counts.listed,
            stored=counts.stored,
            duplicates=counts.duplicates,
            failed=counts.failed,
        )
        return _result(finished, updated, updated.watermark_date, input.deferred)

    def _settled(self, key: str, outcomes: Sequence[ChildOutcome]) -> list[DocumentOutcome]:
        """The outcomes, with a failed or deferred document whose URL is stored counted as
        stored (its ingest failed after the store) or as a duplicate (another crawl stored
        it)."""
        unsure = [
            item.url for item in outcomes if item.outcome in (Outcome.FAILED, Outcome.DEFERRED)
        ]
        kept: frozenset[str] = frozenset()
        if unsure:
            with self._units() as unit:
                kept = unit.documents.known_urls(key, unsure)
        settled: list[DocumentOutcome] = []
        for item in outcomes:
            outcome = item.outcome
            if item.url in kept and outcome is Outcome.FAILED:
                outcome = Outcome.STORED
            elif item.url in kept and outcome is Outcome.DEFERRED:
                outcome = Outcome.DUPLICATE
            settled.append(DocumentOutcome(item.url, outcome, item.published_at, item.error))
        return settled


def _crawled(
    source: Source, input: FinishRequest, outcomes: Sequence[DocumentOutcome], now: datetime
) -> Source:
    """The source after the schedule's crawl or an admin's fetch: reached or not, its watermark
    (``next_watermark``) and its error. A backfill's never comes here: it lists history, so the
    source's watermark (None included), last listing and error stay the schedule's."""
    if input.error:
        return source.crawled(now, listed=False, watermark=None, error=input.error)
    watermark = next_watermark(
        source.watermark_date,
        outcomes,
        known_newest=input.known_newest,
        deferred_oldest=input.deferred_oldest,
    )
    return source.crawled(now, listed=True, watermark=watermark, error=failure_summary(outcomes))


def _result(run: CrawlRun, source: Source, watermark: date | None, deferred: int) -> CrawlResult:
    return CrawlResult(
        run_id=run.id.value,
        source_key=run.source_key,
        status=run.status,
        listed=run.counts.listed,
        stored=run.counts.stored,
        duplicates=run.counts.duplicates,
        failed=run.counts.failed,
        error=run.error,
        source_error=source.last_error,
        watermark=watermark,
        deferred=deferred,
    )
