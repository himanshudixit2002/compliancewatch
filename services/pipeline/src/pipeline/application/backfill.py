"""The backfill through the crawl workflow: a plan's rows of history (``domain.backfill``), each
crawled by ``CrawlSourceWorkflow`` with the trigger ``backfill``, then a report of where the
documents got to.

- ``PlanDryRun``: each row's listing through its source's adapter (the store's catalog), cut to
  the row's window and counted against the URLs the store holds: listed, known, new, with no
  fetch and no write. It reads the regulator's site, so it runs only when a person runs it.
- ``StartBackfill``: one crawl of a row. In one transaction it locks the source, refuses an
  upload-only one, closes a run left over from a lost workflow, refuses while a crawl of the
  source runs, and records the run (trigger ``backfill``, its workflow) with its
  ``pipeline.source.backfill`` audit row; then, with the transaction closed, it starts the crawl
  ``pipeline-crawl-<key>-backfill-<request>`` with the row's window and limit. Refused while
  crawling is off: a backfill reads the live regulator sites.
- ``RunBackfill``: the rows in order, each crawled again while its last crawl left new documents
  for a later one and kept something (``domain.backfill.next_limit``), waiting for each crawl to
  end (``CrawlWatcher``).
- ``BackfillReport``: per source, the documents stored, parsed, not read by any parser, set aside,
  waiting for their extraction, held for triage, kept for reference and extracted, the
  candidates and unparseable answers of the current prompt, and how analysts decided the
  candidates (``CandidateStats``, the rulebook's review stats), with the share no parser read.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final
from uuid import UUID, uuid4

from domain_kernel.audit import AuditActor, AuditEntry
from domain_kernel.events import utc_now
from pipeline.application.crawl import close_abandoned, india_midnight, launch
from pipeline.application.extraction import RULE_PROMPT_REF
from pipeline.application.sources import SOURCE_SUBJECT, require_reason
from pipeline.domain.backfill import DEFAULT_MAX_ROUNDS, BackfillRow, first_limit, next_limit
from pipeline.domain.crawl import CrawlRun, CrawlTrigger
from pipeline.domain.errors import (
    CrawlDisabledError,
    CrawlRunningError,
    SourceNotFoundError,
    SourceNotListableError,
)
from pipeline.domain.extraction import ExtractionOutcome
from pipeline.domain.ports import (
    AdapterTypes,
    CandidateStats,
    CrawlOutcome,
    CrawlStart,
    CrawlStarter,
    CrawlWatcher,
    SourceCatalog,
)
from pipeline.domain.raw_documents import DocumentStatus
from pipeline.domain.repository import DocumentTally, UnitOfWorkFactory
from pipeline.domain.schedule import backfill_workflow_id, run_id_for
from pipeline.domain.sources import source_id_of
from py_common.logging import get_logger

log = get_logger(__name__)

BACKFILL_ACTION: Final = "pipeline.source.backfill"
SAMPLE: Final = 5
"""How many new documents a dry run names per row."""


# ---------------------------------------------------------------- the dry run


@dataclass(frozen=True, slots=True)
class RowListing:
    """What a row's listing gave: everything in its window (``listed``), the URLs the store
    holds already (``known``), the rest (``new``), the first few new ones by reference, or why
    the listing failed (``error``)."""

    row: BackfillRow
    listed: int = 0
    known: int = 0
    new: int = 0
    sample: tuple[str, ...] = ()
    error: str = ""


class PlanDryRun:
    def __init__(self, units: UnitOfWorkFactory, sources: SourceCatalog) -> None:
        self._units = units
        self._sources = sources

    def run(self, rows: Sequence[BackfillRow]) -> list[RowListing]:
        return [self._row(row) for row in rows]

    def _row(self, row: BackfillRow) -> RowListing:
        try:
            adapter = self._sources.resolve(source_id_of(row.source_key)).adapter
            listed = [
                document
                for document in adapter.list_documents(india_midnight(row.since))
                if row.window.admits(document.published_at, document.ref.external_ref)
            ]
        except Exception as exc:
            return RowListing(row, error=f"{type(exc).__name__}: {exc}")
        unique = {document.ref.url: document for document in listed}
        with self._units() as unit:
            known = unit.documents.known_urls(row.source_key, list(unique))
        new = [document for url, document in unique.items() if url not in known]
        sample = tuple(
            document.ref.external_ref or document.title or document.ref.url
            for document in new[:SAMPLE]
        )
        return RowListing(row, len(unique), len(known), len(new), sample)


# ---------------------------------------------------------------- the crawls


@dataclass(frozen=True, slots=True)
class BackfillRequest:
    """Who runs the backfill and why: the actor its audit rows name (the system's backfill
    command, or the person it was told), the reason, and the request behind it."""

    actor: AuditActor
    reason: str
    correlation_id: str | None = None


class StartBackfill:
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

    def run(self, row: BackfillRow, limit: int, request: BackfillRequest) -> CrawlStart:
        if not self._enabled:
            raise CrawlDisabledError()
        reason = require_reason(request.reason)
        key = row.source_key
        workflow_id = backfill_workflow_id(key, self._request_ids())
        start = CrawlStart(
            workflow_id,
            run_id_for(workflow_id),
            key,
            CrawlTrigger.BACKFILL,
            since=row.since,
            until=row.until,
            refs=row.refs,
            limit=limit,
        )
        now = self._clock()
        with self._units() as unit:
            source = unit.sources.get(key, for_update=True)
            if source is None:
                raise SourceNotFoundError(f"no source has the key {key!r}")
            if not self._types.listable(source.adapter_type):
                raise SourceNotListableError(
                    f"{key} is upload-only ({source.adapter_type}): it lists nothing to backfill"
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
                    trigger=CrawlTrigger.BACKFILL,
                    workflow_id=workflow_id,
                )
            )
            unit.audit.write(
                AuditEntry(
                    action=BACKFILL_ACTION,
                    tenant_id=None,
                    subject_type=SOURCE_SUBJECT,
                    subject_id=key,
                    actor=request.actor,
                    reason=reason,
                    after={
                        "run_id": str(start.run_id),
                        "workflow_id": workflow_id,
                        "since": row.since.isoformat(),
                        "until": None if row.until is None else row.until.isoformat(),
                        "refs": list(row.refs),
                        "limit": limit,
                    },
                    occurred_at=now,
                    correlation_id=request.correlation_id,
                )
            )
        launch(self._units, self._starter, start, self._clock)
        return start


@dataclass(frozen=True, slots=True)
class RowRun:
    """How a row went: each crawl's outcome in order, and why the row stopped."""

    row: BackfillRow
    rounds: tuple[CrawlOutcome, ...] = ()
    stopped: str = ""

    @property
    def stored(self) -> int:
        return sum(outcome.stored for outcome in self.rounds)


class RunBackfill:
    def __init__(
        self,
        start: StartBackfill,
        watcher: CrawlWatcher,
        *,
        max_rounds: int = DEFAULT_MAX_ROUNDS,
    ) -> None:
        self._start = start
        self._watcher = watcher
        self._max_rounds = max_rounds

    def run(
        self,
        rows: Sequence[BackfillRow],
        request: BackfillRequest,
        *,
        progress: Callable[[BackfillRow, CrawlOutcome], None] | None = None,
    ) -> list[RowRun]:
        return [self._row(row, request, progress) for row in rows]

    def _row(
        self,
        row: BackfillRow,
        request: BackfillRequest,
        progress: Callable[[BackfillRow, CrawlOutcome], None] | None,
    ) -> RowRun:
        rounds: list[CrawlOutcome] = []
        limit: int | None = first_limit(row)
        while limit is not None:
            try:
                started = self._start.run(row, limit, request)
                outcome = self._watcher.wait(started.workflow_id)
            except Exception as exc:
                log.warning("pipeline.backfill_row_stopped", source=row.source_key, error=str(exc))
                return RowRun(row, tuple(rounds), f"{type(exc).__name__}: {exc}")
            rounds.append(outcome)
            if progress is not None:
                progress(row, outcome)
            if outcome.status != "completed":
                return RowRun(row, tuple(rounds), f"the crawl {outcome.status}: {outcome.error}")
            limit = next_limit(
                row,
                rounds=len(rounds),
                stored=sum(found.stored for found in rounds),
                deferred=outcome.deferred,
                progressed=outcome.stored + outcome.duplicates > 0,
                max_rounds=self._max_rounds,
            )
        last = rounds[-1]
        if last.deferred == 0:
            why = "nothing new is left"
        elif last.stored + last.duplicates == 0:
            why = "the last crawl kept nothing"
        elif row.max_documents is not None and sum(f.stored for f in rounds) >= row.max_documents:
            why = f"it stored its {row.max_documents} documents"
        else:
            why = f"it ran {self._max_rounds} crawls"
        log.info(
            "pipeline.backfill_row_done",
            source=row.source_key,
            rounds=len(rounds),
            stored=sum(found.stored for found in rounds),
            why=why,
        )
        return RowRun(row, tuple(rounds), why)


# ---------------------------------------------------------------- the report


@dataclass(frozen=True, slots=True)
class SourceFunnel:
    """One source's documents and where they got to."""

    source_key: str
    tally: DocumentTally
    candidates: int = 0
    unparseable: int = 0

    def at(self, status: DocumentStatus) -> int:
        return self.tally.at(status)


@dataclass(frozen=True, slots=True)
class BackfillFunnel:
    """Every source's funnel, how analysts decided the candidates (``acceptance``; empty, with
    ``acceptance_error``, when the rulebook did not tell), and the prompt the candidates are of."""

    sources: tuple[SourceFunnel, ...]
    acceptance: Mapping[str, object] = field(default_factory=dict)
    acceptance_error: str = ""
    prompt_version: str = RULE_PROMPT_REF

    @property
    def stored(self) -> int:
        return sum(source.tally.stored for source in self.sources)

    @property
    def unparsed(self) -> int:
        return sum(source.at(DocumentStatus.FAILED) for source in self.sources)

    @property
    def unparsed_share(self) -> float | None:
        """The share of the stored documents no parser read; None with none stored."""
        return None if self.stored == 0 else self.unparsed / self.stored


class BackfillReport:
    def __init__(self, units: UnitOfWorkFactory, stats: CandidateStats | None) -> None:
        self._units = units
        self._stats = stats

    def run(self, keys: Sequence[str] = ()) -> BackfillFunnel:
        with self._units() as unit:
            tallies = unit.documents.tally()
            outcomes = unit.extractions.tally(RULE_PROMPT_REF)
        wanted = sorted(set(tallies) | set(keys))
        sources = tuple(
            SourceFunnel(
                source_key=key,
                tally=tallies.get(key, DocumentTally()),
                candidates=outcomes.get(key, {}).get(ExtractionOutcome.EXTRACTED, 0),
                unparseable=outcomes.get(key, {}).get(ExtractionOutcome.UNPARSEABLE, 0),
            )
            for key in wanted
        )
        acceptance: Mapping[str, object] = {}
        error = ""
        if self._stats is None:
            error = "no rulebook to ask"
        else:
            # Asked with the store's transaction closed: the rulebook is an HTTP call.
            try:
                acceptance = self._stats.candidate_stats()
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
        return BackfillFunnel(sources, acceptance, error)
