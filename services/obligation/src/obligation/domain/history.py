"""The change log of an obligation: one record per event that changed it (ADR-015, every change
writes an audit row).

A change is derived from the event the use case publishes and the obligation as it stands
after the change, and is written in the same transaction as the event's outbox row, so the
history and the published events never disagree. The record's id is the event's id. Records
are never updated or deleted; the table refuses both outside a tenant's erasure.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import assert_never

from domain_kernel._validation import require_aware, require_instance
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import (
    BusinessId,
    CorrelationId,
    EventId,
    ObligationId,
    RuleVersionId,
    TenantId,
    UserId,
)
from domain_kernel.status import ClosureReason, ObligationStatus
from obligation.domain.events import (
    ObligationClosed,
    ObligationCreated,
    ObligationRescheduled,
    RescheduleReason,
)
from obligation.domain.model import Obligation


class ChangeKind(StrEnum):
    CREATED = "created"
    RESCHEDULED = "rescheduled"
    CLOSED = "closed"


type ObligationEvent = ObligationCreated | ObligationRescheduled | ObligationClosed

_REASONS: dict[ChangeKind, frozenset[str]] = {
    ChangeKind.CREATED: frozenset({""}),
    ChangeKind.RESCHEDULED: frozenset(reason.value for reason in RescheduleReason),
    ChangeKind.CLOSED: frozenset(reason.value for reason in ClosureReason),
}


@dataclass(frozen=True, slots=True, kw_only=True)
class ObligationChange:
    """What one event did to one obligation. ``reason`` is the reschedule or closure reason
    ('' for a creation); ``actor`` is the user who closed it, when a user did."""

    id: EventId
    tenant_id: TenantId
    obligation_id: ObligationId
    business_id: BusinessId
    rule_version_id: RuleVersionId
    kind: ChangeKind
    occurred_at: datetime
    previous_due_at: datetime | None
    new_due_at: datetime | None
    status_after: ObligationStatus
    reason: str
    caused_by_rule_version_id: RuleVersionId | None
    actor: UserId | None
    correlation_id: CorrelationId

    def __post_init__(self) -> None:
        require_instance(self.id, EventId, "id")
        require_instance(self.tenant_id, TenantId, "tenant_id")
        require_instance(self.obligation_id, ObligationId, "obligation_id")
        require_instance(self.business_id, BusinessId, "business_id")
        require_instance(self.rule_version_id, RuleVersionId, "rule_version_id")
        kind = require_instance(self.kind, ChangeKind, "kind")
        require_aware(self.occurred_at, "occurred_at")
        for name in ("previous_due_at", "new_due_at"):
            value = getattr(self, name)
            if value is not None:
                require_aware(value, name)
        require_instance(self.status_after, ObligationStatus, "status_after")
        reason = require_instance(self.reason, str, "reason")
        if reason not in _REASONS[kind]:
            raise InvariantViolationError(f"reason {reason!r} does not fit a {kind} change")
        if kind is ChangeKind.RESCHEDULED and (
            self.previous_due_at is None or self.new_due_at is None
        ):
            raise InvariantViolationError("a rescheduled change carries both due dates")
        if self.caused_by_rule_version_id is not None:
            require_instance(
                self.caused_by_rule_version_id, RuleVersionId, "caused_by_rule_version_id"
            )
        if self.actor is not None:
            require_instance(self.actor, UserId, "actor")
        require_instance(self.correlation_id, CorrelationId, "correlation_id")


def change_from_event(event: ObligationEvent, after: Obligation) -> ObligationChange:
    """The change ``event`` records, with ``after`` the obligation once the change is applied.

    The event must be about ``after`` and carry its tenant: a change log row without a tenant
    could not be written under row-level security.
    """
    if event.tenant_id is None:
        raise InvariantViolationError(f"{event.topic} {event.event_id} has no tenant")
    if event.tenant_id != after.tenant_id or event.obligation_id != after.id:
        raise InvariantViolationError(
            f"{event.topic} {event.event_id} is not about obligation {after.id} of its tenant"
        )
    previous_due_at: datetime | None = None
    new_due_at: datetime | None = None
    reason = ""
    caused_by: RuleVersionId | None = None
    actor: UserId | None = None
    match event:
        case ObligationCreated():
            kind = ChangeKind.CREATED
            new_due_at = event.due_at
        case ObligationRescheduled():
            kind = ChangeKind.RESCHEDULED
            previous_due_at, new_due_at = event.previous_due_at, event.new_due_at
            reason = event.reason.value
            caused_by = event.caused_by_rule_version_id
        case ObligationClosed():
            kind = ChangeKind.CLOSED
            reason = event.reason.value
            actor = event.closed_by
        case _:
            assert_never(event)
    return ObligationChange(
        id=event.event_id,
        tenant_id=event.tenant_id,
        obligation_id=event.obligation_id,
        business_id=event.business_id,
        rule_version_id=event.rule_version_id,
        kind=kind,
        occurred_at=event.occurred_at,
        previous_due_at=previous_due_at,
        new_due_at=new_due_at,
        status_after=after.status,
        reason=reason,
        caused_by_rule_version_id=caused_by,
        actor=actor,
        correlation_id=event.correlation_id,
    )
