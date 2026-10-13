"""The profile worker: ``python -m profile_service.worker``, locally
``make worker SERVICE=profile``.

``components(settings)`` is what it runs (``py_common.runtime.WorkerComponents``), and what
``cw-mvp worker`` hosts: a consumer in group ``profile.erasure`` of ``tenant.deletion.requested``
(``py_common.erasure``). While the flag ``identity.tenant_erasure`` is off for the tenant it only
logs ``erasure.off``. On, it checks the event with identity (``CW_IDENTITY_URL``, the service's
client with ``erasure:verify``): one identity did not send for the tenant's open deletion request
is refused, audited and dead-lettered at once. Otherwise it deletes the tenant's profile on the
consumer's connection (``infrastructure.erasure.PostgresProfileEraser``: versions, attributes,
review tasks, nodes, idempotency keys and published events) and writes ``tenant.data.erased``
(service profile), its ``tenant.erased`` audit entry and the erased marker, which commit with the
``processed_event`` row. What it cannot process, identity unreachable included, goes to
``tenant.deletion.requested.profile.erasure.dlq`` after the retries.

With the flag ``profile.fy_schedule`` on (``CW_PROFILE_FY_SCHEDULE_ENABLED``, off by default)
it also hosts the periodic job ``profile-fy-schedule`` (``fy_schedule``): once a day at 00:30 IST
it opens the confirm_financial_year tasks of every tenant that has profile nodes for the financial
year of that moment in India, so the tasks appear on 1 April and a tenant onboarded later gets
its year's tasks the next night; a task for the same entity, attribute and year, open or closed,
is never opened twice. The tenants come from ``profile.tenant_directory()``, the directory
function the NOLOGIN role owns, so the job needs no service token and no row-level security
bypass, and each tenant is confirmed in a unit of work of its own. Every run logs
``profile.fy_schedule_run`` (``application.fy_schedule``).

The consumer writes through Postgres, so the worker needs ``CW_PROFILE_STORE=postgres``. The
outbox relay that publishes profile's events runs on its own (``make relay SERVICE=profile``),
or in ``cw-mvp worker``.
"""

from collections.abc import Callable
from datetime import datetime, time
from typing import Final

import ontology as ontology_package
from domain_kernel.events import utc_now
from domain_kernel.ontology import Ontology
from profile_service import __version__
from profile_service.application.attributes import ConfirmFinancialYear
from profile_service.application.fy_schedule import FinancialYearSchedule
from profile_service.domain.repository import TenantDirectory, UnitOfWorkFactory
from profile_service.infrastructure.erasure import PostgresProfileEraser
from profile_service.infrastructure.repository import (
    PostgresTenantDirectory,
    PostgresUnitOfWorkFactory,
)
from profile_service.settings import ProfileSettings
from py_common.erasure import (
    Enabled,
    ErasureVerifier,
    erasure_component,
    erasure_switch,
    verifier_from,
)
from py_common.runtime import (
    IST,
    PeriodicComponent,
    WorkerComponents,
    daily_at,
    run_worker_process,
)

SERVICE: Final = "profile"
SERVICE_NAME: Final = "profile-worker"
FY_SCHEDULE_JOB: Final = "profile-fy-schedule"
FY_SCHEDULE_AT: Final = time(0, 30, tzinfo=IST)
"""00:30 IST: the first run of a financial year is in the night it turns, before anyone looks."""


def fy_schedule(
    settings: ProfileSettings,
    *,
    unit_of_work: UnitOfWorkFactory | None = None,
    directory: TenantDirectory | None = None,
    ontology: Ontology | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> PeriodicComponent | None:
    """The daily financial year schedule while the flag ``profile.fy_schedule`` is on, else
    None. ``unit_of_work``, ``directory``, ``ontology`` and ``clock`` replace the store, the
    directory function, the packaged ontology and the time (tests and journeys)."""
    if not settings.profile_fy_schedule_enabled:
        return None
    if unit_of_work is None or directory is None:
        postgres = PostgresUnitOfWorkFactory.from_url(settings.database_url)
        unit_of_work = unit_of_work or postgres
        directory = directory or PostgresTenantDirectory(postgres.engine)
    schedule = FinancialYearSchedule(
        ConfirmFinancialYear(unit_of_work, ontology or ontology_package.load(), clock=clock),
        directory,
        clock=clock,
    )
    return PeriodicComponent(
        FY_SCHEDULE_JOB, schedule.run, next_run=daily_at(FY_SCHEDULE_AT), clock=clock
    )


def components(
    settings: ProfileSettings,
    *,
    enabled: Enabled | None = None,
    verifier: ErasureVerifier | None = None,
) -> WorkerComponents:
    """The erasure consumer and, with the flag on, the financial year schedule; ``enabled``
    replaces the erasure flag and ``verifier`` identity (tests)."""
    if settings.profile_store != "postgres":
        raise ValueError("the profile worker needs CW_PROFILE_STORE=postgres")
    schedule = fy_schedule(settings)
    return WorkerComponents(
        consumers=(
            erasure_component(
                SERVICE,
                PostgresProfileEraser,
                enabled=enabled or erasure_switch(settings),
                verifier=verifier or verifier_from(settings),
            ),
        ),
        periodic=() if schedule is None else (schedule,),
    )


def main() -> None:
    run_worker_process(ProfileSettings(service_name=SERVICE_NAME), components, version=__version__)


if __name__ == "__main__":
    main()
