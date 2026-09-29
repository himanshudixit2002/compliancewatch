"""The retention sweep: delete old notifications and empty the values of the ones past a month.

``PurgeExpired.run()`` applies the ``RetentionPolicy``: a notification created more than two
years ago is deleted with its work queue entry, and one created more than 30 days ago that is no
longer pending loses its template values, so that only the record of the delivery stays.

Notifications sit under row-level security, and a unit of work without a tenant sees none of
them. The sweep therefore reads the tenants from the tables without it
(``WorkIndex.tenants()``: every tenant with work entries or registered addresses) and runs one
unit of work per tenant, so each tenant's rows are deleted under its own tenant setting and one
tenant's failure leaves the others' sweep committed. The worker runs it daily at 03:00 IST.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from domain_kernel.events import utc_now
from notification.domain.policy import DEFAULT_RETENTION_POLICY, RetentionPolicy
from notification.domain.repository import UnitOfWorkFactory, WorkIndex


@dataclass(frozen=True, slots=True)
class Swept:
    """What one sweep did: tenants visited, notifications deleted, and values emptied."""

    tenants: int = 0
    purged: int = 0
    stripped: int = 0


class PurgeExpired:
    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        work_index: WorkIndex,
        *,
        policy: RetentionPolicy = DEFAULT_RETENTION_POLICY,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._work_index = work_index
        self._policy = policy
        self._clock = clock

    def run(self) -> Swept:
        now = self._clock()
        purge_before = self._policy.purge_before(now)
        strip_before = self._policy.strip_before(now)
        tenants = purged = stripped = 0
        for tenant_id in self._work_index.tenants():
            with self._unit_of_work(tenant_id) as unit:
                purged += unit.notifications.purge(purge_before)
                stripped += unit.notifications.strip_params(strip_before)
            tenants += 1
        return Swept(tenants, purged, stripped)
