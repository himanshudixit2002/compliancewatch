"""``obligation-sweep --once [--now ISO] [--tenant ID]... [--json]``: the reminder sweep and the
rolling window, once.

The worker runs both on schedules (the sweep every hour, the window daily at 02:30 IST) while
``CW_OBLIGATION_SWEEP_ENABLED`` is on. This command runs each once and exits, so an operator, or
the local product's check, sees their effect at once:

- ``--now`` runs them as of another moment, an ISO 8601 date and time with its offset
  (``2026-11-15T10:00:00+05:30``): a reminder goes out as if it were that moment, and the window
  rolls as of that day in India. It is refused (exit 2) unless ``CW_ENV`` is local or test, since
  a reminder sent ahead of its time cannot be taken back.
- ``--tenant`` limits both to the tenants named (repeatable). The local product's check names its
  synthetic tenants, so the other tenants of the shared dev database are left alone.
- ``--json`` prints the report as JSON.

It reads ``CW_*`` as the worker does and needs ``CW_OBLIGATION_STORE=postgres`` and
``CW_DATABASE_URL`` with the obligation schema first on its ``search_path`` (as
``make worker SERVICE=obligation`` sets it). Exit 0 when every tenant's run committed, 1 when a
tenant failed (the others still ran; the error is printed), 2 when the command is refused.
"""

import argparse
import json
import sys
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final, TextIO
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from domain_kernel.events import utc_now
from domain_kernel.ids import TenantId
from obligation.application.reminders import SendDueReminders
from obligation.application.window import RollWindow
from obligation.domain.ports import RuleVersionReader
from obligation.domain.repository import TenantDirectory, UnitOfWorkFactory
from obligation.infrastructure.repository import PostgresTenantDirectory, PostgresUnitOfWorkFactory
from obligation.infrastructure.rulebook_client import HttpRuleVersionReader
from obligation.settings import ObligationSettings
from py_common.auth import service_auth_from
from py_common.logging import configure_logging

PROG: Final = "obligation-sweep"
LOCAL_ENVIRONMENTS: Final = frozenset({"local", "test"})


class RefusedError(Exception):
    """The command must not run as asked; the message says why."""


@dataclass
class SweepReport:
    """What one run did, as of ``now``: tenants visited, reminders published, obligations the
    window made, what the guard refused there, and the tenants that failed with why."""

    now: datetime
    tenants: int = 0
    reminded: list[str] = field(default_factory=list)
    created: list[str] = field(default_factory=list)
    refused: dict[str, int] = field(default_factory=dict)
    failed: dict[str, str] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        return {
            "now": self.now.isoformat(),
            "tenants": self.tenants,
            "reminded": self.reminded,
            "created": self.created,
            "refused": self.refused,
            "failed": self.failed,
        }

    def lines(self) -> list[str]:
        lines = [
            f"{PROG} as of {self.now.isoformat()}: {self.tenants} tenants, "
            f"{len(self.reminded)} reminders, {len(self.created)} obligations made by the window"
        ]
        lines += [f"  guard refused {count}: {reason}" for reason, count in self.refused.items()]
        lines += [f"  failed {tenant}: {error}" for tenant, error in self.failed.items()]
        return lines


def run_once(
    units: UnitOfWorkFactory,
    tenants: TenantDirectory,
    rules: RuleVersionReader,
    *,
    now: datetime,
    only: Collection[TenantId] | None = None,
) -> SweepReport:
    """The reminder sweep, then the rolling window, both as of ``now``, over ``only`` (every
    tenant of the directory when None)."""
    report = SweepReport(now=now)

    def failed(tenant_id: TenantId, exc: Exception) -> None:
        report.failed.setdefault(str(tenant_id), f"{type(exc).__name__}: {exc}")

    swept = SendDueReminders(units, tenants, clock=lambda: now, on_failure=failed).run(only=only)
    rolled = RollWindow(units, tenants, rules, clock=lambda: now, on_failure=failed).run(only=only)
    report.tenants = max(swept.tenants, rolled.tenants)
    report.reminded = [str(obligation) for obligation in swept.reminded]
    report.created = [str(obligation) for obligation in rolled.created]
    report.refused = {reason.value: count for reason, count in rolled.refused}
    return report


def _moment(value: str) -> datetime:
    try:
        moment = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{value!r} is not an ISO 8601 date and time") from exc
    if moment.tzinfo is None:
        raise argparse.ArgumentTypeError(f"{value!r} needs its offset, such as +05:30")
    return moment


def parser() -> argparse.ArgumentParser:
    commands = argparse.ArgumentParser(
        prog=PROG, description="The reminder sweep and the rolling window, once."
    )
    commands.add_argument("--once", action="store_true", help="run both once and exit")
    commands.add_argument(
        "--now",
        type=_moment,
        default=None,
        help="run as of this ISO 8601 moment with its offset (CW_ENV local or test only)",
    )
    commands.add_argument(
        "--tenant", action="append", type=UUID, metavar="ID", help="only this tenant; repeatable"
    )
    commands.add_argument("--json", action="store_true", help="print the report as JSON")
    return commands


def refusal(args: argparse.Namespace, settings: ObligationSettings) -> str | None:
    """Why the command must not run as asked, or None."""
    if not args.once:
        return "the worker runs the sweep and the window on their schedules; pass --once"
    if args.now is not None and settings.env not in LOCAL_ENVIRONMENTS:
        return (
            f"--now sends reminders ahead of their time: it runs only when CW_ENV is local or "
            f"test, not {settings.env}"
        )
    if settings.obligation_store != "postgres":
        return "obligation-sweep needs CW_OBLIGATION_STORE=postgres"
    return None


def main(
    argv: Sequence[str] | None = None,
    *,
    settings: ObligationSettings | None = None,
    rules: RuleVersionReader | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    out, err = stdout or sys.stdout, stderr or sys.stderr
    args = parser().parse_args(argv)
    chosen = settings
    if chosen is None:
        # Run as the command: its own settings and logging. A caller that passes settings, such
        # as the product's check, keeps its own logging.
        chosen = ObligationSettings(service_name=PROG)
        configure_logging(
            service_name=PROG,
            log_level=chosen.log_level,
            json_output=chosen.log_json,
            env=chosen.env,
        )
    refused = refusal(args, chosen)
    if refused is not None:
        err.write(f"{PROG}: refused: {refused}\n")
        return 2
    only = None if not args.tenant else frozenset(TenantId(tenant) for tenant in args.tenant)
    engine = create_engine(chosen.database_url, poolclass=NullPool)
    own: HttpRuleVersionReader | None = None
    reader: RuleVersionReader
    if rules is None:
        own = reader = HttpRuleVersionReader(chosen.rulebook_url, auth=service_auth_from(chosen))
    else:
        reader = rules
    try:
        report = run_once(
            PostgresUnitOfWorkFactory(engine),
            PostgresTenantDirectory(engine),
            reader,
            now=args.now or utc_now(),
            only=only,
        )
    finally:
        if own is not None:
            own.close()
        engine.dispose()
    if args.json:
        out.write(json.dumps(report.as_json(), indent=2) + "\n")
    else:
        out.write("\n".join(report.lines()) + "\n")
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
