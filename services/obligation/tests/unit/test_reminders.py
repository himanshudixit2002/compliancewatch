"""The reminder rules and the sweep on the memory store: thresholds, deduplication across sweeps,
reminders against a new due date, tenants one at a time, and a failing tenant."""

from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, date, datetime, timedelta

import pytest

from domain_kernel.errors import InvariantViolationError
from domain_kernel.events import utc_now
from domain_kernel.ids import BusinessId, DecisionId, EventId, ObligationId, TenantId
from domain_kernel.status import ClosureReason
from obligation.application.changes import CloseObligation
from obligation.application.materialise import IST, MaterialiseObligations, MaterialiseRequest
from obligation.application.reminders import FailureHandler, SendDueReminders
from obligation.domain.events import ObligationDueSoon, RescheduleReason
from obligation.domain.model import due_at_end_of_day
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
from obligation.infrastructure.memory import MemoryStore
from obligation.testing import rule

AS_OF = date(2026, 10, 1)
DUE = due_at_end_of_day(date(2026, 10, 11), IST)  # 2026-10-11T18:29:59Z


def at(day: int, hour: int = 10) -> datetime:
    return datetime(2026, 10, day, hour, tzinfo=UTC)


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def one_off(store: MemoryStore, tenant: TenantId, *, due_in_days: int = 10) -> ObligationId:
    """One open obligation of a fresh one-off rule, due ``due_in_days`` after AS_OF."""
    result = MaterialiseObligations(store).run(
        MaterialiseRequest(
            tenant,
            BusinessId.new(),
            DecisionId.new(),
            rule(recurrence=None, due_in_days=due_in_days),
            AS_OF,
        )
    )
    (created,) = result.created
    return created


def due_soon(store: MemoryStore) -> list[ObligationDueSoon]:
    return [e for e in store.events if isinstance(e, ObligationDueSoon)]


def sweep(
    store: MemoryStore, clock: Clock, *, on_failure: FailureHandler | None = None
) -> SendDueReminders:
    return SendDueReminders(store, store, clock=clock, on_failure=on_failure)


@pytest.mark.parametrize(
    ("left", "threshold"),
    [(-1, None), (0, 1), (1, 1), (2, 3), (3, 3), (4, 7), (7, 7), (8, None)],
)
def test_the_threshold_is_the_smallest_one_the_days_left_are_within(
    left: int, threshold: int | None
) -> None:
    assert threshold_for(left) == threshold


def test_days_left_are_whole_days_and_negative_once_overdue() -> None:
    assert days_left(DUE, at(4)) == 7
    assert days_left(DUE, at(11, 18)) == 0
    assert days_left(DUE, at(12)) == -1
    assert lookahead() == timedelta(days=8)
    assert REMINDER_DAYS == (7, 3, 1)


def test_reminder_bookkeeping() -> None:
    tenant, obligation = TenantId.new(), ObligationId.new()
    seven = Reminder(EventId.new(), tenant, obligation, DUE, 7, 1, at(4))
    assert next_index([]) == 1
    assert next_index([seven]) == 2
    assert already_reminded([seven], DUE, 7)
    assert already_reminded([seven], DUE, 9), "a less urgent reminder never follows"
    assert not already_reminded([seven], DUE, 3)
    assert not already_reminded([seven], DUE + timedelta(days=5), 7), "a new due date"
    with pytest.raises(InvariantViolationError):
        Reminder(EventId.new(), tenant, obligation, DUE, 7, 0, at(4))
    for bad in ((), (3, 3), (-1,)):
        with pytest.raises(InvariantViolationError):
            validate_thresholds(bad)
    assert validate_thresholds([1]) == (1,)


def test_each_threshold_is_reminded_once_across_sweeps() -> None:
    store, tenant = MemoryStore(), TenantId.new()
    obligation = one_off(store, tenant)
    clock = Clock(at(1))
    sweeper = sweep(store, clock)

    def run(now: datetime) -> Sequence[ObligationId]:
        clock.now = now
        return sweeper.run().reminded

    assert run(at(1)) == (), "ten days left: too early"
    assert run(at(5)) == (obligation,)
    assert run(at(5, 11)) == (), "the same threshold again"
    assert run(at(8)) == (obligation,)
    assert run(at(10)) == (obligation,)
    assert run(at(11)) == (), "the last day is still the 1-day threshold"
    assert run(at(12)) == (), "overdue"

    events = due_soon(store)
    assert [(e.days_left, e.reminder_index) for e in events] == [(6, 1), (3, 2), (1, 3)]
    first = events[0]
    assert first.tenant_id == tenant
    assert first.obligation_id == obligation
    assert first.due_at == DUE
    assert first.title == "File GSTR-3B"
    assert first.occurred_at == at(5)
    assert [r.threshold_days for r in store.reminders] == [7, 3, 1]
    assert [r.id for r in store.reminders] == [e.event_id for e in events]


def test_a_late_first_sweep_sends_only_the_most_urgent_reminder() -> None:
    store, tenant = MemoryStore(), TenantId.new()
    one_off(store, tenant)
    clock = Clock(at(10))
    sweep(store, clock).run()
    sweep(store, clock).run()
    assert [(e.days_left, e.reminder_index) for e in due_soon(store)] == [(1, 1)]


def test_a_new_due_date_is_reminded_again_with_a_new_index() -> None:
    store, tenant = MemoryStore(), TenantId.new()
    obligation = one_off(store, tenant)
    clock = Clock(at(5))
    sweep(store, clock).run()
    with store(tenant) as uow:
        current = uow.obligations.get(obligation)
        assert current is not None
        moved, _ = current.reschedule(
            DUE + timedelta(days=4), reason=RescheduleReason.DEADLINE_EXTENDED, at=at(5, 12)
        )
        uow.obligations.save(moved)
    clock.now = at(9)
    sweep(store, clock).run()
    assert [(e.days_left, e.reminder_index) for e in due_soon(store)] == [(6, 1), (6, 2)]


def test_closed_obligations_are_not_reminded_and_tenants_stay_apart() -> None:
    store, tenant, other = MemoryStore(), TenantId.new(), TenantId.new()
    done = one_off(store, tenant)
    CloseObligation(store, clock=lambda: at(2)).run(tenant, done, ClosureReason.COMPLETED)
    kept = one_off(store, tenant, due_in_days=11)
    theirs = one_off(store, other)
    swept = sweep(store, Clock(at(5))).run()
    assert swept.tenants == 2
    assert sorted(swept.reminded, key=str) == sorted([kept, theirs], key=str)
    assert swept.failed == ()
    assert {(e.tenant_id, e.obligation_id) for e in due_soon(store)} == {
        (tenant, kept),
        (other, theirs),
    }
    with store(other) as uow:
        assert uow.reminders.for_obligation(kept) == []
        assert len(uow.reminders.for_obligation(theirs)) == 1


class FailingFor:
    """The memory store, except that units of ``tenant`` fail before they commit."""

    def __init__(self, store: MemoryStore, tenant: TenantId) -> None:
        self.store = store
        self.tenant = tenant

    def __call__(self, tenant_id: TenantId) -> AbstractContextManager[object]:
        return self._unit(tenant_id)

    @contextmanager
    def _unit(self, tenant_id: TenantId) -> Iterator[object]:
        with self.store(tenant_id) as uow:
            yield uow
            if tenant_id == self.tenant:
                raise RuntimeError("boom")


def test_a_failing_tenant_is_reported_and_the_others_are_swept() -> None:
    store = MemoryStore()
    tenants = sorted([TenantId.new(), TenantId.new()], key=lambda t: t.value)
    for tenant in tenants:
        one_off(store, tenant)
    failures: list[tuple[TenantId, str]] = []
    sweeper = SendDueReminders(
        FailingFor(store, tenants[0]),  # type: ignore[arg-type]
        store,
        clock=lambda: at(5),
        on_failure=lambda tenant, exc: failures.append((tenant, str(exc))),
    )
    swept = sweeper.run()
    assert swept.failed == (tenants[0],)
    assert len(swept.reminded) == 1
    assert failures == [(tenants[0], "boom")]
    assert {e.tenant_id for e in due_soon(store)} == {tenants[1]}, "the failure rolled back"

    strict = SendDueReminders(
        FailingFor(store, tenants[0]),  # type: ignore[arg-type]
        store,
        clock=lambda: at(5),
    )
    with pytest.raises(RuntimeError, match="boom"):
        strict.run()


def test_the_memory_reminder_log_refuses_what_postgres_refuses() -> None:
    store, tenant = MemoryStore(), TenantId.new()
    obligation = one_off(store, tenant)
    first = Reminder(EventId.new(), tenant, obligation, DUE, 7, 1, utc_now())
    with store(tenant) as uow:
        uow.reminders.add(first)
        for duplicate in (
            Reminder(EventId.new(), tenant, obligation, DUE, 7, 2, utc_now()),
            Reminder(EventId.new(), tenant, obligation, DUE, 3, 1, utc_now()),
            Reminder(EventId.new(), TenantId.new(), obligation, DUE, 1, 3, utc_now()),
        ):
            with pytest.raises(ValueError, match=r"duplicate|another tenant"):
                uow.reminders.add(duplicate)
        uow.reminders.add(Reminder(EventId.new(), tenant, ObligationId.new(), DUE, 7, 1, utc_now()))
    assert len(store.reminders) == 2


def test_the_due_soon_event_refuses_what_its_schema_refuses() -> None:
    fields: dict[str, object] = {
        "tenant_id": TenantId.new(),
        "obligation_id": ObligationId.new(),
        "business_id": BusinessId.new(),
        "rule_version_id": rule().rule_version_id,
        "title": "File GSTR-3B",
        "due_at": DUE,
        "days_left": 7,
        "reminder_index": 1,
    }
    ObligationDueSoon(**fields)  # type: ignore[arg-type]
    for bad in (
        {"days_left": -1},
        {"reminder_index": 0},
        {"title": " "},
        {"due_at": datetime(2026, 10, 11)},
    ):
        with pytest.raises(InvariantViolationError):
            ObligationDueSoon(**{**fields, **bad})  # type: ignore[arg-type]
