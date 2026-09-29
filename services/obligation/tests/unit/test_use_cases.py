from datetime import date, timedelta

import pytest

from domain_kernel.ids import ObligationId, RuleVersionId, UserId
from domain_kernel.recurrence import Recurrence
from domain_kernel.status import ClosureReason, ObligationStatus
from obligation.application.audit import record
from obligation.application.changes import (
    ApplyDeadlineChange,
    CloseObligation,
    DeadlineChange,
    WithdrawRule,
)
from obligation.application.materialise import (
    IST,
    MaterialiseObligations,
    MaterialiseRequest,
)
from obligation.domain.errors import ObligationClosedError, ObligationNotFoundError
from obligation.domain.events import (
    ObligationClosed,
    ObligationCreated,
    ObligationRescheduled,
    RescheduleReason,
)
from obligation.domain.history import ChangeKind
from obligation.infrastructure.memory import MemoryStore
from obligation.testing import BUSINESS, DECISION, NOW, OTHER_TENANT, TENANT, clock, rule

AS_OF = date(2026, 9, 28)


def request(**overrides: object) -> MaterialiseRequest:
    fields: dict[str, object] = {
        "tenant_id": TENANT,
        "business_id": BUSINESS,
        "decision_id": DECISION,
        "rule": rule(),
        "as_of": AS_OF,
    }
    fields.update(overrides)
    return MaterialiseRequest(**fields)  # type: ignore[arg-type]


def test_recurring_rule_creates_one_obligation_per_period_in_the_window() -> None:
    store = MemoryStore()
    result = MaterialiseObligations(store, window=2, clock=clock).run(request())
    assert len(result.created) == 2
    assert (result.existing, result.skipped_before_effective) == (0, 0)
    created = store.of_tenant(TENANT)
    assert [o.period_label for o in created] == ["2026-09", "2026-10"]
    assert [o.title for o in created] == ["File GSTR-3B (2026-09)", "File GSTR-3B (2026-10)"]
    september = created[0]
    assert september.due_at is not None
    assert september.due_at.astimezone(IST).isoformat() == "2026-10-20T23:59:59+05:30"
    assert september.status is ObligationStatus.OPEN
    assert september.created_at == NOW
    assert [type(e).__name__ for e in store.events] == ["ObligationCreated"] * 2
    first = store.events[0]
    assert isinstance(first, ObligationCreated)
    assert first.tenant_id == TENANT
    assert first.obligation_id == september.id


def test_materialise_is_idempotent_and_rolls_the_window() -> None:
    store = MemoryStore()
    the_rule = rule()
    use_case = MaterialiseObligations(store, window=2, clock=clock)
    use_case.run(request(rule=the_rule))
    again = use_case.run(request(rule=the_rule))
    assert again.created == ()
    assert again.existing == 2
    later = use_case.run(request(rule=the_rule, as_of=date(2026, 10, 5)))
    assert len(later.created) == 1
    assert later.existing == 1
    assert [o.period_label for o in store.of_tenant(TENANT)] == ["2026-09", "2026-10", "2026-11"]
    assert len(store.events) == 3


def test_periods_before_the_rule_is_in_force_are_skipped() -> None:
    store = MemoryStore()
    late_rule = rule(effective_from=date(2026, 10, 1))
    result = MaterialiseObligations(store, window=2, clock=clock).run(request(rule=late_rule))
    assert len(result.created) == 1
    assert result.skipped_before_effective == 1
    assert [o.period_label for o in store.of_tenant(TENANT)] == ["2026-10"]


def test_one_off_rule_creates_a_single_obligation_with_due_in_days() -> None:
    store = MemoryStore()
    one_off = rule(recurrence=None, due_in_days=30)
    result = MaterialiseObligations(store, clock=clock).run(request(rule=one_off))
    assert len(result.created) == 1
    (obligation,) = store.of_tenant(TENANT)
    assert obligation.period is None
    assert obligation.title == "File GSTR-3B"
    assert obligation.due_at is not None
    assert obligation.due_at.astimezone(IST).date() == AS_OF + timedelta(days=30)
    assert MaterialiseObligations(store, clock=clock).run(request(rule=one_off)).existing == 1


def test_one_off_rule_without_due_in_days_has_no_due_date() -> None:
    store = MemoryStore()
    MaterialiseObligations(store, clock=clock).run(request(rule=rule(recurrence=None)))
    (obligation,) = store.of_tenant(TENANT)
    assert obligation.due_at is None


def test_window_must_be_positive() -> None:
    with pytest.raises(Exception, match="window"):
        MaterialiseObligations(MemoryStore(), window=0)


def test_tenants_do_not_see_each_other() -> None:
    store = MemoryStore()
    MaterialiseObligations(store, clock=clock).run(request())
    MaterialiseObligations(store, clock=clock).run(request(tenant_id=OTHER_TENANT))
    assert len(store.of_tenant(TENANT)) == 2
    assert len(store.of_tenant(OTHER_TENANT)) == 2
    with store(OTHER_TENANT) as uow:
        assert uow.obligations.get(store.of_tenant(TENANT)[0].id) is None


def test_deadline_change_reschedules_open_obligations_of_the_period_only() -> None:
    store = MemoryStore()
    the_rule = rule()
    MaterialiseObligations(store, window=2, clock=clock).run(request(rule=the_rule))
    store.events.clear()
    amendment = RuleVersionId.new()
    result = ApplyDeadlineChange(store, clock=clock).run(
        DeadlineChange(
            TENANT,
            the_rule.rule_version_id,
            "2026-09",
            date(2026, 10, 25),
            RescheduleReason.DEADLINE_EXTENDED,
            caused_by=amendment,
        )
    )
    assert len(result.changed) == 1
    september, october = store.of_tenant(TENANT)
    assert september.due_at is not None
    assert october.due_at is not None
    assert september.due_at.astimezone(IST).date() == date(2026, 10, 25)
    assert october.due_at.astimezone(IST).date() == date(2026, 11, 20)
    (event,) = store.events
    assert isinstance(event, ObligationRescheduled)
    assert event.caused_by_rule_version_id == amendment
    assert event.previous_due_at.astimezone(IST).date() == date(2026, 10, 20)
    again = ApplyDeadlineChange(store, clock=clock).run(
        DeadlineChange(
            TENANT,
            the_rule.rule_version_id,
            "2026-09",
            date(2026, 10, 25),
            RescheduleReason.CORRECTED,
        )
    )
    assert again == type(again)((), 1)


def test_deadline_change_without_a_period_moves_every_open_obligation() -> None:
    store = MemoryStore()
    the_rule = rule()
    MaterialiseObligations(store, window=2, clock=clock).run(request(rule=the_rule))
    result = ApplyDeadlineChange(store, clock=clock).run(
        DeadlineChange(
            TENANT, the_rule.rule_version_id, None, date(2026, 12, 31), RescheduleReason.MANUAL
        )
    )
    assert len(result.changed) == 2


def test_withdraw_closes_open_obligations_and_leaves_closed_ones() -> None:
    store = MemoryStore()
    the_rule = rule()
    MaterialiseObligations(store, window=2, clock=clock).run(request(rule=the_rule))
    first = store.of_tenant(TENANT)[0]
    CloseObligation(store, clock=clock).run(TENANT, first.id, ClosureReason.COMPLETED)
    store.events.clear()
    result = WithdrawRule(store, clock=clock).run(TENANT, the_rule.rule_version_id)
    assert len(result.changed) == 1
    statuses = {o.period_label: o.status for o in store.of_tenant(TENANT)}
    assert statuses == {
        "2026-09": ObligationStatus.DONE,
        "2026-10": ObligationStatus.CLOSED_NOT_APPLICABLE,
    }
    (event,) = store.events
    assert isinstance(event, ObligationClosed)
    assert event.reason is ClosureReason.RULE_WITHDRAWN
    assert WithdrawRule(store, clock=clock).run(TENANT, the_rule.rule_version_id).changed == ()


def test_close_unknown_obligation() -> None:
    store = MemoryStore()
    with pytest.raises(ObligationNotFoundError):
        CloseObligation(store, clock=clock).run(TENANT, ObligationId.new(), ClosureReason.COMPLETED)


def test_a_failure_inside_the_unit_of_work_rolls_everything_back() -> None:
    store = MemoryStore()
    the_rule = rule(recurrence=Recurrence.monthly(20))
    MaterialiseObligations(store, clock=clock).run(request(rule=the_rule))
    before = (len(store.events), len(store.changes))
    with pytest.raises(RuntimeError, match="boom"):
        _close_then_fail(store, the_rule.rule_version_id)
    assert all(o.is_open for o in store.of_tenant(TENANT))
    assert (len(store.events), len(store.changes)) == before


def _close_then_fail(store: MemoryStore, rule_version_id: RuleVersionId) -> None:
    with store(TENANT) as uow:
        obligation = uow.obligations.open_for_rule_version(rule_version_id)[0]
        done, event = obligation.close(ClosureReason.COMPLETED, at=NOW)
        uow.obligations.save(done)
        record(uow, event, done)
        assert len(uow.history.for_obligation(done.id)) == 2, "the unit sees its own append"
        raise RuntimeError("boom")


# ---- change log (ADR-015: every change writes an audit row) ---------------------------------


def assert_one_change_per_event(store: MemoryStore) -> None:
    assert [change.id for change in store.changes] == [event.event_id for event in store.events]


def test_materialise_appends_one_created_change_per_obligation() -> None:
    store = MemoryStore()
    the_rule = rule()
    use_case = MaterialiseObligations(store, window=2, clock=clock)
    use_case.run(request(rule=the_rule))
    assert [change.kind for change in store.changes] == [ChangeKind.CREATED] * 2
    assert [change.obligation_id for change in store.changes] == [
        o.id for o in store.of_tenant(TENANT)
    ]
    assert_one_change_per_event(store)
    use_case.run(request(rule=the_rule))
    assert len(store.changes) == 2, "an existing obligation appends nothing"


def test_deadline_change_appends_one_change_per_moved_obligation_and_none_when_unchanged() -> None:
    store = MemoryStore()
    the_rule = rule()
    MaterialiseObligations(store, window=2, clock=clock).run(request(rule=the_rule))
    amendment = RuleVersionId.new()
    change = DeadlineChange(
        TENANT,
        the_rule.rule_version_id,
        "2026-09",
        date(2026, 10, 25),
        RescheduleReason.DEADLINE_EXTENDED,
        caused_by=amendment,
    )
    ApplyDeadlineChange(store, clock=clock).run(change)
    assert_one_change_per_event(store)
    rescheduled = store.changes[-1]
    assert rescheduled.kind is ChangeKind.RESCHEDULED
    assert rescheduled.reason == "deadline_extended"
    assert rescheduled.caused_by_rule_version_id == amendment
    assert rescheduled.previous_due_at is not None
    assert rescheduled.new_due_at is not None
    assert rescheduled.previous_due_at.astimezone(IST).date() == date(2026, 10, 20)
    assert rescheduled.new_due_at.astimezone(IST).date() == date(2026, 10, 25)
    assert len(store.changes) == 3

    unchanged = ApplyDeadlineChange(store, clock=clock).run(change)
    assert unchanged.unchanged == 1
    assert len(store.changes) == 3


def test_closures_append_one_change_each_and_closed_obligations_append_none() -> None:
    store = MemoryStore()
    the_rule = rule()
    MaterialiseObligations(store, window=2, clock=clock).run(request(rule=the_rule))
    september, october = store.of_tenant(TENANT)
    user = UserId.new()
    CloseObligation(store, clock=clock).run(TENANT, september.id, ClosureReason.COMPLETED, by=user)
    WithdrawRule(store, clock=clock).run(TENANT, the_rule.rule_version_id)
    assert_one_change_per_event(store)
    closed_by_user, withdrawn = store.changes[-2:]
    assert (closed_by_user.obligation_id, closed_by_user.reason) == (september.id, "completed")
    assert closed_by_user.actor == user
    assert closed_by_user.status_after is ObligationStatus.DONE
    assert (withdrawn.obligation_id, withdrawn.reason) == (october.id, "rule_withdrawn")
    assert withdrawn.status_after is ObligationStatus.CLOSED_NOT_APPLICABLE

    WithdrawRule(store, clock=clock).run(TENANT, the_rule.rule_version_id)
    assert len(store.changes) == 4, "a closed obligation appends nothing"
    with pytest.raises(ObligationClosedError):
        CloseObligation(store, clock=clock).run(TENANT, september.id, ClosureReason.COMPLETED)
    assert len(store.changes) == 4


def test_history_reads_one_obligations_changes_in_order_within_its_tenant() -> None:
    store = MemoryStore()
    the_rule = rule()
    MaterialiseObligations(store, window=2, clock=clock).run(request(rule=the_rule))
    september = store.of_tenant(TENANT)[0]
    ApplyDeadlineChange(store, clock=lambda: NOW + timedelta(hours=1)).run(
        DeadlineChange(
            TENANT, the_rule.rule_version_id, "2026-09", date(2026, 10, 25), RescheduleReason.MANUAL
        )
    )
    CloseObligation(store, clock=lambda: NOW + timedelta(hours=2)).run(
        TENANT, september.id, ClosureReason.WAIVED_BY_USER
    )
    with store(TENANT) as uow:
        kinds = [change.kind for change in uow.history.for_obligation(september.id)]
    assert kinds == [ChangeKind.CREATED, ChangeKind.RESCHEDULED, ChangeKind.CLOSED]
    with store(OTHER_TENANT) as uow:
        assert uow.history.for_obligation(september.id) == []
