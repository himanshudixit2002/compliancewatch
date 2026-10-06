"""Fakes and builders for tests of this service and of services that consume its events: fixed
ids, a fixed clock, a profile service and a rulebook held in memory, and ``LocalFanOuts``, which
runs fan-outs on threads of the process instead of Temporal."""

import asyncio
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from applicability_engine.application.fanout_flow import (
    BatchFailedError,
    BatchIn,
    BatchOut,
    Continued,
    Controls,
    FanOutRequest,
    Finished,
    RunChange,
    RunRef,
    RunState,
    Wakeups,
    drive,
)
from applicability_engine.domain.fanout import FanOutSignal, FanOutStart
from applicability_engine.domain.model import RuleInForce, RuleVersionSpec, Schedule
from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import BusinessId, RuleVersionId, TenantId
from domain_kernel.ontology import AttributeLevel
from domain_kernel.periods import EffectivePeriod
from domain_kernel.predicates import Specification, specification_from_mapping
from domain_kernel.profiles import ProfileSnapshot
from domain_kernel.recurrence import Recurrence
from domain_kernel.status import RuleVersionStatus
from py_common.temporal import ActivityBase

TENANT = TenantId.new()
OTHER_TENANT = TenantId.new()
BUSINESS = BusinessId.new()
NOW = datetime(2026, 10, 1, 4, 30, tzinfo=UTC)
FY = FinancialYear(2026)
EFFECTIVE = date(2026, 4, 1)


def clock() -> datetime:
    return NOW


def rule_version(
    specification: Specification | Mapping[str, object],
    *,
    status: RuleVersionStatus = RuleVersionStatus.PUBLISHED,
    rule_version_id: RuleVersionId | None = None,
    rule_key: str | None = "example_rule",
    level: AttributeLevel | None = AttributeLevel.REGISTRATION,
    schedule: Schedule | None = None,
) -> RuleVersionSpec:
    return RuleVersionSpec(
        rule_version_id=rule_version_id or RuleVersionId.new(),
        status=status,
        specification=specification
        if isinstance(specification, Specification)
        else specification_from_mapping(specification),
        rule_key=rule_key,
        level=level,
        schedule=schedule,
    )


def rule_in_force(
    specification: Specification | Mapping[str, object],
    *,
    rule_key: str = "example_rule",
    level: AttributeLevel = AttributeLevel.REGISTRATION,
    effective_from: date = EFFECTIVE,
    effective_to: date | None = None,
    rule_version_id: RuleVersionId | None = None,
    status: RuleVersionStatus = RuleVersionStatus.PUBLISHED,
    recurrence: Recurrence | None = None,
    due_in_days: int | None = None,
) -> RuleInForce:
    """A version in force from ``effective_from`` for nodes of ``level``, published unless
    ``status`` says otherwise, with its schedule: ``recurrence`` for a duty that repeats, else a
    one-off due ``due_in_days`` after the decision."""
    schedule = Schedule(EffectivePeriod(effective_from, effective_to), recurrence, due_in_days)
    return RuleInForce(
        spec=rule_version(
            specification,
            status=status,
            rule_version_id=rule_version_id,
            rule_key=rule_key,
            level=level,
            schedule=schedule,
        ),
        rule_key=rule_key,
        level=level,
        effective_from=effective_from,
        effective_to=effective_to,
    )


def superseded_rule(
    specification: Specification | Mapping[str, object],
    *,
    effective_from: date,
    effective_to: date,
    recurrence: Recurrence | None,
    due_in_days: int | None = None,
    rule_key: str = "example_rule",
    level: AttributeLevel = AttributeLevel.REGISTRATION,
) -> RuleInForce:
    """A version superseded from ``effective_to``, as the listing of the versions superseded
    since a day gives it."""
    return rule_in_force(
        specification,
        rule_key=rule_key,
        level=level,
        effective_from=effective_from,
        effective_to=effective_to,
        status=RuleVersionStatus.SUPERSEDED,
        recurrence=recurrence,
        due_in_days=due_in_days,
    )


@dataclass
class MemoryProfiles:
    """``ProfileReader`` over snapshots keyed by tenant and business, and the registrations of
    each entity; records the years asked."""

    snapshots: dict[tuple[TenantId, BusinessId], ProfileSnapshot] = field(default_factory=dict)
    children: dict[tuple[TenantId, BusinessId], list[BusinessId]] = field(default_factory=dict)
    asked: list[FinancialYear | None] = field(default_factory=list)

    def put(
        self,
        attributes: Mapping[str, object],
        *,
        tenant_id: TenantId = TENANT,
        business_id: BusinessId = BUSINESS,
        version: int = 1,
        level: AttributeLevel | None = AttributeLevel.REGISTRATION,
        lineage: Sequence[BusinessId] = (),
    ) -> ProfileSnapshot:
        snapshot = ProfileSnapshot(
            business_id,
            tenant_id,
            version,
            attributes,
            as_of_fy=FY,
            level=level,
            lineage=tuple(lineage),
        )
        self.snapshots[(tenant_id, business_id)] = snapshot
        if lineage and level is AttributeLevel.REGISTRATION:
            registrations = self.children.setdefault((tenant_id, lineage[0]), [])
            if business_id not in registrations:
                registrations.append(business_id)
        return snapshot

    def snapshot(
        self, tenant_id: TenantId, business_id: BusinessId, fy: FinancialYear | None
    ) -> ProfileSnapshot | None:
        self.asked.append(fy)
        return self.snapshots.get((tenant_id, business_id))

    def registrations(
        self, tenant_id: TenantId, entity_id: BusinessId
    ) -> Sequence[BusinessId] | None:
        if (tenant_id, entity_id) not in self.snapshots:
            return None
        return tuple(self.children.get((tenant_id, entity_id), ()))


@dataclass
class MemoryRulebook:
    """``RulebookReader`` over rule versions keyed by id, the versions in force and the
    superseded ones; records the days asked for (``asked`` of the in-force listing,
    ``asked_superseded`` of the other) and how often the listings were forgotten."""

    versions: dict[RuleVersionId, RuleVersionSpec] = field(default_factory=dict)
    in_force: list[RuleInForce] = field(default_factory=list)
    superseded: list[RuleInForce] = field(default_factory=list)
    asked: list[date] = field(default_factory=list)
    asked_superseded: list[date] = field(default_factory=list)
    forgotten: int = 0

    def put(self, version: RuleVersionSpec) -> RuleVersionSpec:
        self.versions[version.rule_version_id] = version
        return version

    def put_in_force(self, rule: RuleInForce) -> RuleInForce:
        self.put(rule.spec)
        self.in_force.append(rule)
        return rule

    def put_superseded(self, rule: RuleInForce) -> RuleInForce:
        """A version that ended: read by id, and listed among the versions superseded since a
        day on or before its ``effective_to``. The listing gives whatever status was put (the
        rulebook never lists a withdrawn one), so a test can show the engine refuses one too."""
        self.put(rule.spec)
        self.superseded.append(rule)
        return rule

    def rule_version(self, rule_version_id: RuleVersionId) -> RuleVersionSpec | None:
        return self.versions.get(rule_version_id)

    def rules_in_force(self, as_of: date, level: AttributeLevel) -> Sequence[RuleInForce]:
        self.asked.append(as_of)
        return tuple(
            rule
            for rule in self.in_force
            if rule.level is level
            and rule.effective_from <= as_of
            and (rule.effective_to is None or as_of < rule.effective_to)
        )

    def rules_superseded_since(self, since: date, level: AttributeLevel) -> Sequence[RuleInForce]:
        self.asked_superseded.append(since)
        return tuple(
            rule
            for rule in self.superseded
            if rule.level is level and rule.effective_to is not None and rule.effective_to >= since
        )

    def forget_in_force(self) -> None:
        self.forgotten += 1


class ThreadWakeups(Wakeups):
    """``Wakeups`` a signal from another thread sets: a waiting fan-out wakes on the event."""

    def __init__(self) -> None:
        super().__init__()
        self.event = threading.Event()
        self._lock = threading.Lock()

    def signal(self, signal: FanOutSignal) -> None:
        with self._lock:
            super().signal(signal)
        self.event.set()

    def take(self) -> bool:
        with self._lock:
            self.event.clear()
            return super().take()


class LocalSteps:
    """``FanOutSteps`` that call the fan-out's activities in the process, as Temporal would on
    the worker, and wait on the run's ``ThreadWakeups``."""

    def __init__(self, activities: Mapping[str, ActivityBase[Any, Any]], wakeups: ThreadWakeups):
        self._activities = activities
        self._wakeups = wakeups

    async def _call(self, name: str, value: object) -> Any:
        return await self._activities[name].execute(value)

    async def begin(self, request: FanOutRequest) -> RunState:
        begun: RunState = await self._call("applicability.fanout.begin", request)
        return begun

    async def controls(self, rule_version_id: UUID) -> Controls:
        found: Controls = await self._call(
            "applicability.fanout.controls", RunRef(rule_version_id=rule_version_id)
        )
        return found

    async def evaluate(self, batch: BatchIn) -> BatchOut:
        try:
            decided: BatchOut = await self._call("applicability.fanout.evaluate_batch", batch)
        except Exception as error:
            raise BatchFailedError(f"{type(error).__name__}: {error}") from error
        return decided

    async def update(self, change: RunChange) -> RunState:
        stored: RunState = await self._call("applicability.fanout.update", change)
        return stored

    async def wait(self, seconds: float) -> None:
        if self._wakeups.take():
            return
        await asyncio.to_thread(self._wakeups.event.wait, seconds)
        self._wakeups.take()

    def history_is_long(self) -> bool:
        return False


class LocalFanOuts:
    """``FanOutWorkflows`` for tests and demos without Temporal: each fan-out runs on a thread of
    this process through the loop the workflow runs (``application.fanout_flow.drive``), calling
    the same activities (``application.fanout_activities.fanout_activities``) directly, and
    continues as new on the same thread. A version starts once; a signal wakes its loop.
    ``options`` are ``FanOutRequest`` fields, such as ``poll_seconds`` or ``batch_size``."""

    def __init__(self, activities: Sequence[ActivityBase[Any, Any]], **options: object) -> None:
        self._activities = {activity.name: activity for activity in activities}
        self._options = {"poll_seconds": 0.05, **options}
        self._lock = threading.Lock()
        self._runs: dict[RuleVersionId, tuple[threading.Thread, ThreadWakeups]] = {}
        self.finished: dict[RuleVersionId, Finished] = {}
        self.failures: dict[RuleVersionId, BaseException] = {}

    def start(self, start: FanOutStart) -> bool:
        request = FanOutRequest.of(start, **self._options)
        wakeups = ThreadWakeups()
        thread = threading.Thread(
            target=self._run, args=(request, wakeups), name=f"fan-out-{start.rule_version_id}"
        )
        with self._lock:
            if start.rule_version_id in self._runs:
                return False
            self._runs[start.rule_version_id] = (thread, wakeups)
        thread.daemon = True
        thread.start()
        return True

    def signal(self, rule_version_id: RuleVersionId, signal: FanOutSignal) -> None:
        with self._lock:
            found = self._runs.get(rule_version_id)
        if found is not None:
            found[1].signal(signal)

    def join(self, rule_version_id: RuleVersionId, timeout: float = 30.0) -> Finished | None:
        """Wait for the version's fan-out to finish; its outcome, or None if it has not."""
        with self._lock:
            found = self._runs.get(rule_version_id)
        if found is not None:
            found[0].join(timeout)
        return self.finished.get(rule_version_id)

    def _run(self, request: FanOutRequest, wakeups: ThreadWakeups) -> None:
        rule_version_id = RuleVersionId(request.rule_version_id)
        steps = LocalSteps(self._activities, wakeups)
        try:
            outcome = asyncio.run(drive(request, steps, wakeups))
            while isinstance(outcome, Continued):
                outcome = asyncio.run(drive(outcome.request, steps, wakeups))
        except BaseException as error:  # a test reads it; the thread ends either way
            self.failures[rule_version_id] = error
            return
        self.finished[rule_version_id] = outcome
