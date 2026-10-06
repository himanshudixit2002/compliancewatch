"""``rulebook-golden-export --since 2026-10-01 --out var/golden-export``: the rule candidates
analysts decided since a day, as draft cases of the extraction golden set
(``application.golden_export``), for an analyst to review and copy into ``evals/golden`` by hand.

It writes ``<out>/cases/<case id>.yaml``, one per approved candidate, in the shape
``pipeline-label`` reads (``label_status: draft``, ``labelled_by`` the decider, ``reviewed_by``
empty), and ``<out>/summary.yaml``: the cases, the rejected candidates (the golden shape has no
negative case) and the candidates skipped with why. It refuses an ``--out`` inside
``evals/golden``: only a person moves a case there, after a review. It reads the rulebook at
``CW_DATABASE_URL`` (``make golden-export``). Exit status: 0 written, 1 the store cannot be read,
2 refused.
"""

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any, Final

import yaml

from py_common.settings import Settings
from rulebook.application.golden_export import ExportDecidedCandidates, GoldenExport
from rulebook.domain.repository import KnowledgeUnitOfWorkFactory
from rulebook.infrastructure.knowledge_repository import PostgresKnowledgeUnitOfWorkFactory

SERVICE_NAME: Final = "rulebook-golden-export"
GOLDEN_PARTS: Final = ("evals", "golden")


def case_yaml(content: Mapping[str, Any]) -> str:
    """A case file's text, as ``pipeline-label prepare`` writes one."""
    return yaml.safe_dump(dict(content), sort_keys=False, allow_unicode=True, width=100)


def write_export(export: GoldenExport, out: Path) -> list[Path]:
    """Write the cases and the summary under ``out``; the files written."""
    cases = out / "cases"
    cases.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for case in export.cases:
        path = cases / f"{case.case_id}.yaml"
        path.write_text(case_yaml(case.content), encoding="utf-8")
        written.append(path)
    summary = out / "summary.yaml"
    summary.write_text(case_yaml(export.summary()), encoding="utf-8")
    written.append(summary)
    return written


def inside_golden(out: Path) -> bool:
    """Whether ``out`` is ``evals/golden`` or under it, wherever the repository is."""
    parts = out.resolve().parts
    return any(
        parts[index : index + len(GOLDEN_PARTS)] == GOLDEN_PARTS
        for index in range(len(parts) - len(GOLDEN_PARTS) + 1)
    )


def run(argv: Sequence[str] | None, units: KnowledgeUnitOfWorkFactory | None = None) -> int:
    parser = argparse.ArgumentParser(prog=SERVICE_NAME, description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--since", required=True, type=date.fromisoformat, help="decided on or after this day"
    )
    parser.add_argument("--out", required=True, type=Path, help="the directory to write into")
    parser.add_argument("--json", action="store_true", help="print the summary as JSON")
    args = parser.parse_args(argv)
    if inside_golden(args.out):
        sys.stderr.write(
            f"{SERVICE_NAME}: refused: {args.out} is inside evals/golden; write the drafts "
            "elsewhere and move a case there after an analyst reviewed it\n"
        )
        return 2
    since = datetime.combine(args.since, time(0), tzinfo=UTC)
    try:
        store = units or PostgresKnowledgeUnitOfWorkFactory.from_url(
            Settings(service_name=SERVICE_NAME).database_url
        )
        export = ExportDecidedCandidates(store).run(since)
    except Exception as exc:
        sys.stderr.write(f"{SERVICE_NAME}: cannot read the rulebook: {type(exc).__name__}: {exc}\n")
        return 1
    written = write_export(export, args.out)
    if args.json:
        sys.stdout.write(json.dumps(export.summary(), indent=2) + "\n")
        return 0
    sys.stdout.write(
        f"{len(export.cases)} draft case(s), {len(export.rejections)} rejection(s) listed, "
        f"{len(export.skipped)} skipped, since {args.since.isoformat()}; wrote "
        f"{len(written)} file(s) under {args.out} (label_status draft, nothing reviewed)\n"
    )
    for skipped in export.skipped:
        sys.stdout.write(f"skipped {skipped.candidate_id}: {skipped.why}\n")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
