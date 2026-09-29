"""``rulebook-quality``: the data-quality checks over the rulebook (``make data-quality``).

Reads rule versions, citation counts and the relations between rule versions from
``CW_DATABASE_URL`` in a read-only transaction (``CW_DB_SCHEMA`` sets the search path), runs the
checks in ``rulebook.domain.quality`` against the packaged ontology and prints a report, as text
or as JSON with ``--json``: the number of violations per check and up to 10 samples of each.
Exit code 0 means clean, 1 means at least one violation, 2 means the database could not be read.
"""

import argparse
import json
import sys
from collections.abc import Sequence

from sqlalchemy.exc import SQLAlchemyError

import ontology as ontology_package
from py_common.logging import configure_logging
from py_common.settings import Settings
from rulebook.application.quality import QualityReader, RunDataQualityChecks
from rulebook.domain.quality import QualityCheck, QualityReport
from rulebook.infrastructure.quality_reader import SqlQualityReader

SAMPLES = 10
"""Violations printed per check, in the text and in the JSON report."""


def main(argv: Sequence[str] | None = None, *, reader: QualityReader | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rulebook-quality", description=__doc__)
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)
    settings = Settings(service_name="rulebook-quality")
    configure_logging(service_name="rulebook-quality", log_level=settings.log_level)
    try:
        if reader is None:
            reader = SqlQualityReader.from_url(settings.database_url, schema=settings.db_schema)
        report = RunDataQualityChecks(reader, ontology_package.load()).run()
    except SQLAlchemyError as exc:
        sys.stderr.write(f"data quality: cannot read the rulebook: {exc.__class__.__name__}\n")
        return 2
    sys.stdout.write(to_json(report) + "\n" if args.json else to_text(report))
    return 0 if report.ok else 1


def to_json(report: QualityReport) -> str:
    return json.dumps(
        {
            "ok": report.ok,
            "checked": {
                "rule_versions": report.versions_checked,
                "relations": report.relations_checked,
            },
            "checks": [
                {
                    "check": check.value,
                    "violations": len(report.of(check)),
                    "samples": [
                        {"subject": violation.subject, "detail": violation.detail}
                        for violation in report.of(check)[:SAMPLES]
                    ],
                }
                for check in QualityCheck
            ],
        },
        indent=2,
    )


def to_text(report: QualityReport) -> str:
    lines = [
        f"data quality: {report.versions_checked} rule versions, "
        f"{report.relations_checked} relations between rule versions"
    ]
    for check in QualityCheck:
        found = report.of(check)
        lines.append(f"  {check.value}: {'ok' if not found else f'{len(found)} violation(s)'}")
        lines.extend(f"    {v.subject}: {v.detail}" for v in found[:SAMPLES])
        if len(found) > SAMPLES:
            lines.append(f"    ... and {len(found) - SAMPLES} more")
    total = len(report.violations)
    lines.append("data quality: clean" if report.ok else f"data quality: {total} violation(s)")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
