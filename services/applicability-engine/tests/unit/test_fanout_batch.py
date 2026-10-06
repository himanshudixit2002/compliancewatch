"""A fan-out batch on the memory store: a page of the directory decided one tenant group at a time,
with no unit of work open while a profile is read, the decisions stored once with their event by
the emit rule, the review queue kept in step, and flips counted against the superseded version."""

from datetime import UTC, date, datetime

import pytest

import ontology as ontology_package
from applicability_engine.application.fanout_batch import BatchRequest, EvaluateBatch
from applicability_engine.domain.directory import DirectoryEntry, DirectoryKey
from applicability_engine.domain.errors import (
    RuleVersionNotFoundError,
    RuleVersionNotPublishedError,
)
from applicability_engine.domain.events import ApplicabilityDecided
from applicability_engine.domain.fanout import FanOutStart
from applicability_engine.domain.model import Decision, Schedule, Trigger
from applicability_engine.infrastructure.memory import MemoryBusinessDirectory, MemoryStore
from applicability_engine.testing import MemoryProfiles, MemoryRulebook, rule_version
from domain_kernel.confidence import CERTAIN
from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import BusinessId, CorrelationId, DecisionId, EventId, TenantId
from domain_kernel.ontology import AttributeLevel
from domain_kernel.periods import EffectivePeriod
from domain_kernel.predicates import Applicability
from domain_kernel.profiles import ProfileSnapshot
from domain_kernel.recurrence import Recurrence
from domain_kernel.status import RuleVersionStatus

NOW = datetime(2026, 10, 5, 6, 0, tzinfo=UTC)
REGULAR = {"attribute": "registration_type", "operator": "eq", "value": "regular"}
FREE_TEXT = {"attribute": "business_category", "free_text": "Example premises shared with a hotel"}
SEPTEMBER_STILL_DUE = Schedule(
    EffectivePeriod(date(2026, 4, 1), date(2026, 10, 1)), Recurrence.monthly(20)
)
"""A monthly return superseded from 1 October: September, due 20 October, is still its own."""


def clock() -> datetime:
    return NOW


class World:
    """Two tenants with registrations in the directory, each regular or composition."""

    def __init__(self, specification: dict[str, object] | None = None) -> None:
        self.store = MemoryStore()
        self.profiles = MemoryProfiles()
        self.rulebook = MemoryRulebook()
        self.version = self.rulebook.put(rule_version(specification or REGULAR))
        self.tenants = sorted([TenantId.new(), TenantId.new()], key=lambda t: t.value)
        self.event = EventId.new()
        self.batch = EvaluateBatch(
            MemoryBusinessDirectory(self.store),
            self.store,
            self.profiles,
            self.rulebook,
            ontology_package.load(),
            clock=clock,
        )

    def business(self, tenant: TenantId, kind: str = "regular") -> BusinessId:
        entity, business = BusinessId.new(), BusinessId.new()
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
        return business

    def start(self, *superseded: object) -> FanOutStart:
        return FanOutStart(
            rule_version_id=self.version.rule_version_id,
            rule_key="example_rule",
            level=AttributeLevel.REGISTRATION,
            trigger_event_id=self.event,
            supersedes=tuple(superseded),  # type: ignore[arg-type]
            correlation_id=CorrelationId.new(),
        )

    def decided(self) -> list[ApplicabilityDecided]:
        return [e for e in self.store.events if isinstance(e, ApplicabilityDecided)]


def test_a_page_is_decided_tenant_by_tenant_with_no_unit_open_while_reading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = World()
    first, second = world.tenants
    regular = [world.business(first) for _ in range(2)] + [world.business(second)]
    composition = world.business(second, "composition")
    reads: list[bool] = []
    original = world.profiles.snapshot

    def snapshot(
        tenant: TenantId, business: BusinessId, fy: FinancialYear | None
    ) -> ProfileSnapshot | None:
        reads.append(world.store.lock.locked())
        return original(tenant, business, fy)

    monkeypatch.setattr(world.profiles, "snapshot", snapshot)
    groups: list[int] = []
    outcome = world.batch.run(
        BatchRequest(world.start()), progress=lambda: groups.append(len(world.store.decisions))
    )
    assert reads == [False] * 4, "no unit of work open while a profile is read"
    assert groups == [2, 4], "one tenant group at a time"
    assert (outcome.read, outcome.evaluated, outcome.applies, outcome.appended) == (4, 4, 3, 4)
    assert (outcome.published, outcome.skipped, outcome.done) == (4, 0, True)
    decisions = list(world.store.decisions.values())
    assert {d.trigger for d in decisions} == {Trigger.RULE_PUBLISHED}
    assert {d.trigger_ref for d in decisions} == {f"rule.published:{world.event}"}
    results = {d.business_id: d.result for d in decisions}
    assert {results[b] for b in regular} == {Applicability.APPLIES}
    assert results[composition] is Applicability.NOT_APPLICABLE
    assert {event.causation_id for event in world.decided()} == {world.event}
    assert {event.trigger for event in world.decided()} == {Trigger.RULE_PUBLISHED}


def test_pages_follow_the_cursor_and_a_retried_page_stores_nothing_twice() -> None:
    world = World()
    for tenant in world.tenants:
        for _ in range(3):
            world.business(tenant)
    start = world.start()
    first = world.batch.run(BatchRequest(start, limit=4))
    assert (first.read, first.done) == (4, False)
    assert first.last is not None
    second = world.batch.run(BatchRequest(start, after=first.last, limit=4))
    assert (second.read, second.done) == (2, True)
    assert len(world.store.decisions) == 6
    again = world.batch.run(BatchRequest(start, limit=4))
    assert (again.evaluated, again.applies, again.appended, again.published) == (4, 4, 0, 0)
    assert len(world.store.decisions) == 6
    assert len(world.decided()) == 6
    empty = world.batch.run(BatchRequest(start, after=second.last, limit=4))
    assert (empty.read, empty.last, empty.done) == (0, second.last, True)


def test_a_business_the_profile_service_no_longer_has_is_skipped() -> None:
    world = World()
    tenant = world.tenants[0]
    kept = world.business(tenant)
    gone = world.business(tenant)
    del world.profiles.snapshots[(tenant, gone)]
    outcome = world.batch.run(BatchRequest(world.start()))
    assert (outcome.read, outcome.evaluated, outcome.skipped) == (2, 1, 1)
    assert [d.business_id for d in world.store.decisions.values()] == [kept]


def test_an_unchanged_result_is_stored_quietly_and_free_text_opens_a_review() -> None:
    world = World({"all_of": [REGULAR, FREE_TEXT]})
    tenant = world.tenants[0]
    business = world.business(tenant)
    earlier = world.business(tenant, "composition")
    with world.store(tenant) as uow:
        uow.decisions.add(
            Decision(
                decision_id=DecisionId.new(),
                tenant_id=tenant,
                business_id=earlier,
                rule_version_id=world.version.rule_version_id,
                result=Applicability.NOT_APPLICABLE,
                confidence=CERTAIN,
                evaluated=(),
                profile_version=1,
                decided_at=datetime(2026, 10, 1, tzinfo=UTC),
                trigger=Trigger.PROFILE_UPDATED,
                as_of_fy=FinancialYear(2026),
            )
        )
    outcome = world.batch.run(BatchRequest(world.start()))
    assert (outcome.appended, outcome.published) == (2, 1)
    (published,) = world.decided()
    assert published.business_id == business
    (item,) = world.store.reviews.values()
    assert (item.business_id, item.reason.value) == (business, "free_text")


def test_flips_are_counted_against_the_latest_decision_of_the_superseded_versions() -> None:
    world = World()
    tenant = world.tenants[0]
    old = world.rulebook.put(rule_version(REGULAR)).rule_version_id
    older = world.rulebook.put(rule_version(REGULAR)).rule_version_id
    same, flipped, newer, unseen = (world.business(tenant) for _ in range(4))
    with world.store(tenant) as uow:
        for business, version, result, day in (
            (same, old, Applicability.APPLIES, 1),
            (flipped, old, Applicability.NOT_APPLICABLE, 1),
            (newer, older, Applicability.NOT_APPLICABLE, 1),
            (newer, old, Applicability.APPLIES, 2),
        ):
            uow.decisions.add(
                Decision(
                    decision_id=DecisionId.new(),
                    tenant_id=tenant,
                    business_id=business,
                    rule_version_id=version,
                    result=result,
                    confidence=CERTAIN,
                    evaluated=(),
                    profile_version=1,
                    decided_at=datetime(2026, 10, day, tzinfo=UTC),
                    trigger=Trigger.PROFILE_UPDATED,
                    as_of_fy=FinancialYear(2026),
                )
            )
    outcome = world.batch.run(BatchRequest(world.start(old, older)))
    assert (outcome.evaluated, outcome.flips_compared, outcome.flips) == (4, 3, 1)
    assert unseen in {d.business_id for d in world.store.decisions.values()}


def test_only_a_published_version_fans_out() -> None:
    world = World()
    world.business(world.tenants[0])
    withdrawn = world.rulebook.put(rule_version(REGULAR, status=RuleVersionStatus.WITHDRAWN))
    start = world.start()
    with pytest.raises(RuleVersionNotPublishedError):
        world.batch.run(
            BatchRequest(
                FanOutStart(
                    withdrawn.rule_version_id,
                    "example_rule",
                    AttributeLevel.REGISTRATION,
                    start.trigger_event_id,
                )
            )
        )
    del world.rulebook.versions[world.version.rule_version_id]
    with pytest.raises(RuleVersionNotFoundError):
        world.batch.run(BatchRequest(start))
    assert world.store.decisions == {}


def test_a_fan_out_its_version_was_superseded_under_goes_on_while_a_return_is_still_due() -> None:
    """Superseded on 1 October, the version still governs September, due 20 October: on 5 October
    its fan-out decides the businesses it had not reached; on 25 October it ends, and so does a
    superseded version whose schedule is unknown."""
    world = World()
    business = world.business(world.tenants[0])
    superseded = RuleVersionStatus.SUPERSEDED
    old = world.rulebook.put(rule_version(REGULAR, status=superseded, schedule=SEPTEMBER_STILL_DUE))
    start = FanOutStart(
        old.rule_version_id, "example_rule", AttributeLevel.REGISTRATION, world.event
    )
    outcome = world.batch.run(BatchRequest(start))
    assert (outcome.evaluated, outcome.applies, outcome.appended, outcome.published) == (1, 1, 1, 1)
    (decision,) = world.store.decisions.values()
    assert (decision.business_id, decision.rule_version_id, decision.trigger) == (
        business,
        old.rule_version_id,
        Trigger.RULE_PUBLISHED,
    )

    late = EvaluateBatch(
        MemoryBusinessDirectory(world.store),
        world.store,
        world.profiles,
        world.rulebook,
        ontology_package.load(),
        clock=lambda: datetime(2026, 10, 25, 6, 0, tzinfo=UTC),
    )
    with pytest.raises(RuleVersionNotPublishedError, match="superseded"):
        late.run(BatchRequest(start))
    unknown = world.rulebook.put(rule_version(REGULAR, status=superseded))
    with pytest.raises(RuleVersionNotPublishedError):
        world.batch.run(
            BatchRequest(
                FanOutStart(
                    unknown.rule_version_id,
                    "example_rule",
                    AttributeLevel.REGISTRATION,
                    world.event,
                )
            )
        )
    assert len(world.store.decisions) == 1


def test_the_newer_versions_fan_out_decides_the_newer_version_alone() -> None:
    """The businesses keep their decisions of the version it supersedes, still due or not:
    nothing decides that version again."""
    world = World()
    for _ in range(2):
        world.business(world.tenants[0])
    old = world.rulebook.put(
        rule_version(REGULAR, status=RuleVersionStatus.SUPERSEDED, schedule=SEPTEMBER_STILL_DUE)
    )
    outcome = world.batch.run(BatchRequest(world.start(old.rule_version_id)))
    assert (outcome.evaluated, outcome.appended) == (2, 2)
    decided = {d.rule_version_id for d in world.store.decisions.values()}
    assert decided == {world.version.rule_version_id}


def test_the_directory_reads_by_tenant_then_node_and_counts_a_level() -> None:
    world = World()
    for tenant in world.tenants:
        world.business(tenant)
        world.business(tenant)
    directory = MemoryBusinessDirectory(world.store)
    entries = directory.entries(level=AttributeLevel.REGISTRATION)
    keys = [(entry.tenant_id.value, entry.business_id.value) for entry in entries]
    assert keys == sorted(keys)
    after = directory.entries(
        level=AttributeLevel.REGISTRATION, after=DirectoryKey.of(entries[1]), limit=10
    )
    assert after == entries[2:]
    assert directory.count(level=AttributeLevel.REGISTRATION) == 4
    assert directory.count(level=AttributeLevel.ENTITY) == 0
