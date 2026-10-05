"""The fan-out's control loop (``drive``): through ``LocalFanOuts`` with the real activities on the
memory store (the hold, a pause, a cancellation, the flip check, continuing as new), and with
scripted steps for what is hard to reach that way (a failed batch, a long history, a run with
no row)."""

import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import ontology as ontology_package
from applicability_engine import SERVICE_NAME
from applicability_engine.application.fanout import (
    CANCEL_ACTION,
    PAUSE_ACTION,
    CancelFanOut,
    FanOutControl,
    HoldControl,
    PauseFanOut,
    ReleaseHold,
    ResumeFanOut,
    SetHold,
)
from applicability_engine.application.fanout_activities import fanout_activities
from applicability_engine.application.fanout_flow import (
    BatchFailedError,
    BatchIn,
    BatchOut,
    Continued,
    Controls,
    Counters,
    FanOutRequest,
    Finished,
    RunChange,
    RunState,
    Wakeups,
    drive,
)
from applicability_engine.domain.directory import DirectoryEntry
from applicability_engine.domain.fanout import (
    FanOutRun,
    FanOutSignal,
    FanOutStart,
    FanOutStatus,
)
from applicability_engine.domain.model import Decision, Trigger
from applicability_engine.infrastructure.memory import MemoryBusinessDirectory, MemoryStore
from applicability_engine.testing import (
    LocalFanOuts,
    MemoryProfiles,
    MemoryRulebook,
    rule_version,
)
from domain_kernel.access import Role
from domain_kernel.audit import AuditActor
from domain_kernel.confidence import CERTAIN
from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import BusinessId, DecisionId, EventId, RuleVersionId, TenantId, UserId
from domain_kernel.ontology import AttributeLevel
from domain_kernel.predicates import Applicability

REGULAR = {"attribute": "registration_type", "operator": "eq", "value": "regular"}
ADMIN = AuditActor.user(UserId.new(), [Role.ADMIN])
SYSTEM = AuditActor.system(SERVICE_NAME)
REASON = "Checking the version with the analysts"
WAIT = 10.0


def until[T](found: Callable[[], T | None], timeout: float = WAIT) -> T:
    deadline = time.monotonic() + timeout
    while True:
        value = found()
        if value is not None and value is not False:
            return value
        if time.monotonic() > deadline:
            raise AssertionError("the condition did not hold in time")
        time.sleep(0.01)


class World:
    """Two tenants' registrations in the directory, regular ones but every ``composition``-th."""

    def __init__(self, count: int, *, composition_every: int = 0, **options: object) -> None:
        self.store = MemoryStore()
        self.profiles = MemoryProfiles()
        self.rulebook = MemoryRulebook()
        self.version = self.rulebook.put(rule_version(REGULAR))
        tenants = [TenantId.new(), TenantId.new()]
        self.businesses: list[tuple[TenantId, BusinessId]] = []
        for index in range(count):
            tenant = tenants[index % 2]
            entity, business = BusinessId.new(), BusinessId.new()
            kind = (
                "composition" if composition_every and index % composition_every == 0 else "regular"
            )
            self.profiles.put(
                {"registration_type": kind},
                tenant_id=tenant,
                business_id=business,
                lineage=[entity],
            )
            with self.store(tenant) as uow:
                uow.directory.add(
                    DirectoryEntry(tenant, business, AttributeLevel.REGISTRATION, entity, entity)
                )
            self.businesses.append((tenant, business))
        self.fanouts = LocalFanOuts(
            fanout_activities(
                fanouts=self.store.fanouts,
                directory=MemoryBusinessDirectory(self.store),
                unit_of_work=self.store,
                profiles=self.profiles,
                rulebook=self.rulebook,
                ontology=ontology_package.load(),
            ),
            **options,
        )

    def start(self, *supersedes: RuleVersionId) -> FanOutStart:
        start = FanOutStart(
            rule_version_id=self.version.rule_version_id,
            rule_key="example_rule",
            level=AttributeLevel.REGISTRATION,
            trigger_event_id=EventId.new(),
            supersedes=supersedes,
        )
        assert self.fanouts.start(start)
        return start

    def run(self) -> FanOutRun | None:
        return self.store.fanout_runs.get(self.version.rule_version_id)

    def status(self) -> FanOutStatus | None:
        run = self.run()
        return None if run is None else run.status

    def in_status(self, status: FanOutStatus) -> FanOutRun:
        return until(lambda: self.run() if self.status() is status else None)

    def control(self, reason: str = REASON) -> FanOutControl:
        return FanOutControl(self.version.rule_version_id, ADMIN, reason)

    def finished(self) -> Finished:
        outcome = self.fanouts.join(self.version.rule_version_id)
        assert outcome is not None, self.fanouts.failures
        return outcome

    def published(self) -> list[Decision]:
        return [d for d in self.store.decisions.values() if d.trigger is Trigger.RULE_PUBLISHED]


def test_every_business_is_decided_across_runs_continued_as_new() -> None:
    world = World(25, batch_size=10, batches_per_run=1)
    world.start()
    outcome = world.finished()
    assert (outcome.status, outcome.batches, outcome.counters.evaluated) == (
        FanOutStatus.COMPLETED,
        3,
        25,
    )
    run = world.run()
    assert run is not None
    assert (run.counters.businesses_total, run.counters.evaluated, run.counters.applies) == (
        25,
        25,
        25,
    )
    assert run.finished_at is not None
    assert len(world.published()) == 25
    again = FanOutStart(
        world.version.rule_version_id, "example_rule", AttributeLevel.REGISTRATION, EventId.new()
    )
    assert world.fanouts.start(again) is False, "a version fans out once"


def test_the_hold_stops_a_run_until_it_is_released() -> None:
    world = World(6, batch_size=4)
    SetHold(world.store.fanouts).run(HoldControl(ADMIN, "Deploy of the rulebook in progress"))
    world.start()
    held = world.in_status(FanOutStatus.HELD)
    assert held.status_reason == "Deploy of the rulebook in progress"
    time.sleep(0.2)
    assert world.published() == [], "nothing is decided while held"
    ReleaseHold(world.store.fanouts, world.fanouts).run(HoldControl(ADMIN))
    assert world.finished().status is FanOutStatus.COMPLETED
    assert len(world.published()) == 6


def test_a_paused_run_stays_paused_through_the_release_until_resumed() -> None:
    world = World(6, batch_size=4)
    hold = SetHold(world.store.fanouts)
    release = ReleaseHold(world.store.fanouts, world.fanouts)
    hold.run(HoldControl(ADMIN, "Deploy of the rulebook in progress"))
    world.start()
    world.in_status(FanOutStatus.HELD)
    PauseFanOut(world.store.fanouts, world.fanouts).run(world.control())
    release.run(HoldControl(ADMIN))
    time.sleep(0.2)
    assert (world.status(), world.published()) == (FanOutStatus.PAUSED, [])
    ResumeFanOut(world.store.fanouts, world.fanouts).run(world.control(""))
    assert world.finished().status is FanOutStatus.COMPLETED
    assert len(world.published()) == 6


def test_a_cancelled_run_stops_and_keeps_what_it_decided() -> None:
    world = World(6, batch_size=4)
    SetHold(world.store.fanouts).run(HoldControl(ADMIN, "Deploy of the rulebook in progress"))
    world.start()
    world.in_status(FanOutStatus.HELD)
    CancelFanOut(world.store.fanouts, world.fanouts).run(world.control())
    outcome = world.finished()
    assert (outcome.status, world.published()) == (FanOutStatus.CANCELLED, [])
    assert [entry.action for entry in world.store.audit if entry.actor == ADMIN] == [
        "applicability.fanout.hold",
        CANCEL_ACTION,
    ]


def test_a_cancel_signal_alone_ends_the_run_as_the_system() -> None:
    world = World(6, batch_size=4)
    SetHold(world.store.fanouts).run(HoldControl(ADMIN, "Deploy of the rulebook in progress"))
    world.start()
    world.in_status(FanOutStatus.HELD)
    world.fanouts.signal(world.version.rule_version_id, FanOutSignal.CANCEL)
    assert world.finished().status is FanOutStatus.CANCELLED
    (entry,) = [e for e in world.store.audit if e.action == CANCEL_ACTION]
    assert (entry.actor, entry.reason) == (SYSTEM, "cancelled by a cancel signal to the workflow")


def test_too_many_flips_pause_the_run_once_and_resuming_turns_the_check_off() -> None:
    world = World(300, composition_every=10, batch_size=250)
    old = world.rulebook.put(rule_version(REGULAR)).rule_version_id
    for tenant, business in world.businesses:
        with world.store(tenant) as uow:
            uow.decisions.add(
                Decision(
                    decision_id=DecisionId.new(),
                    tenant_id=tenant,
                    business_id=business,
                    rule_version_id=old,
                    result=Applicability.APPLIES,
                    confidence=CERTAIN,
                    evaluated=(),
                    profile_version=1,
                    decided_at=datetime(2026, 10, 1, tzinfo=UTC),
                    trigger=Trigger.PROFILE_UPDATED,
                    as_of_fy=FinancialYear(2026),
                )
            )
    first_batch = MemoryBusinessDirectory(world.store).entries(
        level=AttributeLevel.REGISTRATION, limit=250
    )
    composition = {
        business for index, (_, business) in enumerate(world.businesses) if index % 10 == 0
    }
    flipped = sum(1 for entry in first_batch if entry.business_id in composition)
    world.start(old)
    paused = world.in_status(FanOutStatus.PAUSED)
    assert (paused.counters.evaluated, paused.counters.flips_compared, paused.counters.flips) == (
        250,
        250,
        flipped,
    )
    assert f"{flipped} of 250" in paused.status_reason
    assert paused.status_by == "system:applicability-engine"
    (entry,) = [e for e in world.store.audit if e.action == PAUSE_ACTION]
    assert (entry.actor, entry.tenant_id, entry.reason) == (SYSTEM, None, paused.status_reason)
    ResumeFanOut(world.store.fanouts, world.fanouts).run(world.control("The flips are expected"))
    outcome = world.finished()
    assert (outcome.status, outcome.counters.evaluated, outcome.counters.flips) == (
        FanOutStatus.COMPLETED,
        300,
        30,
    )
    assert len([e for e in world.store.audit if e.action == PAUSE_ACTION]) == 1


class Scripted:
    """``FanOutSteps`` from a script: the controls to answer, in turn, and the batches."""

    def __init__(
        self,
        controls: list[Controls],
        batches: list[BatchOut | Exception],
        *,
        long: bool = False,
    ) -> None:
        self._controls = controls
        self._batches = batches
        self._long = long
        self.changes: list[RunChange] = []
        self.waits = 0

    async def begin(self, request: FanOutRequest) -> RunState:
        return RunState(status=FanOutStatus.RUNNING, counters=Counters(businesses_total=7))

    async def controls(self, rule_version_id: UUID) -> Controls:
        return self._controls.pop(0) if len(self._controls) > 1 else self._controls[0]

    async def evaluate(self, batch: BatchIn) -> BatchOut:
        found = self._batches.pop(0)
        if isinstance(found, Exception):
            raise found
        return found

    async def update(self, change: RunChange) -> RunState:
        self.changes.append(change)
        return RunState(status=change.status or FanOutStatus.RUNNING, counters=Counters())

    async def wait(self, seconds: float) -> None:
        self.waits += 1

    def history_is_long(self) -> bool:
        return self._long


REQUEST = FanOutRequest(
    rule_version_id=RuleVersionId.new().value,
    rule_key="example_rule",
    level=AttributeLevel.REGISTRATION,
    trigger_event_id=EventId.new().value,
)
RUNNING = Controls(status=FanOutStatus.RUNNING)


def batch(**values: Any) -> BatchOut:
    fields: dict[str, Any] = {
        "read": 1,
        "evaluated": 1,
        "applies": 1,
        "flips_compared": 0,
        "flips": 0,
        "appended": 1,
        "published": 1,
        "skipped": 0,
        "done": True,
    }
    fields.update(values)
    return BatchOut(**fields)


async def test_a_batch_that_keeps_failing_fails_the_run_with_its_error() -> None:
    steps = Scripted([RUNNING], [BatchFailedError("profile answered 503")])
    outcome = await drive(REQUEST, steps, Wakeups())
    assert isinstance(outcome, Finished)
    (final,) = steps.changes
    assert (final.status, final.error) == (FanOutStatus.FAILED, "profile answered 503")
    assert final.counters == Counters(businesses_total=7)


async def test_a_long_history_while_waiting_continues_as_new_with_the_state() -> None:
    held = Controls(status=FanOutStatus.RUNNING, hold_reason="Deploy of the rulebook")
    steps = Scripted([held], [], long=True)
    outcome = await drive(REQUEST, steps, Wakeups())
    assert isinstance(outcome, Continued)
    assert (outcome.request.began, outcome.request.counters.businesses_total) == (True, 7)
    (change,) = steps.changes
    assert (change.status, change.reason) == (FanOutStatus.HELD, "Deploy of the rulebook")


async def test_a_run_continued_as_new_does_not_begin_again_and_keeps_its_counters() -> None:
    counters = Counters(businesses_total=10, evaluated=4, applies=4)
    carried = REQUEST.model_copy(update={"began": True, "counters": counters})
    steps = Scripted([RUNNING], [batch(evaluated=6, applies=5, read=6)])
    outcome = await drive(carried, steps, Wakeups())
    assert isinstance(outcome, Finished)
    assert outcome.counters == Counters(
        businesses_total=10, evaluated=10, applies=9, flips_compared=0, flips=0
    )


async def test_a_run_whose_row_is_gone_or_finished_ends_without_a_change() -> None:
    for status in (None, FanOutStatus.COMPLETED):
        steps = Scripted([Controls(status=status)], [])
        outcome = await drive(REQUEST, steps, Wakeups())
        assert isinstance(outcome, Finished)
        assert (outcome.status, steps.changes) == (status, [])
