import threading
from datetime import date, timedelta

import pytest

from domain_kernel.ids import ObligationId, RuleVersionId, UserId
from domain_kernel.recurrence import Recurrence
from domain_kernel.status import ClosureReason, ObligationStatus, RuleVersionStatus
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
from obligation.testing import BUSINESS, DECISION, NOW, OTHER_TENANT, TENANT, clock, ref_of, rule

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
    assert later.existing == 2, "September, due 20 October, is still in the window"
    assert [o.period_label for o in store.of_tenant(TENANT)] == ["2026-09", "2026-10", "2026-11"]
    assert len(store.events) == 3


def labels_and_due_days(store: MemoryStore) -> list[tuple[str, date]]:
    return [
        (o.period_label or "one-off", o.due_at.astimezone(IST).date())
        for o in store.of_tenant(TENANT)
        if o.due_at is not None
    ]


def test_a_decision_on_5_october_makes_septembers_return_due_20_october() -> None:
    store = MemoryStore()
    result = MaterialiseObligations(store, window=2, clock=clock).run(
        request(as_of=date(2026, 10, 5))
    )
    assert (len(result.created), result.existing, result.skipped_before_effective) == (3, 0, 0)
    assert labels_and_due_days(store) == [
        ("2026-09", date(2026, 10, 20)),
        ("2026-10", date(2026, 11, 20)),
        ("2026-11", date(2026, 12, 20)),
    ]


def test_a_decision_on_25_october_starts_with_octobers_return_due_20_november() -> None:
    store = MemoryStore()
    result = MaterialiseObligations(store, window=2, clock=clock).run(
        request(as_of=date(2026, 10, 25))
    )
    assert len(result.created) == 2
    assert labels_and_due_days(store) == [
        ("2026-10", date(2026, 11, 20)),
        ("2026-11", date(2026, 12, 20)),
    ], "September was due on 20 October: nothing overdue is made"


def test_a_return_due_on_the_decision_day_is_still_made() -> None:
    store = MemoryStore()
    MaterialiseObligations(store, window=1, clock=clock).run(request(as_of=date(2026, 10, 20)))
    assert labels_and_due_days(store) == [
        ("2026-09", date(2026, 10, 20)),
        ("2026-10", date(2026, 11, 20)),
    ]


def test_a_quarterly_return_still_due_is_made_and_one_overdue_is_not() -> None:
    store, group_a = MemoryStore(), rule(recurrence=Recurrence.quarterly(22))
    use_case = MaterialiseObligations(store, window=2, clock=clock)
    use_case.run(request(rule=group_a, as_of=date(2026, 10, 5)))
    assert labels_and_due_days(store) == [
        ("2026-27 Q2", date(2026, 10, 22)),
        ("2026-27 Q3", date(2027, 1, 22)),
        ("2026-27 Q4", date(2027, 4, 22)),
    ]
    late = MemoryStore()
    MaterialiseObligations(late, window=2, clock=clock).run(
        request(rule=group_a, as_of=date(2026, 10, 23))
    )
    assert [label for label, _ in labels_and_due_days(late)] == ["2026-27 Q3", "2026-27 Q4"]


def test_a_period_ending_before_the_version_is_in_force_is_skipped_though_still_due() -> None:
    """In force from 15 October: September is due 20 October but ended before the version took
    effect, so an earlier version governs it; October's last day is the version's."""
    store, mid_october = MemoryStore(), rule(effective_from=date(2026, 10, 15))
    use_case = MaterialiseObligations(store, window=2, clock=clock)
    early = use_case.run(request(rule=mid_october, as_of=date(2026, 10, 5)))
    assert (len(early.created), early.skipped_before_effective) == (2, 1)
    later = use_case.run(request(rule=mid_october, as_of=date(2026, 10, 16)))
    assert (later.created, later.existing, later.skipped_before_effective) == ((), 2, 1)
    assert [o.period_label for o in store.of_tenant(TENANT)] == ["2026-10", "2026-11"]


def test_a_superseded_version_and_its_replacement_share_the_window_without_a_gap() -> None:
    """Superseded from 1 October and decided on 5 October: the old version still governs
    September, due 20 October; the new one makes October and November."""
    store = MemoryStore()
    old, new = rule(), rule(effective_from=date(2026, 10, 1))
    cut = ref_of(old, status=RuleVersionStatus.SUPERSEDED, effective_to=date(2026, 10, 1))
    use_case = MaterialiseObligations(store, window=2, clock=clock)
    kept = use_case.run(request(rule=old, as_of=date(2026, 10, 5), ref=cut))
    assert (len(kept.created), kept.refused) == (1, ("2026-10", "2026-11"))
    taken = use_case.run(request(rule=new, as_of=date(2026, 10, 5), ref=ref_of(new)))
    assert (len(taken.created), taken.skipped_before_effective, taken.refused) == (2, 1, ())
    made = sorted(
        (o.period_label or "", o.rule_version_id == old.rule_version_id)
        for o in store.of_tenant(TENANT)
    )
    assert made == [("2026-09", True), ("2026-10", False), ("2026-11", False)]


def test_replays_and_later_days_make_each_period_once() -> None:
    store, the_rule = MemoryStore(), rule()
    use_case = MaterialiseObligations(store, window=2, clock=clock)
    runs = [
        use_case.run(request(rule=the_rule, as_of=day))
        for day in (date(2026, 10, 5), date(2026, 10, 5), date(2026, 10, 25), date(2026, 11, 2))
    ]
    assert [(len(r.created), r.existing) for r in runs] == [(3, 0), (0, 3), (0, 2), (1, 2)]
    assert [o.period_label for o in store.of_tenant(TENANT)] == [
        "2026-09",
        "2026-10",
        "2026-11",
        "2026-12",
    ]
    assert len(store.events) == 4


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


def test_overlapping_units_of_two_tenants_keep_both_writes() -> None:
    """The second unit waits for the first to commit instead of starting from the same copy of
    the store and dropping the other tenant's obligation."""
    scratch = MemoryStore()
    MaterialiseObligations(scratch, window=1, clock=clock).run(request(tenant_id=OTHER_TENANT))
    [theirs] = scratch.of_tenant(OTHER_TENANT)
    store = MemoryStore()
    done = threading.Event()

    def materialise_ours() -> None:
        MaterialiseObligations(store, window=1, clock=clock).run(request())
        done.set()

    with store(OTHER_TENANT) as uow:
        uow.obligations.add(theirs)
        thread = threading.Thread(target=materialise_ours)
        thread.start()
        assert not done.wait(0.05), "a second unit of work ran inside the first"
    thread.join(timeout=5)
    assert done.is_set()
    assert store.of_tenant(OTHER_TENANT) == [theirs]
    assert len(store.of_tenant(TENANT)) == 1


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


def test_each_change_writes_its_audit_entry_by_the_system() -> None:
    store = MemoryStore()
    the_rule = rule()
    made = MaterialiseObligations(store, window=2, clock=clock).run(request(rule=the_rule))
    created = [entry for entry in store.audit if entry.action == "obligation.created"]
    assert [entry.subject_id for entry in created] == [str(o) for o in made.created]
    assert {(entry.tenant_id, entry.actor.label) for entry in created} == {
        (TENANT, "system:obligation")
    }
    assert created[0].before is None
    assert created[0].after is not None
    assert (created[0].after["status"], created[0].after["period"]) == ("open", "2026-09")
    assert created[0].after["rule_version_id"] == str(the_rule.rule_version_id)

    amendment = RuleVersionId.new()
    ApplyDeadlineChange(store, clock=clock).run(
        DeadlineChange(
            TENANT,
            the_rule.rule_version_id,
            "2026-09",
            date(2026, 10, 25),
            RescheduleReason.DEADLINE_EXTENDED,
            caused_by=amendment,
        )
    )
    (moved,) = [entry for entry in store.audit if entry.action == "obligation.rescheduled"]
    assert moved.subject_id == str(made.created[0])
    assert moved.reason == "deadline_extended"
    assert moved.before == {"due_at": "2026-10-20T23:59:59+05:30"}
    assert moved.after == {
        "due_at": "2026-10-25T23:59:59+05:30",
        "cause": "deadline_extended",
        "caused_by_rule_version_id": str(amendment),
    }

    WithdrawRule(store, clock=clock).run(TENANT, the_rule.rule_version_id)
    closed = [entry for entry in store.audit if entry.action == "obligation.closed"]
    assert sorted(entry.subject_id for entry in closed) == sorted(str(o) for o in made.created)
    assert {entry.reason for entry in closed} == {"rule_withdrawn"}
    assert closed[0].after == {"status": "closed_not_applicable", "closed_reason": "rule_withdrawn"}
    assert len(store.audit) == 5, "one entry per change, none for what stayed as it was"
