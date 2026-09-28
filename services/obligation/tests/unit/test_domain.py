from datetime import timedelta

import pytest

from domain_kernel.errors import InvalidTransitionError, InvariantViolationError
from domain_kernel.ids import ObligationId, RuleVersionId, UserId
from domain_kernel.recurrence import Period, Recurrence
from domain_kernel.status import ClosureReason, ObligationStatus, close_obligation
from obligation.domain.errors import ObligationClosedError, ObligationNotFoundError
from obligation.domain.events import RescheduleReason
from obligation.domain.model import Obligation, due_at_end_of_day, period_matches
from obligation.testing import BUSINESS, DECISION, NOW, TENANT, rule

PERIOD = Recurrence.monthly(20).period_containing(NOW.date())


def obligation(**overrides: object) -> Obligation:
    fields: dict[str, object] = {
        "id": ObligationId.new(),
        "tenant_id": TENANT,
        "business_id": BUSINESS,
        "rule_version_id": rule().rule_version_id,
        "decision_id": DECISION,
        "title": "File GSTR-3B (2026-09)",
        "steps": ("Reconcile", "File"),
        "evidence_type": "filing_acknowledgement",
        "period": PERIOD,
        "due_at": NOW + timedelta(days=22),
        "status": ObligationStatus.OPEN,
        "created_at": NOW,
        "updated_at": NOW,
    }
    fields.update(overrides)
    return Obligation(**fields)  # type: ignore[arg-type]


def test_created_event_carries_the_contract_payload() -> None:
    event = obligation().created_event()
    assert event.topic == "obligation.created"
    assert event.schema_version == "1.0.0"
    assert event.tenant_id == TENANT
    assert event.steps == ("Reconcile", "File")
    assert event.due_at == NOW + timedelta(days=22)


def test_start_reschedule_and_close_move_through_the_kernel_table() -> None:
    started = obligation().start(NOW + timedelta(hours=1))
    assert started.status is ObligationStatus.IN_PROGRESS
    moved, rescheduled = started.reschedule(
        NOW + timedelta(days=30),
        reason=RescheduleReason.DEADLINE_EXTENDED,
        at=NOW + timedelta(hours=2),
        caused_by=RuleVersionId.new(),
    )
    assert moved.due_at == NOW + timedelta(days=30)
    assert rescheduled.previous_due_at == NOW + timedelta(days=22)
    assert rescheduled.reason is RescheduleReason.DEADLINE_EXTENDED
    assert rescheduled.caused_by_rule_version_id is not None
    user = UserId.new()
    done, closed = moved.close(ClosureReason.COMPLETED, at=NOW + timedelta(days=3), by=user)
    assert done.status is ObligationStatus.DONE
    assert done.closed_reason is ClosureReason.COMPLETED
    assert done.closed_by == user
    assert closed.status is ObligationStatus.DONE
    assert closed.closed_at == NOW + timedelta(days=3)
    assert not done.is_open


def test_a_closed_obligation_never_changes_again() -> None:
    done, _ = obligation().close(ClosureReason.WAIVED_BY_USER, at=NOW)
    with pytest.raises(ObligationClosedError, match="waived"):
        done.start(NOW)
    with pytest.raises(ObligationClosedError):
        done.reschedule(NOW, reason=RescheduleReason.MANUAL, at=NOW)
    with pytest.raises(ObligationClosedError):
        done.close(ClosureReason.COMPLETED, at=NOW)
    assert ObligationClosedError.type_slug == "obligation-closed"
    assert ObligationNotFoundError("x").type_slug == "obligation-not-found"


def test_reschedule_needs_a_different_due_date_and_an_existing_one() -> None:
    current = obligation()
    with pytest.raises(InvariantViolationError, match="equals the current due date"):
        current.reschedule(current.due_at, reason=RescheduleReason.MANUAL, at=NOW)  # type: ignore[arg-type]
    with pytest.raises(InvariantViolationError, match="without a due date"):
        obligation(due_at=None).reschedule(NOW, reason=RescheduleReason.MANUAL, at=NOW)


def test_closing_from_in_progress_to_not_applicable_is_allowed_and_terminal() -> None:
    started = obligation().start(NOW)
    done, _ = started.close(ClosureReason.PROFILE_CHANGED, at=NOW)
    assert done.status is ObligationStatus.CLOSED_NOT_APPLICABLE
    assert not done.is_open
    with pytest.raises(ObligationClosedError):
        done.close(ClosureReason.COMPLETED, at=NOW)
    with pytest.raises(InvalidTransitionError):
        close_obligation(ObligationStatus.DONE, ClosureReason.PROFILE_CHANGED)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"title": " "}, "title"),
        ({"steps": ("ok", "")}, "steps"),
        ({"closed_at": NOW}, "exactly when the status is terminal"),
        ({"status": ObligationStatus.DONE}, "exactly when the status is terminal"),
        ({"period": "2026-09"}, "period must be Period"),
    ],
)
def test_invariants(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(InvariantViolationError, match=message):
        obligation(**overrides)


def test_period_helpers() -> None:
    current = obligation()
    assert current.period_label == PERIOD.label
    assert obligation(period=None).period_label is None
    assert period_matches(current, None)
    assert period_matches(current, PERIOD.label)
    assert not period_matches(current, "2026-10")
    assert not period_matches(obligation(period=None), "2026-10")
    other = Period(PERIOD.start, PERIOD.end, "other")
    assert not period_matches(obligation(period=other), PERIOD.label)


def test_due_at_end_of_day() -> None:
    from datetime import timezone

    ist = timezone(timedelta(hours=5, minutes=30))
    due = due_at_end_of_day(NOW.date(), ist)
    assert (due.hour, due.minute, due.second) == (23, 59, 59)
    assert due.tzinfo == ist
    with pytest.raises(InvariantViolationError, match="tzinfo"):
        due_at_end_of_day(NOW.date(), "IST")
