"""The change log of an obligation: one record per change (ADR-015, every change writes an audit
row).

Most changes come with the event the use case publishes, and the record is derived from that
event and the obligation as it stands after the change (``change_from_event``): it is written in
the same transaction as the event's outbox row, so the history and the published events never
disagree, and its id is the event's id. A person's changes that publish no event, starting an
obligation and giving it to an assignee or to nobody, are recorded as such (``started_change``,
``assignment_change``) with an id of their own. Records are never updated or deleted; the table
refuses both outside a tenant's erasure.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final, assert_never

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

MAX_NOTE_CHARS: Final = 2_000
"""The longest note a change keeps: what a person said when they made it."""


class ChangeKind(StrEnum):
    CREATED = "created"
    RESCHEDULED = "rescheduled"
    CLOSED = "closed"
    STARTED = "started"
    ASSIGNED = "assigned"
    UNASSIGNED = "unassigned"


type ObligationEvent = ObligationCreated | ObligationRescheduled | ObligationClosed

_REASONS: dict[ChangeKind, frozenset[str]] = {
    ChangeKind.CREATED: frozenset({""}),
    ChangeKind.RESCHEDULED: frozenset(reason.value for reason in RescheduleReason),
    ChangeKind.CLOSED: frozenset(reason.value for reason in ClosureReason),
    ChangeKind.STARTED: frozenset({""}),
    ChangeKind.ASSIGNED: frozenset({""}),
    ChangeKind.UNASSIGNED: frozenset({""}),
}


@dataclass(frozen=True, slots=True, kw_only=True)
class ObligationChange:
    """What one change did to one obligation. ``reason`` is the reschedule or closure reason
    ('' for any other kind); ``actor`` is the user who made the change, when a user did, and
    ``note`` what they said (a waiver's reason). An assignment names the assignee before and
    after: ``assigned`` has a new one, ``unassigned`` had one and has none."""

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
    previous_assignee_id: UserId | None = None
    new_assignee_id: UserId | None = None
    note: str = ""

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
        self._check_assignees(kind)
        note = require_instance(self.note, str, "note")
        if note != note.strip() or len(note) > MAX_NOTE_CHARS:
            raise InvariantViolationError(
                f"note must be stripped and at most {MAX_NOTE_CHARS} characters"
            )

    def _check_assignees(self, kind: ChangeKind) -> None:
        previous, new = self.previous_assignee_id, self.new_assignee_id
        for name, value in (("previous_assignee_id", previous), ("new_assignee_id", new)):
            if value is not None:
                require_instance(value, UserId, name)
        if kind is ChangeKind.ASSIGNED:
            fits = new is not None and new != previous
        elif kind is ChangeKind.UNASSIGNED:
            fits = previous is not None and new is None
        else:
            fits = previous is None and new is None
        if not fits:
            raise InvariantViolationError(f"the assignees do not fit a {kind} change")


def change_from_event(
    event: ObligationEvent, after: Obligation, *, note: str = ""
) -> ObligationChange:
    """The change ``event`` records, with ``after`` the obligation once the change is applied
    and ``note`` what the person who made it said.

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
        note=note,
    )


def started_change(
    after: Obligation,
    *,
    at: datetime,
    actor: UserId | None,
    correlation_id: CorrelationId,
    note: str = "",
) -> ObligationChange:
    """The change of a person starting ``after``: ``started``, with no event behind it."""
    if after.status is not ObligationStatus.IN_PROGRESS:
        raise InvariantViolationError(f"obligation {after.id} is {after.status}, not in progress")
    return _person_change(
        after, ChangeKind.STARTED, at=at, actor=actor, correlation_id=correlation_id, note=note
    )


def assignment_change(
    before: Obligation,
    after: Obligation,
    *,
    at: datetime,
    actor: UserId | None,
    correlation_id: CorrelationId,
) -> ObligationChange:
    """The change of a person giving ``before`` to another assignee, or to nobody."""
    if before.id != after.id:
        raise InvariantViolationError("an assignment changes one obligation")
    kind = ChangeKind.UNASSIGNED if after.assignee_id is None else ChangeKind.ASSIGNED
    return _person_change(
        after,
        kind,
        at=at,
        actor=actor,
        correlation_id=correlation_id,
        previous_assignee_id=before.assignee_id,
        new_assignee_id=after.assignee_id,
    )


def _person_change(
    after: Obligation,
    kind: ChangeKind,
    *,
    at: datetime,
    actor: UserId | None,
    correlation_id: CorrelationId,
    note: str = "",
    previous_assignee_id: UserId | None = None,
    new_assignee_id: UserId | None = None,
) -> ObligationChange:
    return ObligationChange(
        id=EventId.new(),
        tenant_id=after.tenant_id,
        obligation_id=after.id,
        business_id=after.business_id,
        rule_version_id=after.rule_version_id,
        kind=kind,
        occurred_at=at,
        previous_due_at=None,
        new_due_at=None,
        status_after=after.status,
        reason="",
        caused_by_rule_version_id=None,
        actor=actor,
        correlation_id=correlation_id,
        previous_assignee_id=previous_assignee_id,
        new_assignee_id=new_assignee_id,
        note=note,
    )
