"""``pipeline-backfill``: fill the pipeline's store with a regulator's history through the crawl
workflow, from a plan, and report where the documents got to.

    pipeline-backfill --plan services/pipeline/backfill-plan.yaml --dry-run
    pipeline-backfill --plan services/pipeline/backfill-plan.yaml --workflow --reason "<why>"
    pipeline-backfill --plan services/pipeline/backfill-plan.yaml --report [--json]

A plan (``--plan``, YAML) lists rows in order, each a source with its window and limits
(``domain.backfill.BackfillRow``): ``source``, ``since``, and optionally ``until``, ``refs`` (the
references to take, as the listing writes them), ``limit`` (documents per crawl, 500 at most),
``max_documents`` (in all) and ``note``. ``--row N`` runs only the Nth.

- ``--dry-run`` lists each row's window through its source's adapter and counts the documents
  new to the store (``application.backfill.PlanDryRun``): no fetch, no write. **It reads the
  live regulator site**: a person runs it, never a test or a check.
- ``--workflow`` starts ``CrawlSourceWorkflow`` per row with the trigger ``backfill``, the row's
  window and limit, waits for it, and crawls again while new documents are left
  (``RunBackfill``); each crawl is a crawl run with its ``pipeline.source.backfill`` audit row,
  naming ``--actor-id`` or the system's backfill, with ``--reason``. It fetches from the live
  sites through the running worker, so it refuses while ``CW_PIPELINE_CRAWL_ENABLED`` is off.
- ``--report`` counts per source, from the store, the documents stored, parsed, unread by any
  parser, set aside, classified (waiting for their extraction), held for triage, kept for
  reference and extracted, with the current prompt's candidates and unparseable answers, and
  asks the rulebook (``CW_RULEBOOK_URL``, ``GET /v1/rulebook/review/stats``) how analysts decided
  the candidates; the share no parser read is the OCR question's number.

``--legacy`` keeps the command this one replaced, which fetches straight from a site into a local
raw store outside the pipeline's store and its workflow, records nothing and extracts nothing:
``pipeline-backfill --legacy --source cbic_notifications --since 2026-01-01 [--store var/raw]
[--limit N] [--list-only]``. Keep it for recording fixtures; the plan's modes are the backfill.

Exit status: 0 done; 1 a row's listing or crawl failed, or nothing could be fetched (legacy);
2 refused (crawling off, no reason) or the store cannot be read.
"""

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final
from uuid import UUID

import yaml

from domain_kernel.audit import AuditActor
from domain_kernel.documents import DiscoveredDocument, DocumentType, ParsedDocument, RawDocument
from domain_kernel.ids import UserId
from domain_kernel.protocols import DocumentParser, SourceAdapter
from pipeline.application.backfill import (
    BackfillFunnel,
    BackfillReport,
    BackfillRequest,
    PlanDryRun,
    RowListing,
    RowRun,
    RunBackfill,
    StartBackfill,
)
from pipeline.application.detector import Detection, detect
from pipeline.domain.backfill import DEFAULT_MAX_ROUNDS, BackfillRow
from pipeline.domain.ports import (
    AdapterTypes,
    CandidateStats,
    CrawlOutcome,
    CrawlStarter,
    CrawlWatcher,
    RawStore,
    SourceCatalog,
)
from pipeline.domain.raw_documents import DocumentStatus
from pipeline.domain.repository import UnitOfWorkFactory
from pipeline.infrastructure.adapters import (
    SOURCES,
    RegistryAdapterTypes,
    StoreCatalog,
    build_adapter,
)
from pipeline.infrastructure.http import ClientConfig, PoliteClient
from pipeline.infrastructure.parsers import parsers_for
from pipeline.infrastructure.parsers.pdf import UnparsedDocumentError
from pipeline.infrastructure.raw_store import LocalRawStore
from pipeline.infrastructure.rulebook_client import HttpRulebook
from pipeline.infrastructure.temporal import TemporalCrawls
from pipeline.settings import PipelineSettings
from pipeline.stores import unit_of_work_of
from py_common.auth import service_auth_from

SERVICE_NAME: Final = "pipeline-backfill"
SYSTEM_ACTOR: Final = "pipeline-backfill"
ROW_KEYS: Final = frozenset({"source", "since", "until", "refs", "limit", "max_documents", "note"})
FUNNEL: Final = (
    ("stored", None),
    ("parsed", None),
    ("unparsed", DocumentStatus.FAILED),
    ("irrelevant", DocumentStatus.IRRELEVANT),
    ("classified", DocumentStatus.CLASSIFIED),
    ("triage", DocumentStatus.TRIAGE),
    ("reference", DocumentStatus.REFERENCE),
    ("extracted", DocumentStatus.EXTRACTED),
)


class PlanError(ValueError):
    """The plan file is not a list of rows the backfill can run."""


def load_plan(path: Path) -> list[BackfillRow]:
    """The rows of the plan file at ``path``, in order."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PlanError(f"{path}: {exc}") from exc
    rows = data.get("rows") if isinstance(data, Mapping) else None
    if not isinstance(rows, list) or not rows:
        raise PlanError(f"{path}: a plan holds a non-empty list of rows under 'rows'")
    return [_row(path, index, item) for index, item in enumerate(rows, start=1)]


def _row(path: Path, index: int, item: object) -> BackfillRow:
    where = f"{path} row {index}"
    if not isinstance(item, Mapping):
        raise PlanError(f"{where}: not a mapping")
    unknown = sorted(set(item) - ROW_KEYS)
    if unknown:
        raise PlanError(f"{where}: unknown keys {', '.join(map(str, unknown))}")
    refs = item.get("refs") or []
    if not isinstance(refs, list) or not all(isinstance(ref, str) for ref in refs):
        raise PlanError(f"{where}: refs is a list of references")
    try:
        return BackfillRow(
            source_key=str(item.get("source", "")),
            since=_date(item.get("since"), "since"),
            until=None if item.get("until") is None else _date(item.get("until"), "until"),
            refs=tuple(refs),
            limit=int(item.get("limit", 50)),
            max_documents=None if item.get("max_documents") is None else int(item["max_documents"]),
            note=str(item.get("note", "")).strip(),
        )
    except (ValueError, TypeError) as exc:
        raise PlanError(f"{where}: {exc}") from exc


def _date(value: object, name: str) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ValueError(f"{name} must be a date (YYYY-MM-DD)")


# ---------------------------------------------------------------- what the modes print


def render_dry_run(listings: Sequence[RowListing]) -> str:
    lines = [
        "# Backfill dry run: each row listed, nothing fetched",
        "",
        "| Row | Window | Listed | Known | New | First new |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for index, listing in enumerate(listings, start=1):
        if listing.error:
            lines.append(f"| {index} | {listing.row.describe()} | failed: {listing.error} | | | |")
            continue
        lines.append(
            f"| {index} | {listing.row.describe()} | {listing.listed} | {listing.known} | "
            f"{listing.new} | {', '.join(listing.sample) or '-'} |"
        )
    new = sum(listing.new for listing in listings)
    lines += ["", f"{new} document(s) new to the store; nothing was fetched or written."]
    return "\n".join(lines) + "\n"


def dry_run_json(listings: Sequence[RowListing]) -> list[dict[str, Any]]:
    return [
        {
            "row": index,
            "source": listing.row.source_key,
            "window": listing.row.describe(),
            "listed": listing.listed,
            "known": listing.known,
            "new": listing.new,
            "first_new": list(listing.sample),
            "error": listing.error or None,
        }
        for index, listing in enumerate(listings, start=1)
    ]


def render_round(row: BackfillRow, outcome: CrawlOutcome) -> str:
    return (
        f"{row.source_key}: crawl {outcome.workflow_id} {outcome.status}: listed "
        f"{outcome.listed}, stored {outcome.stored}, duplicates {outcome.duplicates}, failed "
        f"{outcome.failed}, left for later {outcome.deferred}"
        + (f" ({outcome.error})" if outcome.error else "")
        + "\n"
    )


def _print_round(row: BackfillRow, outcome: CrawlOutcome) -> None:
    sys.stdout.write(render_round(row, outcome))
    sys.stdout.flush()


def render_runs(runs: Sequence[RowRun]) -> str:
    lines = ["", "| Row | Window | Crawls | Stored | Stopped |", "| --- | --- | --- | --- | --- |"]
    for index, run in enumerate(runs, start=1):
        lines.append(
            f"| {index} | {run.row.describe()} | {len(run.rounds)} | {run.stored} | {run.stopped} |"
        )
    return "\n".join(lines) + "\n"


def render_report(funnel: BackfillFunnel) -> str:
    header = " | ".join(name.capitalize() for name, _ in FUNNEL)
    lines = [
        f"# Backfill report ({funnel.prompt_version})",
        "",
        f"| Source | {header} | Candidates | Unparseable |",
        "| --- | " + " | ".join("---" for _ in FUNNEL) + " | --- | --- |",
    ]
    for source in funnel.sources:
        counts = [
            str(source.tally.stored if name == "stored" else source.tally.parsed)
            if status is None
            else str(source.at(status))
            for name, status in FUNNEL
        ]
        lines.append(
            f"| {source.source_key} | {' | '.join(counts)} | {source.candidates} | "
            f"{source.unparseable} |"
        )
    share = funnel.unparsed_share
    lines += [
        "",
        f"Unparsed: {funnel.unparsed} of {funnel.stored} stored"
        + ("" if share is None else f" ({share:.1%})")
        + "; no parser read them, and each waits for a manual parse.",
    ]
    if funnel.acceptance:
        accepted = funnel.acceptance
        rate = accepted.get("acceptance_rate")
        lines.append(
            f"Acceptance: {accepted.get('decided', 0)} candidate(s) decided, "
            f"{accepted.get('approved', 0)} approved ({accepted.get('approved_without_edits', 0)} "
            f"without edits), {accepted.get('rejected', 0)} rejected; acceptance rate "
            + ("-" if not isinstance(rate, int | float) else f"{rate:.1%}")
        )
    else:
        lines.append(f"Acceptance: unavailable ({funnel.acceptance_error})")
    return "\n".join(lines) + "\n"


def report_json(funnel: BackfillFunnel) -> dict[str, Any]:
    return {
        "prompt_version": funnel.prompt_version,
        "sources": [
            {
                "source": source.source_key,
                **{
                    name: (source.tally.stored if name == "stored" else source.tally.parsed)
                    if status is None
                    else source.at(status)
                    for name, status in FUNNEL
                },
                "candidates": source.candidates,
                "unparseable": source.unparseable,
            }
            for source in funnel.sources
        ],
        "stored": funnel.stored,
        "unparsed": funnel.unparsed,
        "unparsed_share": funnel.unparsed_share,
        "acceptance": dict(funnel.acceptance) or None,
        "acceptance_error": funnel.acceptance_error or None,
    }


# ---------------------------------------------------------------- the plan's modes


@dataclass(frozen=True, slots=True)
class Wiring:
    """What the plan's modes run on; tests hand in memory ones and fakes."""

    settings: PipelineSettings
    units: UnitOfWorkFactory
    types: AdapterTypes
    catalog: Callable[[], SourceCatalog]
    starter: CrawlStarter
    watcher: CrawlWatcher
    stats: CandidateStats | None


def run_plan(args: argparse.Namespace, wiring: Wiring) -> int:
    try:
        rows = load_plan(args.plan)
    except PlanError as exc:
        sys.stderr.write(f"{SERVICE_NAME}: {exc}\n")
        return 2
    if args.row is not None:
        if not 1 <= args.row <= len(rows):
            sys.stderr.write(f"{SERVICE_NAME}: the plan has rows 1 to {len(rows)}\n")
            return 2
        rows = [rows[args.row - 1]]
    if args.report:
        return _report(args, wiring, rows)
    if args.dry_run:
        return _dry_run(args, wiring, rows)
    return _workflow(args, wiring, rows)


def _dry_run(args: argparse.Namespace, wiring: Wiring, rows: Sequence[BackfillRow]) -> int:
    try:
        listings = PlanDryRun(wiring.units, wiring.catalog()).run(rows)
    except Exception as exc:
        sys.stderr.write(f"{SERVICE_NAME}: cannot read the store: {type(exc).__name__}: {exc}\n")
        return 2
    if args.json:
        sys.stdout.write(json.dumps(dry_run_json(listings), indent=2) + "\n")
    else:
        sys.stdout.write(render_dry_run(listings))
    return 1 if any(listing.error for listing in listings) else 0


def _workflow(args: argparse.Namespace, wiring: Wiring, rows: Sequence[BackfillRow]) -> int:
    if not wiring.settings.pipeline_crawl_enabled:
        sys.stderr.write(
            f"{SERVICE_NAME}: refused: CW_PIPELINE_CRAWL_ENABLED is off; a backfill fetches from "
            "the live regulator sites through the worker, so turn crawling on for it first\n"
        )
        return 2
    if not args.reason or len(args.reason.strip()) < 10:
        sys.stderr.write(f"{SERVICE_NAME}: --workflow needs --reason of ten characters or more\n")
        return 2
    actor = (
        AuditActor.system(SYSTEM_ACTOR)
        if args.actor_id is None
        else AuditActor.user(UserId(args.actor_id))
    )
    start = StartBackfill(wiring.units, wiring.starter, types=wiring.types, enabled=True)
    runs = RunBackfill(start, wiring.watcher, max_rounds=args.max_rounds).run(
        rows,
        BackfillRequest(actor=actor, reason=args.reason.strip()),
        progress=_print_round,
    )
    sys.stdout.write(render_runs(runs))
    failed = any(not run.rounds or run.rounds[-1].status != "completed" for run in runs)
    return 1 if failed else 0


def _report(args: argparse.Namespace, wiring: Wiring, rows: Sequence[BackfillRow]) -> int:
    try:
        funnel = BackfillReport(wiring.units, wiring.stats).run(
            sorted({row.source_key for row in rows})
        )
    except Exception as exc:
        sys.stderr.write(f"{SERVICE_NAME}: cannot read the store: {type(exc).__name__}: {exc}\n")
        return 2
    if args.json:
        sys.stdout.write(json.dumps(report_json(funnel), indent=2) + "\n")
    else:
        sys.stdout.write(render_report(funnel))
    return 0


# ---------------------------------------------------------------- the legacy backfill


@dataclass(frozen=True, slots=True)
class BackfillResult:
    listed: int
    fetched: int
    parsed: int
    unparsed: int
    failed: int


@dataclass(frozen=True, slots=True)
class Ingested:
    discovered: DiscoveredDocument
    raw: RawDocument
    uri: str
    parsed: ParsedDocument | None
    detection: Detection | None


def ingest(
    adapter: SourceAdapter,
    parsers: Sequence[DocumentParser],
    store: RawStore,
    *,
    source_key: str,
    since: datetime,
    default_type: DocumentType,
    limit: int | None = None,
    list_only: bool = False,
    out: list[str] | None = None,
) -> BackfillResult:
    """The legacy backfill: list, fetch, keep in a local raw store, parse and detect, writing
    nothing to the pipeline's store."""
    listed = fetched = parsed_count = unparsed = failed = 0
    for discovered in adapter.list_documents(since):
        if limit is not None and listed >= limit:
            break
        listed += 1
        if list_only:
            _emit(out, f"{source_key}\t{discovered.published_at}\t-\t{discovered.title[:80]}")
            continue
        try:
            raw = adapter.fetch(discovered.ref)
        except Exception as exc:
            failed += 1
            _emit(out, f"{source_key}\t{discovered.published_at}\tfetch failed\t{exc}")
            continue
        fetched += 1
        uri = store.uri(store.put(raw))
        parser = next((p for p in parsers if p.supports(raw)), None)
        try:
            if parser is None:
                raise UnparsedDocumentError(f"no parser for {raw.media_type}")
            parsed = parser.parse(raw)
        except UnparsedDocumentError as exc:
            unparsed += 1
            _emit(
                out, f"{source_key}\t{discovered.published_at}\t{raw.sha256[:12]}\tunparsed\t{exc}"
            )
            continue
        parsed_count += 1
        detection = detect(parsed, default_type=default_type, own_ref=discovered.ref.external_ref)
        refs = ",".join(detection.references) or "-"
        _emit(
            out,
            f"{source_key}\t{discovered.published_at}\t{raw.sha256[:12]}\t{detection.doc_type.value}"
            f"\t{detection.change_kind.value}\t{refs}\t{uri}",
        )
    return BackfillResult(listed, fetched, parsed_count, unparsed, failed)


def _emit(out: list[str] | None, line: str) -> None:
    if out is None:
        sys.stdout.write(line + "\n")
    else:
        out.append(line)


def run_legacy(args: argparse.Namespace) -> int:
    if args.source not in SOURCES:
        sys.stderr.write(
            f"{SERVICE_NAME}: --legacy needs --source, one of {', '.join(sorted(SOURCES))}\n"
        )
        return 2
    spec = SOURCES[args.source]
    since_day = args.since or date(date.today().year, 1, 1)
    since = datetime.combine(since_day, datetime.min.time(), tzinfo=UTC)
    with PoliteClient(ClientConfig(min_delay_seconds=args.delay)) as client:
        adapter = build_adapter(args.source, client)
        result = ingest(
            adapter,
            parsers_for(spec.doc_type),
            LocalRawStore(args.store),
            source_key=args.source,
            since=since,
            default_type=spec.doc_type,
            limit=args.limit,
            list_only=args.list_only,
        )
    sys.stdout.write(
        f"{args.source}: listed {result.listed}, fetched {result.fetched}, parsed {result.parsed}, "
        f"unparsed {result.unparsed}, failed {result.failed}\n"
    )
    return 1 if result.failed and not result.fetched else 0


# ---------------------------------------------------------------- the command


def parser() -> argparse.ArgumentParser:
    found = argparse.ArgumentParser(prog=SERVICE_NAME, description=__doc__.split("\n\n")[0])
    found.add_argument(
        "--plan", type=Path, help="the plan file, such as services/pipeline/backfill-plan.yaml"
    )
    modes = found.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true", help="list each row; fetch nothing")
    modes.add_argument("--workflow", action="store_true", help="crawl each row through the worker")
    modes.add_argument("--report", action="store_true", help="where the documents got to")
    modes.add_argument("--legacy", action="store_true", help="the old fetch into a local raw store")
    found.add_argument("--row", type=int, default=None, help="only this row of the plan, from 1")
    found.add_argument("--max-rounds", type=int, default=DEFAULT_MAX_ROUNDS, help="crawls per row")
    found.add_argument("--reason", default="", help="why: kept in each crawl's audit row")
    found.add_argument("--actor-id", type=UUID, default=None, help="the person the audit names")
    found.add_argument("--json", action="store_true", help="print JSON (dry run, report)")
    found.add_argument("--source", choices=sorted(SOURCES), help="(legacy) the source")
    found.add_argument("--since", type=date.fromisoformat, default=None, help="(legacy) from")
    found.add_argument("--store", type=Path, default=Path("var/raw"), help="(legacy) raw store")
    found.add_argument("--limit", type=int, default=None, help="(legacy) documents at most")
    found.add_argument("--list-only", action="store_true", help="(legacy) list, fetch nothing")
    found.add_argument(
        "--delay", type=float, default=ClientConfig().min_delay_seconds, help="(legacy) delay"
    )
    return found


def run(argv: Sequence[str] | None, wiring: Callable[[], Wiring]) -> int:
    args = parser().parse_args(argv)
    if args.legacy:
        return run_legacy(args)
    if args.plan is None or not (args.dry_run or args.workflow or args.report):
        parser().error("name --plan with one of --dry-run, --workflow, --report (or --legacy)")
    if args.max_rounds < 1:
        parser().error("--max-rounds must be at least 1")
    return run_plan(args, wiring())


def wired() -> Wiring:
    settings = PipelineSettings(service_name=SERVICE_NAME)
    units = unit_of_work_of(settings)
    crawls = TemporalCrawls(settings)
    token = settings.rulebook_write_token
    return Wiring(
        settings=settings,
        units=units,
        types=RegistryAdapterTypes(),
        catalog=lambda: StoreCatalog(units, PoliteClient(ClientConfig())),
        starter=crawls,
        watcher=crawls,
        stats=HttpRulebook(
            settings.rulebook_url,
            token=None if token is None else token.get_secret_value(),
            auth=service_auth_from(settings),
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    return run(argv, wired)


if __name__ == "__main__":
    raise SystemExit(main())
