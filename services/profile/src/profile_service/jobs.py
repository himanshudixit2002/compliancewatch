"""``profile-fy-confirm``: open the financial year confirmation tasks for named tenants.

Runs ``ConfirmFinancialYear`` for each ``--tenant`` (repeatable) and the year of ``--fy``, or the
financial year of today's date in IST. It opens one ``confirm_financial_year`` review task per
entity and per-year attribute with no value for that year, and prints how many it opened. It is
idempotent: a task still open for the same entity, attribute and year is not opened again, so a
rerun opens nothing. It covers one tenant by hand or a short list; the route
``POST /v1/profile/financial-year-confirmations`` does the same for one tenant over HTTP.

    uv run --package compliancewatch-profile profile-fy-confirm --tenant <uuid> [--fy 2026-27]

``CW_PROFILE_STORE`` and ``CW_DATABASE_URL`` pick the store, as for the service.
"""

import argparse
import sys
from collections.abc import Callable, Sequence
from datetime import datetime

import ontology as ontology_package
from domain_kernel.events import utc_now
from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import TenantId
from profile_service.application.attributes import ConfirmFinancialYear, financial_year_in_india
from profile_service.domain.repository import UnitOfWorkFactory
from profile_service.infrastructure.memory import MemoryStore
from profile_service.infrastructure.repository import PostgresUnitOfWorkFactory
from profile_service.settings import ProfileSettings
from py_common.logging import configure_logging

PROG = "profile-fy-confirm"


def _tenant(text: str) -> TenantId:
    try:
        return TenantId.parse(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not a tenant UUID: {text!r}") from exc


def _financial_year(text: str) -> FinancialYear:
    try:
        return FinancialYear.parse(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _unit_of_work(settings: ProfileSettings) -> UnitOfWorkFactory:
    if settings.profile_store == "memory":
        return MemoryStore()
    return PostgresUnitOfWorkFactory.from_url(settings.database_url)


def main(
    argv: Sequence[str] | None = None,
    *,
    confirm: ConfirmFinancialYear | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> int:
    """Exit 0 once every tenant is done; 2 on bad arguments (argparse). ``confirm`` and
    ``clock`` replace the store and the time in tests."""
    parser = argparse.ArgumentParser(
        prog=PROG, description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--tenant",
        action="append",
        required=True,
        type=_tenant,
        metavar="UUID",
        help="tenant to open the tasks for; repeat for several",
    )
    parser.add_argument(
        "--fy",
        type=_financial_year,
        default=None,
        help="financial year such as 2026-27 (default: the current one in IST)",
    )
    args = parser.parse_args(argv)
    settings = ProfileSettings(service_name=PROG)
    configure_logging(service_name=PROG, log_level=settings.log_level)
    use_case = confirm or ConfirmFinancialYear(_unit_of_work(settings), ontology_package.load())
    fy: FinancialYear = args.fy or financial_year_in_india(clock())
    tenants: list[TenantId] = list(dict.fromkeys(args.tenant))
    total = 0
    for tenant in tenants:
        opened = use_case.run(tenant, fy)
        total += len(opened)
        sys.stdout.write(f"{tenant}: {len(opened)} task(s) opened for {fy.label}\n")
    sys.stdout.write(
        f"financial year {fy.label}: {total} task(s) opened for {len(tenants)} tenant(s)\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
