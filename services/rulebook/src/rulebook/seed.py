"""``rulebook-seed``: load the seed calendar into the rule tables (``make seed SERVICE=rulebook``).

Reads ``seed/gst_calendar.yaml`` (or ``--file``), checks it against the packaged ontology and
writes draft rule versions through ``SqlAlchemySeedRepository``. ``--check`` only validates.
Every rule stays ``needs_review`` until an analyst reviews it in the workbench.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import ontology as ontology_package
from py_common.logging import configure_logging
from py_common.settings import Settings
from rulebook.application.seed_loader import SeedError, default_seed_path, load_calendar
from rulebook.infrastructure.seed_repository import SqlAlchemySeedRepository


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rulebook-seed", description=__doc__)
    parser.add_argument("--file", type=Path, default=None, help="seed file (default: packaged)")
    parser.add_argument("--check", action="store_true", help="validate only, write nothing")
    args = parser.parse_args(argv)
    settings = Settings(service_name="rulebook-seed")
    configure_logging(service_name="rulebook-seed", log_level=settings.log_level)
    try:
        calendar = load_calendar(ontology_package.load(), args.file or default_seed_path())
    except (OSError, SeedError) as exc:
        problems = getattr(exc, "problems", (str(exc),))
        sys.stderr.write("seed: invalid:\n" + "".join(f"  {p}\n" for p in problems))
        return 1
    recurring = sum(rule.is_recurring for rule in calendar.rules)
    sys.stdout.write(
        f"seed {calendar.version} for ontology {calendar.ontology_version}: "
        f"{len(calendar.rules)} rules ({recurring} recurring), all "
        f"{sorted({rule.seed_status.value for rule in calendar.rules})}\n"
    )
    if args.check:
        return 0
    outcome = SqlAlchemySeedRepository.from_url(settings.database_url).apply(calendar)
    sys.stdout.write(f"seed applied: {outcome.summary}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
