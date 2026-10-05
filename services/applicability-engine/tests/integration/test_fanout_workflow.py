"""The fan-out workflow on a local Temporal dev server, over 2,500 directory businesses in two
tenants on the memory store: it continues as new between batches and completes, the hold and a
pause stop it at a batch boundary until released and resumed, a cancellation ends it keeping the
decisions made, and too many flips pause it as the system. The controls go through the use cases
and ``TemporalFanOuts``, so the rows change first and the signals follow.

``WorkflowEnvironment.start_local`` downloads the Temporal CLI once (native on Apple Silicon; the
time-skipping test server is x86-only and needs Rosetta, so it is not used).
"""

import asyncio
import threading
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from temporalio.client import WorkflowExecutionStatus
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

import ontology as ontology_package
from applicability_engine.application.fanout import (
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
from applicability_engine.application.fanout_flow import FanOutProgress, FanOutResult
from applicability_engine.domain.directory import DirectoryEntry
from applicability_engine.domain.fanout import (
    FanOutRun,
    FanOutStart,
    FanOutStatus,
    fan_out_workflow_id,
)
from applicability_engine.domain.model import Decision, Trigger
from applicability_engine.infrastructure.memory import MemoryBusinessDirectory, MemoryStore
from applicability_engine.infrastructure.temporal import TemporalFanOuts
from applicability_engine.testing import MemoryProfiles, MemoryRulebook, rule_version
from applicability_engine.workflows import FanOutWorkflow
from domain_kernel.access import Role
from domain_kernel.audit import AuditActor
from domain_kernel.confidence import CERTAIN
from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import BusinessId, DecisionId, EventId, RuleVersionId, TenantId, UserId
from domain_kernel.ontology import AttributeLevel
from domain_kernel.predicates import Applicability
from domain_kernel.profiles import ProfileSnapshot
from py_common.settings import Settings
from py_common.temporal.client import default_interceptors
from py_common.temporal.worker import WorkerConfig, build_worker

pytestmark = pytest.mark.integration

BUSINESSES = 2_500
REGULAR = {"attribute": "registration_type", "operator": "eq", "value": "regular"}
ADMIN = AuditActor.user(UserId.new(), [Role.ADMIN])
SYSTEM = AuditActor.system("applicability-engine")
REASON = "Checking the version with the analysts"
WAIT = 60.0


@pytest.fixture
async def environment() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_local(
        data_converter=pydantic_data_converter, interceptors=default_interceptors()
    ) as env:
        yield env


class GatedProfiles(MemoryProfiles):
    """Profiles whose ``gate_after``-th read waits for ``gate`` to open."""

    def __init__(self) -> None:
        super().__init__()
        self.reads = 0
        self.gate_after: int | None = None
        self.gate = threading.Event()
        self.reached = threading.Event()
        self._lock = threading.Lock()

    def snapshot(
        self, tenant_id: TenantId, business_id: BusinessId, fy: FinancialYear | None
    ) -> ProfileSnapshot | None:
        with self._lock:
            self.reads += 1
            gated = self.gate_after is not None and self.reads == self.gate_after
        if gated:
            self.reached.set()
            self.gate.wait(WAIT)
        return super().snapshot(tenant_id, business_id, fy)


@dataclass
class World:
    store: MemoryStore
    profiles: GatedProfiles
    rulebook: MemoryRulebook
    businesses: list[tuple[TenantId, BusinessId]]
    compositions: set[BusinessId]
    fanouts: TemporalFanOuts
    task_queue: str

    @property
    def units(self) -> Any:
        return self.store.fanouts

    def start(self, *supersedes: RuleVersionId) -> FanOutStart:
        version = self.rulebook.put(rule_version(REGULAR, rule_key="example_rule"))
        return FanOutStart(
            rule_version_id=version.rule_version_id,
            rule_key="example_rule",
            level=AttributeLevel.REGISTRATION,
            trigger_event_id=EventId.new(),
            supersedes=supersedes,
        )

    def run(self, start: FanOutStart) -> FanOutRun | None:
        return self.store.fanout_runs.get(start.rule_version_id)

    def decided(self, start: FanOutStart) -> list[Decision]:
        return [
            d
            for d in self.store.decisions.values()
            if d.rule_version_id == start.rule_version_id and d.trigger is Trigger.RULE_PUBLISHED
        ]

    def control(self, start: FanOutStart, reason: str = REASON) -> FanOutControl:
        return FanOutControl(start.rule_version_id, ADMIN, reason)


def build_world(environment: WorkflowEnvironment, *, composition_every: int = 0) -> World:
    store, profiles, rulebook = MemoryStore(), GatedProfiles(), MemoryRulebook()
    tenants = [TenantId.new(), TenantId.new()]
    businesses: list[tuple[TenantId, BusinessId]] = []
    compositions: set[BusinessId] = set()
    for index in range(BUSINESSES):
        tenant = tenants[index % 2]
        entity, business = BusinessId.new(), BusinessId.new()
        # Pairs of businesses, one in each tenant, so both tenants hold compositions.
        composition = bool(composition_every) and (index // 2) % composition_every == 0
        kind = "composition" if composition else "regular"
        if composition:
            compositions.add(business)
        profiles.put(
            {"registration_type": kind}, tenant_id=tenant, business_id=business, lineage=[entity]
        )
        store.directory[business] = DirectoryEntry(
            tenant, business, AttributeLevel.REGISTRATION, entity, entity
        )
        businesses.append((tenant, business))
    task_queue = f"applicability-test-{uuid.uuid4().hex[:8]}"
    settings = Settings(
        _env_file=None,
        service_name="applicability-engine",
        temporal_address=environment.client.service_client.config.target_host,
    )
    fanouts = TemporalFanOuts(
        settings, options={"poll_seconds": 0.5, "batches_per_run": 1}, task_queue=task_queue
    )
    return World(store, profiles, rulebook, businesses, compositions, fanouts, task_queue)


def worker_of(environment: WorkflowEnvironment, world: World) -> Worker:
    activities = fanout_activities(
        fanouts=world.store.fanouts,
        directory=MemoryBusinessDirectory(world.store),
        unit_of_work=world.store,
        profiles=world.profiles,
        rulebook=world.rulebook,
        ontology=ontology_package.load(),
        heartbeat_seconds=1.0,
    )
    return build_worker(
        environment.client,
        WorkerConfig(task_queue=world.task_queue),
        workflows=[FanOutWorkflow],
        activities=activities,
    )


async def until[T](found: Callable[[], T | None], within: float = WAIT) -> T:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + within
    while True:
        value = found()
        if value is not None and value is not False:
            return value
        if loop.time() > deadline:
            raise AssertionError("the condition did not hold in time")
        await asyncio.sleep(0.05)


async def in_status(world: World, start: FanOutStart, status: FanOutStatus) -> FanOutRun:
    def found() -> FanOutRun | None:
        run = world.run(start)
        return run if run is not None and run.status is status else None

    return await until(found)


async def result_of(environment: WorkflowEnvironment, start: FanOutStart) -> FanOutResult:
    handle = environment.client.get_workflow_handle_for(
        FanOutWorkflow.run, fan_out_workflow_id(start.rule_version_id)
    )
    return await asyncio.wait_for(handle.result(), WAIT)


async def test_2500_businesses_in_two_tenants_continue_as_new_and_complete(
    environment: WorkflowEnvironment,
) -> None:
    world = build_world(environment)
    start = world.start()
    async with worker_of(environment, world):
        assert await asyncio.to_thread(world.fanouts.start, start) is True
        handle = environment.client.get_workflow_handle_for(
            FanOutWorkflow.run, fan_out_workflow_id(start.rule_version_id)
        )
        first_run = (await handle.describe()).run_id
        result = await result_of(environment, start)
        assert await asyncio.to_thread(world.fanouts.start, start) is False, "a duplicate start"
        progress: FanOutProgress | None = await handle.query(FanOutWorkflow.progress)
    assert (result.status, result.batches, result.counters.evaluated) == (
        FanOutStatus.COMPLETED,
        3,
        BUSINESSES,
    )
    first = environment.client.get_workflow_handle(handle.id, run_id=first_run)
    assert (await first.describe()).status is WorkflowExecutionStatus.CONTINUED_AS_NEW
    run = world.run(start)
    assert run is not None
    assert (run.status, run.counters.businesses_total, run.counters.evaluated) == (
        FanOutStatus.COMPLETED,
        BUSINESSES,
        BUSINESSES,
    )
    assert run.counters.applies == BUSINESSES
    decided = world.decided(start)
    assert len(decided) == BUSINESSES
    assert {d.tenant_id for d in decided} == {tenant for tenant, _ in world.businesses}
    assert {d.trigger_ref for d in decided} == {start.trigger_ref}
    assert len(world.store.events) == BUSINESSES
    assert progress is not None
    assert progress.batches == 3


async def test_the_hold_and_a_pause_stop_it_until_released_and_resumed(
    environment: WorkflowEnvironment,
) -> None:
    world = build_world(environment)
    start = world.start()
    await asyncio.to_thread(
        SetHold(world.units).run, HoldControl(ADMIN, "Deploy of the rulebook in progress")
    )
    async with worker_of(environment, world):
        await asyncio.to_thread(world.fanouts.start, start)
        held = await in_status(world, start, FanOutStatus.HELD)
        assert held.status_reason == "Deploy of the rulebook in progress"
        await asyncio.sleep(1.0)
        assert world.decided(start) == [], "nothing is decided while held"
        pause = PauseFanOut(world.units, world.fanouts)
        await asyncio.to_thread(pause.run, world.control(start))
        await asyncio.to_thread(ReleaseHold(world.units, world.fanouts).run, HoldControl(ADMIN))
        await asyncio.sleep(1.5)
        run = world.run(start)
        assert run is not None
        assert (run.status, world.decided(start)) == (FanOutStatus.PAUSED, [])
        resume = ResumeFanOut(world.units, world.fanouts)
        await asyncio.to_thread(resume.run, world.control(start, ""))
        result = await result_of(environment, start)
    assert (result.status, result.counters.evaluated) == (FanOutStatus.COMPLETED, BUSINESSES)
    assert [entry.action for entry in world.store.audit] == [
        "applicability.fanout.hold",
        PAUSE_ACTION,
        "applicability.fanout.release",
        "applicability.fanout.resume",
    ]


async def test_a_cancellation_ends_it_at_the_boundary_and_keeps_its_decisions(
    environment: WorkflowEnvironment,
) -> None:
    world = build_world(environment)
    world.profiles.gate_after = 1_010
    start = world.start()
    async with worker_of(environment, world):
        await asyncio.to_thread(world.fanouts.start, start)
        assert await asyncio.to_thread(world.profiles.reached.wait, WAIT)
        cancel = CancelFanOut(world.units, world.fanouts)
        await asyncio.to_thread(cancel.run, world.control(start))
        world.profiles.gate.set()
        result = await result_of(environment, start)
    assert (result.status, result.counters.evaluated) == (FanOutStatus.CANCELLED, 2_000)
    run = world.run(start)
    assert run is not None
    assert (run.status, run.counters.evaluated) == (FanOutStatus.CANCELLED, 2_000)
    assert len(world.decided(start)) == 2_000, "the decisions made stay"


async def test_too_many_flips_pause_it_as_the_system_until_a_person_resumes(
    environment: WorkflowEnvironment,
) -> None:
    world = build_world(environment, composition_every=20)
    old = world.rulebook.put(rule_version(REGULAR)).rule_version_id
    for tenant, business in world.businesses:
        decision = Decision(
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
        world.store.decisions[decision.decision_id] = decision
    start = world.start(old)
    async with worker_of(environment, world):
        await asyncio.to_thread(world.fanouts.start, start)
        paused = await in_status(world, start, FanOutStatus.PAUSED)
        assert (paused.counters.evaluated, paused.counters.flips_compared) == (1_000, 1_000)
        assert paused.counters.flips > 20, "more than 2% flipped"
        assert paused.status_by == "system:applicability-engine"
        (entry,) = [e for e in world.store.audit if e.action == PAUSE_ACTION]
        assert (entry.actor, entry.tenant_id, entry.reason) == (
            SYSTEM,
            None,
            paused.status_reason,
        )
        resume = ResumeFanOut(world.units, world.fanouts)
        await asyncio.to_thread(resume.run, world.control(start, "The flips are expected"))
        result = await result_of(environment, start)
    assert (result.status, result.counters.flips_compared) == (FanOutStatus.COMPLETED, BUSINESSES)
    assert result.counters.flips == len(world.compositions)
    assert len([e for e in world.store.audit if e.action == PAUSE_ACTION]) == 1
