"""Publish an obligation event, write its change log row and its audit entry, in the same unit
of work.

Every use case that changes an obligation calls ``record`` where it used to publish the event
alone, so the outbox row, the change row and the ``audit.event`` row commit or roll back together
(ADR-015: every change writes an audit row). A use case that leaves an obligation as it was, or
skips a closed one, publishes nothing and so records nothing.

The audit entry is ``obligation.created`` (materialised from a decision), ``obligation.rescheduled``
(one per obligation, with the reschedule reason and the rule version that caused it) or
``obligation.closed`` (a withdrawal, a supersession, a profile change, or a person). Its actor is
the request's caller, or ``system:obligation`` for a consumer or a sweep. A person's status change
through the tracking routes writes its own ``obligation.status.*`` entry and passes
``audited=False``, so one action is one entry.

Volume: ``obligation.created`` grows with fan-out, one row per obligation materialised (one per
business, rule and period); a reschedule writes one row per open obligation it moves, and a rule's
withdrawal or supersession, or a profile change, writes one ``obligation.closed`` per open
obligation it closes. All three are bounded by the obligation rows themselves, which is fine for
the MVP; a later change could write one entry per batch instead.
"""

from datetime import datetime
from typing import Final

from domain_kernel.audit import AuditEntry
from obligation.domain.events import ObligationClosed, ObligationCreated, ObligationRescheduled
from obligation.domain.history import ObligationEvent, change_from_event
from obligation.domain.model import Obligation
from obligation.domain.repository import UnitOfWork
from py_common.audit import audit_actor, current_correlation_id

SERVICE: Final = "obligation"
SUBJECT: Final = "obligation"
CREATED_ACTION: Final = "obligation.created"
RESCHEDULED_ACTION: Final = "obligation.rescheduled"
CLOSED_ACTION: Final = "obligation.closed"


def record(
    uow: UnitOfWork,
    event: ObligationEvent,
    after: Obligation,
    *,
    note: str = "",
    audited: bool = True,
) -> None:
    """Publish ``event`` and append the change it made; ``after`` is the changed obligation and
    ``note`` what the person who made the change said. With ``audited`` (the default) the
    change's audit entry is written too."""
    change = change_from_event(event, after, note=note)
    uow.events.publish(event)
    uow.history.append(change)
    if audited:
        uow.audit.write(audit_entry_of(event, after, note=note))


def audit_entry_of(event: ObligationEvent, after: Obligation, *, note: str = "") -> AuditEntry:
    """The audit entry of the change ``event`` made to ``after``."""
    before: dict[str, object] | None
    state: dict[str, object]
    reason = note
    match event:
        case ObligationCreated():
            action, before = CREATED_ACTION, None
            state = {
                "status": after.status.value,
                "due_at": _instant(event.due_at),
                "rule_version_id": str(event.rule_version_id),
                "business_id": str(event.business_id),
                "decision_id": str(event.decision_id),
                "period": None if after.period is None else after.period.label,
            }
        case ObligationRescheduled():
            action = RESCHEDULED_ACTION
            before = {"due_at": _instant(event.previous_due_at)}
            state = {
                "due_at": _instant(event.new_due_at),
                "cause": event.reason.value,
                "caused_by_rule_version_id": None
                if event.caused_by_rule_version_id is None
                else str(event.caused_by_rule_version_id),
            }
            reason = note or event.reason.value
        case ObligationClosed():
            action, before = CLOSED_ACTION, None
            state = {"status": event.status.value, "closed_reason": event.reason.value}
            reason = note or event.reason.value
    return AuditEntry(
        action=action,
        tenant_id=after.tenant_id,
        subject_type=SUBJECT,
        subject_id=str(after.id),
        actor=audit_actor(SERVICE),
        reason=reason,
        before=before,
        after=state,
        occurred_at=event.occurred_at,
        correlation_id=current_correlation_id() or str(event.correlation_id),
    )


def _instant(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()
