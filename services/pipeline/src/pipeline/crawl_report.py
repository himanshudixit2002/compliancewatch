"""``pipeline-crawl-report [--days 30] [--target-hours 6] [--f1-source cbic_notifications]``:
how the crawl did, per source, and the F1 check.

It reads the pipeline's store at ``CW_DATABASE_URL`` (the ``pipeline`` schema) and prints, for
every source (or those ``--source`` names), the crawl runs started in the window and how they
ended, the documents stored and failed, the longest gap between successful listings (from the
window's start up to now) and, where documents carry a publication date, the detection delay
from the start of that day in India to the first fetch (``application.report``). The F1 line
judges ``--f1-source``: met when the source was listed all through the window with no gap above
``--target-hours`` and its last crawl recorded no error. A backfill's runs, and the documents
fetched while one ran, are left out, and so are documents published before the window.
``--json`` prints the same as JSON.

Exit status: 0 when F1 is met, 1 when it is not (or the source is unknown), 2 when the store
cannot be read.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import timedelta
from typing import Any, Final

from pipeline.application.report import (
    DEFAULT_DAYS,
    DEFAULT_TARGET,
    CrawlReport,
    CrawlReportResult,
    SourceReport,
)
from pipeline.settings import PipelineSettings
from pipeline.stores import unit_of_work_of

SERVICE_NAME: Final = "pipeline-crawl-report"
F1_SOURCE: Final = "cbic_notifications"


def hours(span: timedelta | None) -> str:
    return "-" if span is None else f"{span.total_seconds() / 3600:.1f} h"


def render(result: CrawlReportResult, f1: str) -> str:
    lines = [
        f"# Crawl report {result.since:%Y-%m-%d %H:%M} to {result.until:%Y-%m-%d %H:%M} UTC",
        "",
        "| Source | Runs | Completed | Failed | Stored | Failed documents | Longest gap | "
        "Detection (dated, within target, longest, median) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for source in result.sources:
        detection = source.detection
        found = (
            "-"
            if detection is None
            else (
                f"{detection.documents}, {detection.within_target}, "
                f"{hours(detection.longest)}, {hours(detection.median)}"
            )
        )
        switches = "" if source.enabled and not source.paused else " (not crawled)"
        lines.append(
            f"| {source.key}{switches} | {source.runs} | {source.completed} | "
            f"{source.failed_runs} | {source.stored} | {source.failed_documents} | "
            f"{hours(source.longest_gap)} | {found} |"
        )
    lines += ["", f1_line(result, f1)]
    return "\n".join(lines) + "\n"


def f1_line(result: CrawlReportResult, key: str) -> str:
    source = result.source(key)
    target = hours(result.target)
    if source is None:
        return f"F1 {key}: not met (no such source)"
    verdict = "met" if source.meets(result.target) else "not met"
    why = [f"longest gap {hours(source.longest_gap)} against {target}"]
    if source.completed == 0:
        why.append("no crawl listed it")
    if source.last_error:
        why.append(f"last error: {source.last_error}")
    return f"F1 {key}: {verdict} ({'; '.join(why)})"


def as_json(result: CrawlReportResult, f1: str) -> dict[str, Any]:
    def seconds(span: timedelta | None) -> float | None:
        return None if span is None else span.total_seconds()

    def source_json(source: SourceReport) -> dict[str, Any]:
        detection = source.detection
        return {
            "key": source.key,
            "name": source.name,
            "enabled": source.enabled,
            "paused": source.paused,
            "runs": source.runs,
            "completed": source.completed,
            "failed_runs": source.failed_runs,
            "stored": source.stored,
            "duplicates": source.duplicates,
            "failed_documents": source.failed_documents,
            "first_listing": None
            if source.first_listing is None
            else source.first_listing.isoformat(),
            "last_listing": None
            if source.last_listing is None
            else source.last_listing.isoformat(),
            "longest_gap_seconds": seconds(source.longest_gap),
            "last_error": source.last_error,
            "detection": None
            if detection is None
            else {
                "documents": detection.documents,
                "within_target": detection.within_target,
                "longest_seconds": seconds(detection.longest),
                "median_seconds": seconds(detection.median),
            },
            "meets_target": source.meets(result.target),
        }

    checked = result.source(f1)
    return {
        "since": result.since.isoformat(),
        "until": result.until.isoformat(),
        "target_seconds": result.target.total_seconds(),
        "sources": [source_json(source) for source in result.sources],
        "f1": {
            "source": f1,
            "met": checked is not None and checked.meets(result.target),
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=SERVICE_NAME, description=__doc__.split("\n\n")[0])
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="the window, in days")
    parser.add_argument(
        "--target-hours",
        type=float,
        default=DEFAULT_TARGET.total_seconds() / 3600,
        help="the detection target, in hours (6)",
    )
    parser.add_argument("--source", action="append", default=[], help="report this source only")
    parser.add_argument("--f1-source", default=F1_SOURCE, help="the source F1 judges")
    parser.add_argument("--json", action="store_true", help="print JSON")
    args = parser.parse_args(argv)
    if args.days < 1:
        parser.error("--days must be at least 1")
    if args.target_hours <= 0:
        parser.error("--target-hours must be positive")
    settings = PipelineSettings(service_name=SERVICE_NAME)
    try:
        result = CrawlReport(unit_of_work_of(settings)).run(
            days=args.days,
            target=timedelta(hours=args.target_hours),
            keys=tuple(args.source),
        )
    except Exception as exc:
        sys.stderr.write(f"{SERVICE_NAME}: cannot read the store: {type(exc).__name__}: {exc}\n")
        return 2
    if args.json:
        sys.stdout.write(json.dumps(as_json(result, args.f1_source), indent=2) + "\n")
    else:
        sys.stdout.write(render(result, args.f1_source))
    checked = result.source(args.f1_source)
    return 0 if checked is not None and checked.meets(result.target) else 1


if __name__ == "__main__":
    raise SystemExit(main())
