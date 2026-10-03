"""Reminders of open obligations as their due date nears: when one is due, and the record that
keeps the sweep from sending it twice.

An obligation is reminded at most once per threshold of ``REMINDER_DAYS`` (7, 3 and 1 days
before it is due) for each due date it has. The threshold of a moment is the smallest one that
``days_left`` (whole days until the due date) is within: 5 days left is the 7-day reminder, 2
days left the 3-day one. A sweep that first sees an obligation late sends only the most urgent
reminder, never the ones it missed. A rescheduled obligation has a new due date, so it is
reminded again against that date.

``reminder_index`` counts the obligation's reminders over its life, 1 for the first, and never
repeats: the notification service keys a reminder by obligation and index.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from domain_kernel._validation import require_aware, require_instance, require_int
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import EventId, ObligationId, TenantId

REMINDER_DAYS: tuple[int, ...] = (7, 3, 1)
"""Days before the due date at which an open obligation is reminded."""


def days_left(due_at: datetime, now: datetime) -> int:
    """Whole days from ``now`` until ``due_at``; 0 on the last day, negative once overdue."""
    return (require_aware(due_at, "due_at") - require_aware(now, "now")) // timedelta(days=1)


def threshold_for(left: int, thresholds: Iterable[int] = REMINDER_DAYS) -> int | None:
    """The reminder threshold ``left`` days falls in, or None when it is too early (more days
    than the largest threshold) or too late (overdue)."""
    if left < 0:
        return None
    reached = [days for days in thresholds if left <= days]
    return min(reached) if reached else None


def lookahead(thresholds: Iterable[int] = REMINDER_DAYS) -> timedelta:
    """How far ahead of now a due date can be and still fall in a threshold."""
    return timedelta(days=max(thresholds) + 1)


@dataclass(frozen=True, slots=True)
class Reminder:
    """One reminder sent: its ``id`` is the id of the ``obligation.due_soon`` event."""

    id: EventId
    tenant_id: TenantId
    obligation_id: ObligationId
    due_at: datetime
    threshold_days: int
    reminder_index: int
    sent_at: datetime

    def __post_init__(self) -> None:
        require_instance(self.id, EventId, "id")
        require_instance(self.tenant_id, TenantId, "tenant_id")
        require_instance(self.obligation_id, ObligationId, "obligation_id")
        require_aware(self.due_at, "due_at")
        require_int(self.threshold_days, "threshold_days", minimum=0)
        require_int(self.reminder_index, "reminder_index", minimum=1)
        require_aware(self.sent_at, "sent_at")


def already_reminded(sent: Sequence[Reminder], due_at: datetime, threshold: int) -> bool:
    """True when ``sent`` holds a reminder for ``due_at`` at ``threshold`` or a more urgent one:
    a reminder is never followed by a less urgent one for the same due date."""
    return any(r.due_at == due_at and r.threshold_days <= threshold for r in sent)


def next_index(sent: Sequence[Reminder]) -> int:
    """The ``reminder_index`` of the obligation's next reminder."""
    return max((r.reminder_index for r in sent), default=0) + 1


def validate_thresholds(thresholds: Sequence[int]) -> tuple[int, ...]:
    """``thresholds`` as a tuple, when it names at least one day count and none twice."""
    if not thresholds:
        raise InvariantViolationError("at least one reminder threshold is needed")
    for days in thresholds:
        require_int(days, "reminder threshold", minimum=0)
    if len(set(thresholds)) != len(thresholds):
        raise InvariantViolationError(f"reminder thresholds repeat: {list(thresholds)}")
    return tuple(thresholds)
