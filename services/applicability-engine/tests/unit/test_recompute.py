"""ApplyProfileUpdate on the memory store, with the profile service and the rulebook faked in
memory: what a profile.updated event evaluates, stores, publishes and opens for review."""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import pytest

import ontology as ontology_package
from applicability_engine.application.recompute import (
    ApplyProfileUpdate,
    ProfileUpdate,
    publishes,
)
from applicability_engine.application.review import ReviewChange
from applicability_engine.domain.directory import DirectoryEntry
from applicability_engine.domain.events import ApplicabilityDecided
from applicability_engine.domain.model import Decision, RuleInForce, Trigger, decision_id_for
from applicability_engine.domain.review import Resolution, ReviewReason, ReviewStatus
from applicability_engine.infrastructure.memory import MemoryStore
from applicability_engine.testing import (
    FY,
    NOW,
    OTHER_TENANT,
    TENANT,
    MemoryProfiles,
    MemoryRulebook,
    rule_in_force,
    superseded_rule,
)
from domain_kernel.confidence import CERTAIN, ZERO
from domain_kernel.ids import BusinessId, CorrelationId, DecisionId, EventId
from domain_kernel.ontology import AttributeLevel
from domain_kernel.predicates import Applicability
from domain_kernel.recurrence import Recurrence
from domain_kernel.status import RuleVersionStatus

ENTITY = BusinessId.new()
REGISTRATION = BusinessId.new()
SECOND_REGISTRATION = BusinessId.new()
LOCATION = BusinessId.new()
REGULAR = {"attribute": "registration_type", "operator": "eq", "value": "regular"}
MONTHLY = {"attribute": "filing_scheme", "operator": "eq", "value": "regular_monthly"}
FREE_TEXT = {"attribute": "business_category", "free_text": "Example premises shared with a hotel"}
TODAY = date(2026, 10, 1)
"""NOW in India."""


@dataclass
class Ticking:
    """A clock one second later on every call, from ``start``."""

    ticks: int = 0
    start: datetime = NOW

    def __call__(self) -> datetime:
        self.ticks += 1
        return self.start + timedelta(seconds=self.ticks)


@dataclass
class Setup:
    store: MemoryStore = field(default_factory=MemoryStore)
    profiles: MemoryProfiles = field(default_factory=MemoryProfiles)
    rulebook: MemoryRulebook = field(default_factory=MemoryRulebook)
    clock: Ticking = field(default_factory=Ticking)

    def recompute(
        self, *, enabled: bool = True, lookahead_days: int = 0, superseded_lookback_days: int = 0
    ) -> ApplyProfileUpdate:
        return ApplyProfileUpdate(
            self.profiles,
            self.rulebook,
            ontology_package.load(),
            enabled=enabled,
            lookahead_days=lookahead_days,
            superseded_lookback_days=superseded_lookback_days,
            clock=self.clock,
        )

    def on(self, day: date) -> None:
        """The clock at 10:00 in India on ``day``."""
        self.clock = Ticking(start=datetime(day.year, day.month, day.day, 4, 30, tzinfo=UTC))

    def hierarchy(self, registration: dict[str, object] | None = None) -> None:
        """An entity with two registrations and a location under the first."""
        self.profiles.put(
            {"state_codes": frozenset({"29"})}, business_id=ENTITY, level=AttributeLevel.ENTITY
        )
        self.profiles.put(
            registration if registration is not None else {"registration_type": "regular"},
            business_id=REGISTRATION,
            lineage=[ENTITY],
            version=3,
        )
        self.profiles.put(
            {"registration_type": "composition"}, business_id=SECOND_REGISTRATION, lineage=[ENTITY]
        )
        self.profiles.put(
            {"registration_type": "regular"},
            business_id=LOCATION,
            level=AttributeLevel.LOCATION,
            lineage=[ENTITY, REGISTRATION],
        )

    def decided(self) -> list[ApplicabilityDecided]:
        return [e for e in self.store.events if isinstance(e, ApplicabilityDecided)]

    def latest(self, business: BusinessId, rule: object) -> Decision:
        with self.store(TENANT) as uow:
            found = uow.decisions.latest(business, rule.rule_version_id)  # type: ignore[attr-defined]
        assert found is not None
        return found


def update(business: BusinessId = REGISTRATION, **changes: object) -> ProfileUpdate:
    values: dict[str, object] = {
        "tenant_id": TENANT,
        "event_id": EventId.new(),
        "business_id": business,
        "profile_version": 2,
        "changed_attributes": ("registration_type",),
        "correlation_id": CorrelationId.new(),
    }
    values.update(changes)
    return ProfileUpdate(**values)  # type: ignore[arg-type]


@pytest.fixture
def setup() -> Setup:
    setup = Setup()
    setup.hierarchy()
    return setup


def test_a_registration_is_evaluated_against_the_rules_of_its_level(setup: Setup) -> None:
    regular = setup.rulebook.put_in_force(rule_in_force(REGULAR, rule_key="a_regular"))
    setup.rulebook.put_in_force(
        rule_in_force(REGULAR, rule_key="b_entity", level=AttributeLevel.ENTITY)
    )
    event = update()
    done = setup.recompute().run(event, setup.store)

    (decision,) = done.appended
    assert (decision.business_id, decision.rule_version_id) == (
        REGISTRATION,
        regular.rule_version_id,
    )
    assert (decision.result, decision.confidence, decision.trigger) == (
        Applicability.APPLIES,
        CERTAIN,
        Trigger.PROFILE_UPDATED,
    )
    assert decision.trigger_ref == f"profile.updated:{event.event_id}"
    assert decision.decision_id == decision_id_for(
        decision.trigger_ref, REGISTRATION, regular.rule_version_id
    )
    assert (decision.profile_version, decision.as_of_fy) == (3, FY)
    assert setup.rulebook.asked == [TODAY]
    (published,) = setup.decided()
    assert published.decision_id == decision.decision_id
    assert (published.causation_id, published.correlation_id) == (
        event.event_id,
        event.correlation_id,
    )
    assert setup.store.directory == {
        REGISTRATION: DirectoryEntry(
            TENANT, REGISTRATION, AttributeLevel.REGISTRATION, ENTITY, ENTITY
        )
    }


def test_an_entity_change_reaches_every_registration_under_it(setup: Setup) -> None:
    regular = setup.rulebook.put_in_force(rule_in_force(REGULAR))
    entity_rule = setup.rulebook.put_in_force(
        rule_in_force(
            {"attribute": "state_codes", "operator": "contains", "value": "29"},
            rule_key="entity_rule",
            level=AttributeLevel.ENTITY,
        )
    )
    done = setup.recompute().run(update(ENTITY, changed_attributes=("state_codes",)), setup.store)

    decided = {(d.business_id, d.rule_version_id): d.result for d in done.appended}
    assert decided == {
        (ENTITY, entity_rule.rule_version_id): Applicability.APPLIES,
        (REGISTRATION, regular.rule_version_id): Applicability.APPLIES,
        (SECOND_REGISTRATION, regular.rule_version_id): Applicability.NOT_APPLICABLE,
    }
    assert set(setup.store.directory) == {ENTITY, REGISTRATION, SECOND_REGISTRATION}
    assert setup.store.directory[ENTITY] == DirectoryEntry(
        TENANT, ENTITY, AttributeLevel.ENTITY, None, ENTITY
    )
    assert setup.store.directory[SECOND_REGISTRATION].parent_id == ENTITY
    assert LOCATION not in setup.store.directory, "the profile lists no locations"


def test_a_location_change_recomputes_the_location_with_its_lineage(setup: Setup) -> None:
    rule = setup.rulebook.put_in_force(rule_in_force(REGULAR, level=AttributeLevel.LOCATION))
    done = setup.recompute().run(update(LOCATION), setup.store)
    assert [(d.business_id, d.rule_version_id) for d in done.appended] == [
        (LOCATION, rule.rule_version_id)
    ]
    assert setup.store.directory[LOCATION] == DirectoryEntry(
        TENANT, LOCATION, AttributeLevel.LOCATION, REGISTRATION, ENTITY
    )


def test_the_same_event_again_stores_and_publishes_nothing(setup: Setup) -> None:
    setup.rulebook.put_in_force(rule_in_force(REGULAR))
    setup.rulebook.put_in_force(rule_in_force(FREE_TEXT, rule_key="judged"))
    event = update()
    recompute = setup.recompute()
    first = recompute.run(event, setup.store)
    assert len(first.appended) == 2
    stored, events, items = (
        dict(setup.store.decisions),
        list(setup.store.events),
        dict(setup.store.reviews),
    )

    again = recompute.run(event, setup.store)
    assert (again.appended, again.published, again.listed) == ((), (), 0)
    assert setup.store.decisions == stored
    assert setup.store.events == events
    assert setup.store.reviews == items


def test_only_a_result_that_applies_or_changes_publishes(setup: Setup) -> None:
    rule = setup.rulebook.put_in_force(rule_in_force(MONTHLY))
    recompute = setup.recompute()
    setup.profiles.put(
        {"filing_scheme": "regular_qrmp"}, business_id=REGISTRATION, lineage=[ENTITY]
    )
    first = recompute.run(update(), setup.store)
    assert [d.result for d in first.appended] == [Applicability.NOT_APPLICABLE]
    assert len(first.published) == 1, "the first decision of a pair differs from none"

    unchanged = recompute.run(update(), setup.store)
    assert len(unchanged.appended) == 1, "every evaluation is stored"
    assert unchanged.published == ()

    setup.profiles.put(
        {"filing_scheme": "regular_monthly"}, business_id=REGISTRATION, lineage=[ENTITY]
    )
    flipped = recompute.run(update(), setup.store)
    assert [d.result for d in flipped.appended] == [Applicability.APPLIES]
    assert len(flipped.published) == 1
    again = recompute.run(update(), setup.store)
    assert len(again.published) == 1, "applies always goes out; obligations are idempotent"
    assert setup.latest(REGISTRATION, rule).result is Applicability.APPLIES
    assert len(setup.decided()) == 3


def test_the_emit_rule_compares_the_result_and_the_need_for_review() -> None:
    def decision(result: Applicability) -> Decision:
        return Decision(
            decision_id=DecisionId.new(),
            tenant_id=TENANT,
            business_id=REGISTRATION,
            rule_version_id=rule_in_force(REGULAR).rule_version_id,
            result=result,
            confidence=ZERO if result is Applicability.UNSURE else CERTAIN,
            evaluated=(),
            profile_version=1,
            decided_at=NOW,
            trigger=Trigger.PROFILE_UPDATED,
            as_of_fy=FY,
        )

    applies, not_applicable, unsure = (
        decision(Applicability.APPLIES),
        decision(Applicability.NOT_APPLICABLE),
        decision(Applicability.UNSURE),
    )
    assert publishes(applies, applies)
    assert publishes(not_applicable, None)
    assert publishes(not_applicable, applies)
    assert publishes(unsure, not_applicable)
    assert not publishes(not_applicable, not_applicable)
    assert not publishes(unsure, unsure)


def test_with_recompute_off_the_directory_is_kept_and_nothing_evaluated(setup: Setup) -> None:
    setup.rulebook.put_in_force(rule_in_force(REGULAR))
    done = setup.recompute(enabled=False).run(update(ENTITY), setup.store)
    assert not done.plan.evaluated
    assert done.appended == ()
    assert setup.store.decisions == {}
    assert setup.store.events == []
    assert setup.rulebook.asked == [], "the rulebook is not read"
    assert set(setup.store.directory) == {ENTITY, REGISTRATION, SECOND_REGISTRATION}


def test_a_business_the_tenant_no_longer_has_changes_nothing(setup: Setup) -> None:
    setup.rulebook.put_in_force(rule_in_force(REGULAR))
    done = setup.recompute().run(update(tenant_id=OTHER_TENANT), setup.store)
    assert not done.plan.found
    assert (done.appended, done.listed) == ((), 0)
    assert setup.store.directory == {}


def test_versions_taking_effect_within_the_lookahead_are_evaluated_too(setup: Setup) -> None:
    today_only = setup.rulebook.put_in_force(
        rule_in_force(REGULAR, rule_key="current", effective_to=TODAY + timedelta(days=30))
    )
    successor = setup.rulebook.put_in_force(
        rule_in_force(REGULAR, rule_key="current", effective_from=TODAY + timedelta(days=30))
    )
    later = setup.rulebook.put_in_force(
        rule_in_force(REGULAR, rule_key="later", effective_from=TODAY + timedelta(days=120))
    )
    within = setup.recompute(lookahead_days=92).run(update(), setup.store)
    decided = {d.rule_version_id for d in within.appended}
    assert decided == {today_only.rule_version_id, successor.rule_version_id}
    assert later.rule_version_id not in decided
    assert setup.rulebook.asked == [TODAY, TODAY + timedelta(days=92)]

    without = setup.recompute().run(update(), setup.store)
    assert {d.rule_version_id for d in without.appended} == {today_only.rule_version_id}


def test_a_free_text_decision_opens_one_review_item_and_follows_the_latest(setup: Setup) -> None:
    rule = setup.rulebook.put_in_force(rule_in_force({"all_of": [REGULAR, FREE_TEXT]}))
    recompute = setup.recompute()
    first = recompute.run(update(), setup.store)
    assert first.reviews == {ReviewChange.OPENED: 1}
    (item,) = setup.store.reviews.values()
    assert (item.reason, item.status, item.decision_id) == (
        ReviewReason.FREE_TEXT,
        ReviewStatus.OPEN,
        first.appended[0].decision_id,
    )
    assert item.opened_at == first.appended[0].decided_at

    second = recompute.run(update(), setup.store)
    assert second.reviews == {ReviewChange.FOLLOWED: 1}
    (moved,) = setup.store.reviews.values()
    assert (moved.item_id, moved.decision_id) == (item.item_id, second.appended[0].decision_id)
    assert moved.opened_at == item.opened_at

    setup.profiles.put(
        {"registration_type": "composition"}, business_id=REGISTRATION, lineage=[ENTITY]
    )
    settled = recompute.run(update(), setup.store)
    assert [d.result for d in settled.appended] == [Applicability.NOT_APPLICABLE]
    assert settled.reviews == {ReviewChange.SETTLED: 1}
    (done,) = setup.store.reviews.values()
    assert (done.status, done.resolution, done.resolved_by) == (
        ReviewStatus.RESOLVED,
        Resolution.DISMISS,
        None,
    )
    assert str(settled.appended[0].decision_id) in done.note
    assert setup.latest(REGISTRATION, rule).result is Applicability.NOT_APPLICABLE


def test_a_missing_attribute_is_unsure_without_a_review_item(setup: Setup) -> None:
    setup.rulebook.put_in_force(rule_in_force({"all_of": [REGULAR, MONTHLY]}))
    done = setup.recompute().run(update(), setup.store)
    (decision,) = done.appended
    assert (decision.result, decision.needs_review) == (Applicability.UNSURE, True)
    assert done.reviews == {}
    assert setup.store.reviews == {}
    assert len(done.published) == 1, "an unsure first decision still tells the obligations"


def test_a_free_text_leaf_the_tree_does_not_need_opens_nothing(setup: Setup) -> None:
    setup.profiles.put(
        {"registration_type": "composition"}, business_id=REGISTRATION, lineage=[ENTITY]
    )
    setup.rulebook.put_in_force(rule_in_force({"all_of": [REGULAR, FREE_TEXT]}))
    done = setup.recompute().run(update(), setup.store)
    assert [d.result for d in done.appended] == [Applicability.NOT_APPLICABLE]
    assert setup.store.reviews == {}


def test_the_lookahead_cannot_be_negative() -> None:
    with pytest.raises(ValueError, match="lookahead_days"):
        Setup().recompute(lookahead_days=-1)
    with pytest.raises(ValueError, match="superseded_lookback_days"):
        Setup().recompute(superseded_lookback_days=-1)


# ---------------------------------------------------------------- versions superseded, still due

MONTHLY_ON_THE_20TH = Recurrence.monthly(20)
APRIL = date(2026, 4, 1)
OCTOBER = date(2026, 10, 1)
LOOKBACK = 400
OBLIGATION_WINDOW = 2
"""The obligation service's window: the periods still due, through the one containing the day
and the next."""


def superseded_monthly(setup: Setup) -> tuple[RuleInForce, RuleInForce]:
    """A monthly return due on the 20th: v1 from April, superseded from 1 October by v2."""
    v1 = setup.rulebook.put_superseded(
        superseded_rule(
            REGULAR, effective_from=APRIL, effective_to=OCTOBER, recurrence=MONTHLY_ON_THE_20TH
        )
    )
    v2 = setup.rulebook.put_in_force(
        rule_in_force(REGULAR, effective_from=OCTOBER, recurrence=MONTHLY_ON_THE_20TH)
    )
    return v1, v2


def made_of(rule: RuleInForce, day: date) -> list[str]:
    """The periods the obligation service makes of a decision of ``rule`` on ``day``: those of its
    window whose last day the version is in force on (its guard refuses the others)."""
    schedule = rule.spec.schedule
    assert schedule is not None
    assert schedule.recurrence is not None
    governed = schedule.recurrence.periods_governed(schedule.effective, day, OBLIGATION_WINDOW)
    return [period.label for period in governed]


def test_a_business_new_after_a_supersession_is_decided_for_the_version_owing_september(
    setup: Setup,
) -> None:
    """Onboarded on 5 October: v2 does not govern September, v1 does, and September's return is
    due on 20 October, so v1 is decided too, and the obligation service makes September of it."""
    v1, v2 = superseded_monthly(setup)
    day = date(2026, 10, 5)
    setup.on(day)
    event = update()
    recompute = setup.recompute(superseded_lookback_days=LOOKBACK)
    done = recompute.run(event, setup.store)

    decided = {d.rule_version_id: d for d in done.appended}
    assert set(decided) == {v1.rule_version_id, v2.rule_version_id}
    old = decided[v1.rule_version_id]
    assert (old.business_id, old.result, old.trigger, old.trigger_ref) == (
        REGISTRATION,
        Applicability.APPLIES,
        Trigger.PROFILE_UPDATED,
        event.trigger_ref,
    )
    assert old.decision_id == decision_id_for(event.trigger_ref, REGISTRATION, v1.rule_version_id)
    assert set(done.published) == {decision.decision_id for decision in decided.values()}
    assert setup.rulebook.asked_superseded == [day - timedelta(days=LOOKBACK)]
    assert made_of(v1, day) == ["2026-09"], "October and November are v2's"
    assert made_of(v2, day) == ["2026-10", "2026-11"], "September is v1's"

    again = recompute.run(event, setup.store)
    assert again.appended == (), "the same event decides nothing twice"


@pytest.mark.parametrize(
    ("day", "owes_september"),
    [
        (date(2026, 10, 1), True),
        (date(2026, 10, 20), True),
        (date(2026, 10, 21), False),
        (date(2026, 10, 25), False),
    ],
)
def test_the_superseded_version_is_decided_until_its_last_return_falls_due(
    setup: Setup, day: date, owes_september: bool
) -> None:
    """Onboarded on 25 October, nothing of v1 is still due, so v1 needs no decision."""
    v1, v2 = superseded_monthly(setup)
    setup.on(day)
    done = setup.recompute(superseded_lookback_days=LOOKBACK).run(update(), setup.store)
    expected = {v2.rule_version_id} | ({v1.rule_version_id} if owes_september else set())
    assert {d.rule_version_id for d in done.appended} == expected
    assert bool(made_of(v1, day)) is owes_september


def test_an_annual_return_keeps_its_superseded_version_decided_for_months(setup: Setup) -> None:
    """Superseded from 1 April 2026, the version still governs the year 2025-26, whose annual
    return is due on 31 December 2026; a lookback shorter than that misses it."""
    annual = Recurrence.annual(31, due_month_offset=8)
    v1 = setup.rulebook.put_superseded(
        superseded_rule(
            REGULAR,
            rule_key="annual_return",
            effective_from=date(2025, 4, 1),
            effective_to=APRIL,
            recurrence=annual,
        )
    )
    v2 = setup.rulebook.put_in_force(
        rule_in_force(REGULAR, rule_key="annual_return", effective_from=APRIL, recurrence=annual)
    )
    both, newer = {v1.rule_version_id, v2.rule_version_id}, {v2.rule_version_id}

    def decided(day: date, lookback: int) -> set[object]:
        setup.on(day)
        done = setup.recompute(superseded_lookback_days=lookback).run(update(), setup.store)
        return {d.rule_version_id for d in done.appended}

    assert decided(date(2026, 10, 5), LOOKBACK) == both
    assert made_of(v1, date(2026, 10, 5)) == ["2025-26"]
    assert decided(date(2026, 12, 31), LOOKBACK) == both
    assert decided(date(2027, 1, 1), LOOKBACK) == newer
    assert decided(date(2026, 10, 5), 92) == newer, "v1 ended before the lookback"


def test_a_withdrawn_version_or_a_one_off_that_ended_is_never_decided(setup: Setup) -> None:
    """A withdrawal closes a version's obligations, so it governs nothing; a one-off belongs to
    the version in force on its due day, never one that ended."""
    setup.rulebook.put_superseded(
        rule_in_force(
            REGULAR,
            rule_key="withdrawn_return",
            effective_from=APRIL,
            effective_to=OCTOBER,
            status=RuleVersionStatus.WITHDRAWN,
            recurrence=MONTHLY_ON_THE_20TH,
        )
    )
    for rule_key, due_in_days in (("dated_one_off", 30), ("undated_one_off", None)):
        setup.rulebook.put_superseded(
            superseded_rule(
                REGULAR,
                rule_key=rule_key,
                effective_from=APRIL,
                effective_to=OCTOBER,
                recurrence=None,
                due_in_days=due_in_days,
            )
        )
    setup.on(date(2026, 10, 5))
    done = setup.recompute(superseded_lookback_days=LOOKBACK).run(update(), setup.store)
    assert done.appended == ()
    assert len(setup.rulebook.superseded) == 3, "each was listed and refused"


def test_with_the_lookback_off_no_superseded_version_is_read(setup: Setup) -> None:
    _, v2 = superseded_monthly(setup)
    setup.on(date(2026, 10, 5))
    done = setup.recompute().run(update(), setup.store)
    assert [d.rule_version_id for d in done.appended] == [v2.rule_version_id]
    assert setup.rulebook.asked_superseded == []
