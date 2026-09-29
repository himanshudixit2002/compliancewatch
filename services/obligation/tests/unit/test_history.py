from dataclasses import replace
from datetime import timedelta

import pytest

from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import ObligationId, RuleVersionId, TenantId, UserId
from domain_kernel.recurrence import Recurrence
from domain_kernel.status import ClosureReason, ObligationStatus
from obligation.domain.events import RescheduleReason
from obligation.domain.history import ChangeKind, ObligationChange, change_from_event
from obligation.domain.model import Obligation
from obligation.testing import BUSINESS, DECISION, NOW, TENANT, rule

PERIOD = Recurrence.monthly(20).period_containing(NOW.date())
DUE = NOW + timedelta(days=22)


def obligation() -> Obligation:
    return Obligation(
        id=ObligationId.new(),
        tenant_id=TENANT,
        business_id=BUSINESS,
        rule_version_id=rule().rule_version_id,
        decision_id=DECISION,
        title="File GSTR-3B (2026-09)",
        steps=("Reconcile", "File"),
        evidence_type="filing_acknowledgement",
        period=PERIOD,
        due_at=DUE,
        status=ObligationStatus.OPEN,
        created_at=NOW,
        updated_at=NOW,
    )


def test_created_maps_the_new_due_date_and_no_reason() -> None:
    created = obligation()
    event = created.created_event()
    change = change_from_event(event, created)
    assert change.id == event.event_id
    assert change.kind is ChangeKind.CREATED
    assert (change.tenant_id, change.obligation_id) == (TENANT, created.id)
    assert (change.business_id, change.rule_version_id) == (BUSINESS, created.rule_version_id)
    assert change.occurred_at == NOW
    assert (change.previous_due_at, change.new_due_at) == (None, DUE)
    assert change.status_after is ObligationStatus.OPEN
    assert change.reason == ""
    assert (change.caused_by_rule_version_id, change.actor) == (None, None)
    assert change.correlation_id == event.correlation_id


def test_rescheduled_maps_both_dates_the_reason_and_the_causing_version() -> None:
    amendment = RuleVersionId.new()
    at = NOW + timedelta(hours=1)
    moved, event = obligation().reschedule(
        DUE + timedelta(days=5),
        reason=RescheduleReason.DEADLINE_EXTENDED,
        at=at,
        caused_by=amendment,
    )
    change = change_from_event(event, moved)
    assert change.kind is ChangeKind.RESCHEDULED
    assert change.id == event.event_id
    assert change.occurred_at == at
    assert (change.previous_due_at, change.new_due_at) == (DUE, DUE + timedelta(days=5))
    assert change.reason == "deadline_extended"
    assert change.caused_by_rule_version_id == amendment
    assert change.status_after is ObligationStatus.OPEN
    assert change.actor is None


def test_closed_maps_the_reason_the_status_and_the_actor() -> None:
    user = UserId.new()
    done, event = obligation().close(ClosureReason.COMPLETED, at=NOW, by=user)
    change = change_from_event(event, done)
    assert change.kind is ChangeKind.CLOSED
    assert change.reason == "completed"
    assert change.actor == user
    assert change.status_after is ObligationStatus.DONE
    assert (change.previous_due_at, change.new_due_at) == (None, None)

    withdrawn, by_rule = obligation().close(ClosureReason.RULE_WITHDRAWN, at=NOW)
    change = change_from_event(by_rule, withdrawn)
    assert change.reason == "rule_withdrawn"
    assert change.actor is None
    assert change.status_after is ObligationStatus.CLOSED_NOT_APPLICABLE


def test_an_event_without_a_tenant_is_refused() -> None:
    created = obligation()
    event = replace(created.created_event(), tenant_id=None)
    with pytest.raises(InvariantViolationError, match="no tenant"):
        change_from_event(event, created)


def test_the_event_must_be_about_the_obligation_and_its_tenant() -> None:
    created = obligation()
    with pytest.raises(InvariantViolationError, match="is not about"):
        change_from_event(obligation().created_event(), created)
    with pytest.raises(InvariantViolationError, match="is not about"):
        change_from_event(replace(created.created_event(), tenant_id=TenantId.new()), created)


def test_a_change_holds_a_reason_that_fits_its_kind_and_the_dates_a_reschedule_needs() -> None:
    created = obligation()
    change = change_from_event(created.created_event(), created)
    with pytest.raises(InvariantViolationError, match="does not fit"):
        replace(change, reason="deadline_extended")
    with pytest.raises(InvariantViolationError, match="does not fit"):
        replace(change, kind=ChangeKind.CLOSED, reason="manual")
    with pytest.raises(InvariantViolationError, match="both due dates"):
        replace(change, kind=ChangeKind.RESCHEDULED, reason="manual")
    with pytest.raises(InvariantViolationError, match="timezone-aware"):
        replace(change, new_due_at=DUE.replace(tzinfo=None))
    with pytest.raises(InvariantViolationError, match="actor"):
        replace(change, actor="someone")  # type: ignore[arg-type]
    with pytest.raises(InvariantViolationError, match="caused_by_rule_version_id"):
        replace(change, caused_by_rule_version_id="v2")  # type: ignore[arg-type]
    assert isinstance(change, ObligationChange)
