"""The reminder sweep: publish ``obligation.due_soon`` for open obligations whose due date is
near, once per obligation, due date and threshold (``domain.reminders``).

Obligations sit under row-level security, and a unit of work without a tenant sees none of
them. The sweep therefore reads the tenants from the tenant directory (``TenantDirectory``: ids
only, readable across tenants) and runs one unit of work per tenant, so each tenant's
obligations are read, and its reminders recorded, under its own tenant setting. In that unit
every open obligation due within the largest threshold (and not yet overdue) is looked at: when
its ``days_left`` falls in a threshold it has not been reminded at for its current due date, the
event goes to the outbox and the reminder row is written in the same transaction, so a repeated
sweep, or a second worker, never publishes it twice.

A tenant whose unit fails is rolled back alone: the sweep reports it to ``on_failure`` and goes
on with the next tenant, and the next sweep tries it again. ``run(only=...)`` visits only the
tenants named, as ``obligation-sweep --tenant`` does.
"""

from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from datetime import datetime

from domain_kernel.events import utc_now
from domain_kernel.ids import ObligationId, TenantId
from obligation.domain.events import ObligationDueSoon
from obligation.domain.reminders import (
    REMINDER_DAYS,
    Reminder,
    already_reminded,
    days_left,
    lookahead,
    next_index,
    threshold_for,
    validate_thresholds,
)
from obligation.domain.repository import TenantDirectory, UnitOfWork, UnitOfWorkFactory

FailureHandler = Callable[[TenantId, Exception], None]


@dataclass(frozen=True, slots=True)
class Swept:
    """What one sweep did: tenants visited, reminders published, and the tenants that
    failed."""

    tenants: int = 0
    reminded: tuple[ObligationId, ...] = ()
    failed: tuple[TenantId, ...] = ()


class SendDueReminders:
    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        tenants: TenantDirectory,
        *,
        thresholds: Sequence[int] = REMINDER_DAYS,
        clock: Callable[[], datetime] = utc_now,
        on_failure: FailureHandler | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._tenants = tenants
        self._thresholds = validate_thresholds(thresholds)
        self._clock = clock
        self._on_failure = on_failure

    def run(self, *, only: Collection[TenantId] | None = None) -> Swept:
        now = self._clock()
        visited = 0
        reminded: list[ObligationId] = []
        failed: list[TenantId] = []
        for tenant_id in self._tenants.tenants():
            if only is not None and tenant_id not in only:
                continue
            visited += 1
            try:
                with self._unit_of_work(tenant_id) as uow:
                    published = self._remind(uow, tenant_id, now)
                reminded.extend(published)  # committed: the unit closed cleanly
            except Exception as exc:
                failed.append(tenant_id)
                if self._on_failure is None:
                    raise
                self._on_failure(tenant_id, exc)
        return Swept(visited, tuple(reminded), tuple(failed))

    def _remind(self, uow: UnitOfWork, tenant_id: TenantId, now: datetime) -> list[ObligationId]:
        reminded: list[ObligationId] = []
        for obligation in uow.obligations.open_due_between(now, now + lookahead(self._thresholds)):
            due_at = obligation.due_at
            if due_at is None:  # pragma: no cover - the query only returns dated obligations
                continue
            left = days_left(due_at, now)
            threshold = threshold_for(left, self._thresholds)
            sent = uow.reminders.for_obligation(obligation.id)
            if threshold is None or already_reminded(sent, due_at, threshold):
                continue
            event = ObligationDueSoon(
                tenant_id=tenant_id,
                occurred_at=now,
                obligation_id=obligation.id,
                business_id=obligation.business_id,
                rule_version_id=obligation.rule_version_id,
                title=obligation.title,
                due_at=due_at,
                days_left=left,
                reminder_index=next_index(sent),
            )
            uow.events.publish(event)
            uow.reminders.add(
                Reminder(
                    id=event.event_id,
                    tenant_id=tenant_id,
                    obligation_id=obligation.id,
                    due_at=due_at,
                    threshold_days=threshold,
                    reminder_index=event.reminder_index,
                    sent_at=now,
                )
            )
            reminded.append(obligation.id)
        return reminded
