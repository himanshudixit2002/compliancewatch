"""``pipeline-extract-backlog [--dry-run] [--source KEY] [--limit N] [--concurrency N] [--json]``:
extract the documents that wait as ``classified``.

Turning ``CW_PIPELINE_EXTRACTION_ENABLED`` on extracts what the ingest classifies from then on,
none of the documents it classified while the extraction was off: they wait as ``classified``.
This command counts them per source (``application.backlog``) from the pipeline's store at
``CW_DATABASE_URL``, leaving out the ones already extracted for the current prompt, and, without
``--dry-run``, starts the sweep ``pipeline.extract_backlog`` on Temporal
(``pipeline-extract-backlog-<request>``), which runs each one's extraction as a child, at most
``--concurrency`` (3) at a time, under the id the ingest's own extraction would have, so nothing
is extracted twice. At most ``--limit`` documents (1,000 at most) go into one sweep, the first
fetched first; run it again for the rest. The worker runs the sweep; this command returns once it
started.

It refuses (exit 2) while ``CW_PIPELINE_EXTRACTION_ENABLED`` is off, since the worker's
extraction would then skip every document; ``--dry-run`` only counts, whatever the flag says.
Exit status: 0 counted or started (or nothing waits), 1 when the store or Temporal does not
answer, 2 refused.
"""

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from typing import Any, Final, Protocol
from uuid import UUID, uuid4

from pipeline.application.backlog import MAX_BATCH, Backlog, ExtractionBacklog
from pipeline.application.extraction import RULE_PROMPT_REF
from pipeline.domain.ports import AdapterTypes
from pipeline.domain.repository import UnitOfWorkFactory
from pipeline.infrastructure.adapters import RegistryAdapterTypes
from pipeline.infrastructure.temporal import TemporalBacklog, backlog_payload
from pipeline.settings import PipelineSettings
from pipeline.stores import unit_of_work_of
from pipeline.workflows.extract_backlog import DEFAULT_CONCURRENCY, MAX_CONCURRENCY

SERVICE_NAME: Final = "pipeline-extract-backlog"
FLAG: Final = "CW_PIPELINE_EXTRACTION_ENABLED"


class BacklogStarter(Protocol):
    def start(self, workflow_id: str, payload: dict[str, object]) -> bool: ...


def sweep_workflow_id(request: UUID) -> str:
    """``pipeline-extract-backlog-<request>``: one sweep per run of the command."""
    return f"pipeline-extract-backlog-{request.hex}"


def render(backlog: Backlog, *, enabled: bool) -> str:
    lines = [
        f"# Classified backlog ({RULE_PROMPT_REF})",
        "",
        "| Source | Waiting |",
        "| --- | --- |",
    ]
    lines += [f"| {key} | {count} |" for key, count in sorted(backlog.waiting.items())]
    lines += [
        "",
        f"{backlog.total} document(s) wait as classified; the extraction is "
        f"{'on' if enabled else f'off ({FLAG})'}.",
    ]
    return "\n".join(lines) + "\n"


def as_json(backlog: Backlog, *, enabled: bool, workflow_id: str | None) -> dict[str, Any]:
    return {
        "prompt_version": RULE_PROMPT_REF,
        "waiting": dict(sorted(backlog.waiting.items())),
        "total": backlog.total,
        "extraction_enabled": enabled,
        "sweep": None
        if workflow_id is None
        else {"workflow_id": workflow_id, "documents": len(backlog.requests)},
    }


def run(
    argv: Sequence[str] | None,
    *,
    settings: PipelineSettings,
    units: UnitOfWorkFactory,
    types: AdapterTypes,
    starter: BacklogStarter,
    request_ids: Callable[[], UUID] = uuid4,
) -> int:
    parser = argparse.ArgumentParser(prog=SERVICE_NAME, description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="count per source; start nothing")
    parser.add_argument("--source", default=None, help="only this source's documents")
    parser.add_argument("--limit", type=int, default=MAX_BATCH, help="documents per sweep")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help=f"extractions at once, 1 to {MAX_CONCURRENCY}",
    )
    parser.add_argument("--json", action="store_true", help="print JSON")
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= MAX_BATCH:
        parser.error(f"--limit must be 1 to {MAX_BATCH}")
    if not 1 <= args.concurrency <= MAX_CONCURRENCY:
        parser.error(f"--concurrency must be 1 to {MAX_CONCURRENCY}")
    enabled = settings.pipeline_extraction_enabled
    try:
        backlog = ExtractionBacklog(units, types).run(source_key=args.source, limit=args.limit)
    except Exception as exc:
        sys.stderr.write(f"{SERVICE_NAME}: cannot read the store: {type(exc).__name__}: {exc}\n")
        return 1
    workflow_id: str | None = None
    if not args.dry_run:
        if not enabled:
            sys.stderr.write(
                f"{SERVICE_NAME}: refused: {FLAG} is off (flag pipeline.extraction), so the "
                "worker would skip every extraction; turn it on for the worker and here, or "
                "count with --dry-run\n"
            )
            return 2
        if backlog.requests:
            workflow_id = sweep_workflow_id(request_ids())
            payload = backlog_payload(
                [request.model_dump(mode="json") for request in backlog.requests],
                args.concurrency,
            )
            try:
                starter.start(workflow_id, payload)
            except Exception as exc:
                sys.stderr.write(f"{SERVICE_NAME}: the sweep did not start: {exc}\n")
                return 1
    if args.json:
        sys.stdout.write(
            json.dumps(as_json(backlog, enabled=enabled, workflow_id=workflow_id), indent=2) + "\n"
        )
        return 0
    sys.stdout.write(render(backlog, enabled=enabled))
    if workflow_id is not None:
        sys.stdout.write(
            f"started {workflow_id}: {len(backlog.requests)} document(s), "
            f"{args.concurrency} at a time; the worker runs it (Temporal UI)\n"
        )
    elif not args.dry_run:
        sys.stdout.write("nothing waits: no sweep started\n")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    settings = PipelineSettings(service_name=SERVICE_NAME)
    return run(
        argv,
        settings=settings,
        units=unit_of_work_of(settings),
        types=RegistryAdapterTypes(),
        starter=TemporalBacklog(settings),
    )


if __name__ == "__main__":
    raise SystemExit(main())
