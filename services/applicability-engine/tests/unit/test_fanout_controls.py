"""The fan-out controls on the memory store: each changes its row and writes its audit entry
together, of no tenant, and signals the workflow only once that has committed; the reads; the
hold; and what the run's own steps and the rule events do to the row."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from applicability_engine import SERVICE_NAME
from applicability_engine.application.fanout import (
    CANCEL_ACTION,
    HOLD_ACTION,
    PAUSE_ACTION,
    RELEASE_ACTION,
    RESUME_ACTION,
    CancelFanOut,
    FanOutControl,
    FanOutQuery,
    HoldControl,
    ListFanOuts,
    PauseFanOut,
    ReadFanOut,
    ReadHold,
    ReleaseHold,
    ResumeFanOut,
    SetHold,
    actor_name,
)
from applicability_engine.application.fanout_runs import (
    BeginFanOut,
    ReadControls,
    RunUpdate,
    UpdateFanOut,
)
from applicability_engine.application.rule_events import RuleEvents, RulePublished, RuleWithdrawn
from applicability_engine.domain.directory import DirectoryEntry
from applicability_engine.domain.errors import FanOutNotFoundError, FanOutStateError
from applicability_engine.domain.fanout import (
    FanOutCounters,
    FanOutRunKey,
    FanOutSignal,
    FanOutStart,
    FanOutStatus,
)
from applicability_engine.infrastructure.memory import MemoryBusinessDirectory, MemoryStore
from applicability_engine.testing import MemoryRulebook, rule_version
from domain_kernel.access import Role
from domain_kernel.audit import AuditActor
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import BusinessId, CorrelationId, EventId, RuleVersionId, TenantId, UserId
from domain_kernel.ontology import AttributeLevel
from domain_kernel.status import RuleVersionStatus

NOW = datetime(2026, 10, 5, 6, 0, tzinfo=UTC)
ADMIN_ID = UserId.new()
ADMIN = AuditActor.user(ADMIN_ID, [Role.ADMIN])
SYSTEM = AuditActor.system(SERVICE_NAME)
REASON = "Checking the flips with the analysts"
REGULAR = {"attribute": "registration_type", "operator": "eq", "value": "regular"}


@dataclass
class Workflows:
    """``FanOutWorkflows`` that records what it is asked, and checks that no unit of work of the
    store is open when a signal goes out."""

    store: MemoryStore
    started: list[FanOutStart] = field(default_factory=list)
    signals: list[tuple[RuleVersionId, FanOutSignal]] = field(default_factory=list)

    def start(self, start: FanOutStart) -> bool:
        if any(seen.rule_version_id == start.rule_version_id for seen in self.started):
            return False
        self.started.append(start)
        return True

    def signal(self, rule_version_id: RuleVersionId, signal: FanOutSignal) -> None:
        assert not self.store.lock.locked(), "a signal left while the transaction was open"
        self.signals.append((rule_version_id, signal))


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


class World:
    def __init__(self) -> None:
        self.store = MemoryStore()
        self.workflows = Workflows(self.store)
        self.clock = Clock()
        self.directory = MemoryBusinessDirectory(self.store)
        fanouts = self.store.fanouts
        self.begin = BeginFanOut(fanouts, self.directory, clock=self.clock)
        self.pause = PauseFanOut(fanouts, self.workflows, clock=self.clock)
        self.resume = ResumeFanOut(fanouts, self.workflows, clock=self.clock)
        self.cancel = CancelFanOut(fanouts, self.workflows, clock=self.clock)
        self.set_hold = SetHold(fanouts, clock=self.clock)
        self.release = ReleaseHold(fanouts, self.workflows, clock=self.clock)
        self.update = UpdateFanOut(fanouts, clock=self.clock)
        self.controls = ReadControls(fanouts)

    def started(self, **changes: object) -> FanOutStart:
        values: dict[str, object] = {
            "rule_version_id": RuleVersionId.new(),
            "rule_key": "example_rule",
            "level": AttributeLevel.REGISTRATION,
            "trigger_event_id": EventId.new(),
        }
        values.update(changes)
        start = FanOutStart(**values)  # type: ignore[arg-type]
        self.begin.run(start)
        return start

    def list_entries(self, count: int, level: AttributeLevel = AttributeLevel.REGISTRATION) -> None:
        tenant = TenantId.new()
        for _ in range(count):
            entity, business = BusinessId.new(), BusinessId.new()
            entry = (
                DirectoryEntry(tenant, entity, level, None, entity)
                if level is AttributeLevel.ENTITY
                else DirectoryEntry(tenant, business, level, entity, entity)
            )
            with self.store(tenant) as uow:
                uow.directory.add(entry)


@pytest.fixture
def world() -> World:
    return World()


def control(start: FanOutStart, reason: str = REASON) -> FanOutControl:
    return FanOutControl(start.rule_version_id, ADMIN, reason, correlation_id="request-7")


def test_beginning_counts_the_level_and_inserts_once(world: World) -> None:
    world.list_entries(3)
    world.list_entries(2, AttributeLevel.ENTITY)
    start = world.started()
    again = world.begin.run(start)
    assert again.counters.businesses_total == 3
    assert list(world.store.fanout_runs) == [start.rule_version_id]


def test_pause_resume_and_cancel_are_audited_then_signalled(world: World) -> None:
    start = world.started()
    paused = world.pause.run(control(start))
    assert (paused.status, paused.status_reason, paused.status_by) == (
        FanOutStatus.PAUSED,
        REASON,
        str(ADMIN_ID),
    )
    resumed = world.resume.run(control(start, ""))
    assert resumed.status is FanOutStatus.RUNNING
    cancelled = world.cancel.run(control(start))
    assert (cancelled.status, cancelled.finished_at) == (FanOutStatus.CANCELLED, world.clock.now)
    assert world.workflows.signals == [
        (start.rule_version_id, FanOutSignal.PAUSE),
        (start.rule_version_id, FanOutSignal.RESUME),
        (start.rule_version_id, FanOutSignal.CANCEL),
    ]
    pause, resume, cancel = world.store.audit
    assert [entry.action for entry in world.store.audit] == [
        PAUSE_ACTION,
        RESUME_ACTION,
        CANCEL_ACTION,
    ]
    for entry in (pause, resume, cancel):
        assert (entry.tenant_id, entry.subject_type, entry.subject_id) == (
            None,
            "fanout_run",
            str(start.rule_version_id),
        )
        assert (entry.actor, entry.correlation_id) == (ADMIN, "request-7")
    assert (pause.reason, resume.reason) == (REASON, "")
    assert pause.before is not None
    assert pause.after is not None
    assert (pause.before["status"], pause.after["status"]) == ("running", "paused")


def test_controls_refuse_what_the_status_does_not_allow(world: World) -> None:
    start = world.started()
    with pytest.raises(FanOutStateError, match="running; it cannot become running"):
        world.resume.run(control(start))
    world.cancel.run(control(start))
    with pytest.raises(FanOutStateError):
        world.pause.run(control(start))
    with pytest.raises(FanOutNotFoundError):
        world.pause.run(
            control(FanOutStart(RuleVersionId.new(), "x", AttributeLevel.ENTITY, EventId.new()))
        )
    with pytest.raises(InvariantViolationError, match="at least 10"):
        world.cancel.run(control(world.started(), "too short"))
    assert [entry.action for entry in world.store.audit] == [CANCEL_ACTION]
    assert world.workflows.signals == [(start.rule_version_id, FanOutSignal.CANCEL)]


def test_a_held_run_is_paused_by_a_person_but_resumed_only_by_the_release(world: World) -> None:
    start = world.started()
    world.update.run(RunUpdate(start.rule_version_id, status=FanOutStatus.HELD, reason="Deploy"))
    with pytest.raises(FanOutStateError):
        world.resume.run(control(start))
    assert world.pause.run(control(start)).status is FanOutStatus.PAUSED


def test_the_hold_is_set_replaced_and_released_with_an_entry_each(world: World) -> None:
    held, running = world.started(), world.started()
    hold = world.set_hold.run(HoldControl(ADMIN, "Deploy of the rulebook in progress", "r-1"))
    assert (hold.set_by, hold.reason) == (str(ADMIN_ID), "Deploy of the rulebook in progress")
    world.set_hold.run(HoldControl(SYSTEM, "A replacement reason for the hold"))
    assert ReadHold(world.store.fanouts).run() == world.store.fanout_hold[0]
    assert world.store.fanout_hold[0].set_by == "system:applicability-engine"
    world.update.run(RunUpdate(held.rule_version_id, status=FanOutStatus.HELD, reason="Deploy"))
    released = world.release.run(HoldControl(ADMIN))
    assert released is not None
    assert released.reason == "A replacement reason for the hold"
    assert ReadHold(world.store.fanouts).run() is None
    assert world.workflows.signals == [(held.rule_version_id, FanOutSignal.RESUME)]
    assert running.rule_version_id not in {signalled for signalled, _ in world.workflows.signals}
    assert world.release.run(HoldControl(ADMIN)) is None, "nothing to release"
    actions = [entry.action for entry in world.store.audit]
    assert actions == [HOLD_ACTION, HOLD_ACTION, RELEASE_ACTION]
    first, second, release = world.store.audit
    assert (first.subject_type, first.subject_id, first.before) == ("fanout_hold", "global", None)
    assert second.before is not None
    assert second.before["reason"] == "Deploy of the rulebook in progress"
    assert (release.after, release.actor) == (None, ADMIN)
    with pytest.raises(InvariantViolationError):
        world.set_hold.run(HoldControl(ADMIN, "short"))


def test_the_runs_are_listed_newest_first_a_page_at_a_time(world: World) -> None:
    starts = [world.started() for _ in range(3)]
    runs = ListFanOuts(world.store.fanouts)
    first = runs.run(FanOutQuery(limit=2))
    assert [run.rule_version_id for run in first] == [s.rule_version_id for s in starts[::-1][:2]]
    rest = runs.run(FanOutQuery(limit=2, after=FanOutRunKey.of(first[-1])))
    assert [run.rule_version_id for run in rest] == [starts[0].rule_version_id]
    assert ReadFanOut(world.store.fanouts).run(starts[0].rule_version_id).rule_key == "example_rule"
    with pytest.raises(FanOutNotFoundError):
        ReadFanOut(world.store.fanouts).run(RuleVersionId.new())


def test_the_run_moves_itself_without_overriding_a_person(world: World) -> None:
    start = world.started()
    rule_version_id = start.rule_version_id
    counted = world.update.run(RunUpdate(rule_version_id, counters=FanOutCounters(10, 4, 1, 0, 0)))
    assert (counted.status, counted.counters.evaluated) == (FanOutStatus.RUNNING, 4)
    paused = world.update.run(
        RunUpdate(
            rule_version_id,
            status=FanOutStatus.PAUSED,
            reason="5 of 200 flipped (2.5%)",
            correlation_id="c-1",
        )
    )
    assert (paused.status, paused.status_by) == (FanOutStatus.PAUSED, "system:applicability-engine")
    (entry,) = world.store.audit
    assert (entry.action, entry.actor, entry.reason, entry.correlation_id) == (
        PAUSE_ACTION,
        SYSTEM,
        "5 of 200 flipped (2.5%)",
        "c-1",
    )
    again = world.update.run(RunUpdate(rule_version_id, status=FanOutStatus.PAUSED, reason="x"))
    assert again.status_reason == "5 of 200 flipped (2.5%)", "already paused: nothing again"
    world.cancel.run(control(start))
    after = world.update.run(
        RunUpdate(
            rule_version_id,
            counters=FanOutCounters(10, 8, 2, 0, 0),
            status=FanOutStatus.COMPLETED,
        )
    )
    assert (after.status, after.counters.evaluated) == (FanOutStatus.CANCELLED, 8)
    assert [e.action for e in world.store.audit] == [PAUSE_ACTION, CANCEL_ACTION]
    controls = world.controls.run(rule_version_id)
    assert controls.run is not None
    assert (controls.run.status, controls.hold) == (FanOutStatus.CANCELLED, None)
    with pytest.raises(FanOutNotFoundError):
        world.update.run(RunUpdate(RuleVersionId.new(), counters=FanOutCounters()))


def test_a_publication_starts_a_fan_out_once_and_off_records_it_disabled(world: World) -> None:
    rulebook = MemoryRulebook()
    version = rulebook.put(rule_version(REGULAR, rule_key="example_rule"))
    superseded = RuleVersionId.new()
    published = RulePublished(
        EventId.new(), version.rule_version_id, (superseded,), CorrelationId.new()
    )
    events = RuleEvents(rulebook, world.workflows, enabled=True, clock=world.clock)
    plan = events.plan_published(published)
    assert (plan.started, plan.disabled, plan.skipped) == (True, False, "")
    assert rulebook.forgotten == 1
    run = events.apply(plan, world.store.fanouts)
    assert run is not None
    assert (run.status, run.supersedes, run.trigger_event_id) == (
        FanOutStatus.RUNNING,
        (superseded,),
        published.event_id,
    )
    (started,) = world.workflows.started
    assert (started.rule_key, started.level, started.trigger_event_id) == (
        "example_rule",
        AttributeLevel.REGISTRATION,
        published.event_id,
    )
    replay = events.plan_published(published)
    assert replay.started is False
    assert events.apply(replay, world.store.fanouts) == run

    off = RuleEvents(rulebook, world.workflows, enabled=False, clock=world.clock)
    other = rulebook.put(rule_version(REGULAR))
    disabled = off.apply(
        off.plan_published(RulePublished(EventId.new(), other.rule_version_id)),
        world.store.fanouts,
    )
    assert disabled is not None
    assert (disabled.status, disabled.finished_at is not None) == (FanOutStatus.DISABLED, True)
    assert len(world.workflows.started) == 1, "the flag off starts nothing"
    assert world.store.audit == []


def test_a_version_the_rulebook_cannot_fan_out_records_nothing(world: World) -> None:
    rulebook = MemoryRulebook()
    events = RuleEvents(rulebook, world.workflows, enabled=True, clock=world.clock)
    for version_id, why in (
        (RuleVersionId.new(), "no such version"),
        (
            rulebook.put(rule_version(REGULAR, status=RuleVersionStatus.WITHDRAWN)).rule_version_id,
            "withdrawn",
        ),
        (rulebook.put(rule_version(REGULAR, level=None)).rule_version_id, "no rule key or level"),
    ):
        plan = events.plan_published(RulePublished(EventId.new(), version_id))
        assert why in plan.skipped
        assert events.apply(plan, world.store.fanouts) is None
    assert world.store.fanout_runs == {}
    assert world.workflows.started == []


def test_a_withdrawal_cancels_a_run_that_has_not_finished(world: World) -> None:
    rulebook = MemoryRulebook()
    events = RuleEvents(rulebook, world.workflows, enabled=True, clock=world.clock)
    start = world.started()
    withdrawn = RuleWithdrawn(EventId.new(), start.rule_version_id, CorrelationId.new())
    plan = events.plan_withdrawn(withdrawn)
    assert rulebook.forgotten == 1
    cancelled = events.apply(plan, world.store.fanouts)
    assert cancelled is not None
    assert cancelled.status is FanOutStatus.CANCELLED
    assert "withdrawn" in cancelled.status_reason
    (entry,) = world.store.audit
    assert (entry.action, entry.actor, entry.correlation_id) == (
        CANCEL_ACTION,
        SYSTEM,
        str(withdrawn.correlation_id),
    )
    assert events.apply(plan, world.store.fanouts) == cancelled, "a redelivery changes nothing"
    assert len(world.store.audit) == 1
    nothing = events.apply(
        events.plan_withdrawn(RuleWithdrawn(EventId.new(), RuleVersionId.new())),
        world.store.fanouts,
    )
    assert nothing is None
    assert world.workflows.signals == [], "the workflow sees the row at its next boundary"


def test_a_person_is_named_by_user_id_and_anyone_else_by_label() -> None:
    assert actor_name(ADMIN) == str(ADMIN_ID)
    assert actor_name(SYSTEM) == "system:applicability-engine"
    assert actor_name(AuditActor.service("ops")) == "service:ops"
