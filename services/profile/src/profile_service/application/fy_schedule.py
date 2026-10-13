"""The April financial year schedule: ``ConfirmFinancialYear`` for every tenant, once the year
has turned (the flag ``profile.fy_schedule``).

On 1 April IST a new financial year starts and every per-year attribute (the turnover band) has
no value for it yet. ``FinancialYearSchedule.run`` names the financial year of the moment it
runs in India (``financial_year_in_india``) and opens the confirmation tasks for every tenant
the ``TenantDirectory`` lists: the tenants that have profile nodes, read through
``profile.tenant_directory()``, a SECURITY DEFINER function owned by the NOLOGIN directory role
(``infra/dev/postgres/roles.sql``), so the job needs no service token and no row-level security
bypass; each tenant is then visited in a unit of work of its own, under its policy. A tenant
whose confirmation fails is logged and the others go on. The worker runs it once a day
(``profile_service.worker``), on and after 1 April, and it is idempotent: a task for the same
entity, attribute and year, open or closed, is not opened again, so the run after the first opens
nothing (``ConfirmFinancialYear``). Each run logs ``profile.fy_schedule_run`` with the year, the
tenants visited, the tasks opened and the failures.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from domain_kernel.events import utc_now
from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import BusinessId, TenantId
from profile_service.application.attributes import ConfirmFinancialYear, financial_year_in_india
from profile_service.domain.repository import TenantDirectory
from py_common.logging import get_logger

log = get_logger(__name__)

OnFailure = Callable[[TenantId, Exception], None]


@dataclass(frozen=True, slots=True)
class ScheduleRun:
    """What one run did: the year it confirmed, the tenants it visited, the tasks it opened and
    the tenants whose confirmation failed."""

    fy: FinancialYear
    tenants: int
    opened: dict[TenantId, tuple[BusinessId, ...]] = field(default_factory=dict)
    failed: tuple[TenantId, ...] = ()

    @property
    def tasks_opened(self) -> int:
        return sum(len(tasks) for tasks in self.opened.values())


class FinancialYearSchedule:
    def __init__(
        self,
        confirm: ConfirmFinancialYear,
        directory: TenantDirectory,
        *,
        clock: Callable[[], datetime] = utc_now,
        on_failure: OnFailure | None = None,
    ) -> None:
        self._confirm = confirm
        self._directory = directory
        self._clock = clock
        self._on_failure = on_failure or _log_failure

    def run(self) -> ScheduleRun:
        fy = financial_year_in_india(self._clock())
        tenants = list(self._directory.tenants())
        opened: dict[TenantId, tuple[BusinessId, ...]] = {}
        failed: list[TenantId] = []
        for tenant in tenants:
            try:
                tasks = self._confirm.run(tenant, fy)
            except Exception as exc:
                failed.append(tenant)
                self._on_failure(tenant, exc)
                continue
            if tasks:
                opened[tenant] = tasks
        run = ScheduleRun(fy, len(tenants), opened, tuple(failed))
        log.info(
            "profile.fy_schedule_run",
            fy=fy.label,
            tenants=run.tenants,
            tenants_with_tasks=len(opened),
            opened=run.tasks_opened,
            failed=len(failed),
        )
        return run


def _log_failure(tenant_id: TenantId, exc: Exception) -> None:
    log.error(
        "profile.fy_schedule_failed",
        tenant_id=str(tenant_id),
        error=f"{type(exc).__name__}: {exc}",
        exc_info=exc,
    )
