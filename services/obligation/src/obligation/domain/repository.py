"""What the application layer needs from persistence, as protocols the infrastructure implements."""

from collections.abc import Sequence
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Protocol

from domain_kernel.events import DomainEvent
from domain_kernel.ids import BusinessId, ObligationId, RuleVersionId, TenantId
from obligation.domain.history import ObligationChange
from obligation.domain.model import Obligation
from obligation.domain.reminders import Reminder


class ObligationRepository(Protocol):
    """Reads and writes are scoped to the tenant the unit of work was opened for."""

    def get(self, obligation_id: ObligationId) -> Obligation | None: ...

    def find(
        self, business_id: BusinessId, rule_version_id: RuleVersionId, period_label: str | None
    ) -> Obligation | None: ...

    def open_for_rule_version(
        self,
        rule_version_id: RuleVersionId,
        period_label: str | None = None,
        *,
        business_id: BusinessId | None = None,
    ) -> Sequence[Obligation]:
        """Open obligations of the rule version, of one period and one business when given,
        by period start (none first), creation and id."""
        ...

    def open_due_between(self, due_after: datetime, due_before: datetime) -> Sequence[Obligation]:
        """Open obligations due at or after ``due_after`` and before ``due_before``, by due
        date and id: what the reminder sweep looks at."""
        ...

    def list_for_business(
        self,
        business_id: BusinessId,
        *,
        due_after: datetime | None,
        due_before: datetime | None,
        rule_version_id: RuleVersionId | None,
        limit: int,
    ) -> Sequence[Obligation]:
        """The business's obligations in any status, due at or after ``due_after`` and before
        ``due_before`` (one without a due date only when neither is given), ordered by due date
        (none last), period start, creation and id, at most ``limit``."""
        ...

    def add(self, obligation: Obligation) -> None: ...

    def save(self, obligation: Obligation) -> None: ...


class EventSink(Protocol):
    """Where events go inside the transaction: the outbox."""

    def publish(self, event: DomainEvent) -> None: ...


class ChangeLog(Protocol):
    """The append-only change log of the tenant's obligations: one record per change event."""

    def append(self, change: ObligationChange) -> None: ...

    def for_obligation(self, obligation_id: ObligationId) -> Sequence[ObligationChange]:
        """The obligation's changes, oldest first."""
        ...


class ReminderLog(Protocol):
    """The reminders sent for the tenant's obligations, one per obligation, due date and
    threshold."""

    def for_obligation(self, obligation_id: ObligationId) -> Sequence[Reminder]:
        """The obligation's reminders, oldest first."""
        ...

    def add(self, reminder: Reminder) -> None: ...


class TenantDirectory(Protocol):
    """The tenants that have obligations, read across tenants; each call is a transaction of
    its own. Only ids: what a sweep needs to open one unit of work per tenant."""

    def tenants(self) -> Sequence[TenantId]: ...


class UnitOfWork(Protocol):
    """One transaction: the repository, the event sink and the change log commit or roll back
    together. The factory returns it as a context manager; leaving the block cleanly commits."""

    @property
    def obligations(self) -> ObligationRepository: ...

    @property
    def events(self) -> EventSink: ...

    @property
    def history(self) -> ChangeLog: ...

    @property
    def reminders(self) -> ReminderLog: ...


class UnitOfWorkFactory(Protocol):
    def __call__(self, tenant_id: TenantId) -> AbstractContextManager[UnitOfWork]: ...
