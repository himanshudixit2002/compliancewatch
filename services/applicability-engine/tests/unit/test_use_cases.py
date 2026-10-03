"""EvaluateRule and the queries on the memory store, with the profile service and the rulebook
faked in memory."""

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any

import pytest

import ontology as ontology_package
from applicability_engine.application.evaluate import EvaluateRequest, EvaluateRule
from applicability_engine.application.queries import DecisionQuery, ListDecisions, ReadDecision
from applicability_engine.domain.errors import (
    BusinessNotFoundError,
    DecisionNotFoundError,
    RuleVersionNotFoundError,
    RuleVersionNotPublishedError,
)
from applicability_engine.domain.events import ApplicabilityDecided
from applicability_engine.domain.model import DecisionKey, Trigger
from applicability_engine.infrastructure.memory import MemoryStore
from applicability_engine.testing import (
    BUSINESS,
    FY,
    NOW,
    OTHER_TENANT,
    TENANT,
    MemoryProfiles,
    MemoryRulebook,
    rule_version,
)
from domain_kernel.confidence import CERTAIN, ZERO
from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import BusinessId, DecisionId, RuleVersionId
from domain_kernel.predicates import Applicability
from domain_kernel.status import RuleVersionStatus

REGULAR = {"attribute": "registration_type", "operator": "eq", "value": "regular"}
FREE_TEXT = {"attribute": "business_category", "free_text": "Runs a restaurant in a hotel"}


@dataclass
class Ticking:
    """A clock one minute later on every call, so decisions have distinct times."""

    ticks: int = 0

    def __call__(self) -> datetime:
        self.ticks += 1
        return NOW + timedelta(minutes=self.ticks)


@dataclass
class Engine:
    store: MemoryStore = field(default_factory=MemoryStore)
    profiles: MemoryProfiles = field(default_factory=MemoryProfiles)
    rulebook: MemoryRulebook = field(default_factory=MemoryRulebook)
    clock: Ticking = field(default_factory=Ticking)

    def evaluator(self) -> EvaluateRule:
        return EvaluateRule(
            self.store, self.profiles, self.rulebook, ontology_package.load(), clock=self.clock
        )

    def request(self, rule_version_id: RuleVersionId, **changes: Any) -> EvaluateRequest:
        return replace(EvaluateRequest(TENANT, BUSINESS, rule_version_id), **changes)


@pytest.fixture
def engine() -> Engine:
    engine = Engine()
    engine.profiles.put({"registration_type": "regular"}, version=3)
    return engine


def test_a_decision_is_stored_with_its_event(engine: Engine) -> None:
    rule = engine.rulebook.put(rule_version(REGULAR))
    decision = engine.evaluator().run(engine.request(rule.rule_version_id))

    assert decision.result is Applicability.APPLIES
    assert decision.confidence == CERTAIN
    assert not decision.needs_review
    assert (decision.profile_version, decision.as_of_fy, decision.trigger) == (
        3,
        FY,
        Trigger.MANUAL,
    )
    assert [item.outcome for item in decision.evaluated] == [Applicability.APPLIES]
    assert engine.store.decisions == {decision.decision_id: decision}
    [event] = engine.store.events
    assert isinstance(event, ApplicabilityDecided)
    assert event.tenant_id == TENANT
    assert (event.decision_id, event.business_id, event.rule_version_id) == (
        decision.decision_id,
        BUSINESS,
        rule.rule_version_id,
    )
    assert (event.result, event.confidence, event.needs_review) == (
        Applicability.APPLIES,
        1.0,
        False,
    )
    assert (event.profile_version, event.decided_at, event.trigger) == (
        3,
        decision.decided_at,
        Trigger.MANUAL,
    )


def test_an_unsure_decision_needs_review(engine: Engine) -> None:
    rule = engine.rulebook.put(rule_version({"all_of": [REGULAR, FREE_TEXT]}))
    decision = engine.evaluator().run(engine.request(rule.rule_version_id))
    assert (decision.result, decision.confidence) == (Applicability.UNSURE, ZERO)
    assert decision.needs_review
    [event] = engine.store.events
    assert isinstance(event, ApplicabilityDecided)
    assert (event.result, event.confidence, event.needs_review) == (Applicability.UNSURE, 0, True)


def test_the_profile_is_read_for_the_current_financial_year_in_india(engine: Engine) -> None:
    rule = engine.rulebook.put(rule_version(REGULAR))
    evaluate = engine.evaluator()
    evaluate.run(engine.request(rule.rule_version_id))
    evaluate.run(engine.request(rule.rule_version_id, fy=FinancialYear(2025)))
    assert engine.profiles.asked == [FinancialYear(2026), FinancialYear(2025)]


def test_an_unknown_rule_version_stores_nothing(engine: Engine) -> None:
    with pytest.raises(RuleVersionNotFoundError):
        engine.evaluator().run(engine.request(RuleVersionId.new()))
    assert (engine.store.decisions, engine.store.events) == ({}, [])


@pytest.mark.parametrize(
    "status", [status for status in RuleVersionStatus if status is not RuleVersionStatus.PUBLISHED]
)
def test_only_a_published_rule_version_is_evaluated(
    engine: Engine, status: RuleVersionStatus
) -> None:
    rule = engine.rulebook.put(rule_version(REGULAR, status=status))
    with pytest.raises(RuleVersionNotPublishedError):
        engine.evaluator().run(engine.request(rule.rule_version_id))
    assert engine.profiles.asked == []
    assert engine.store.decisions == {}


def test_an_unknown_business_stores_nothing(engine: Engine) -> None:
    rule = engine.rulebook.put(rule_version(REGULAR))
    with pytest.raises(BusinessNotFoundError):
        engine.evaluator().run(engine.request(rule.rule_version_id, business_id=BusinessId.new()))
    assert (engine.store.decisions, engine.store.events) == ({}, [])


def test_recomputing_appends_and_the_listing_is_newest_first(engine: Engine) -> None:
    gst = engine.rulebook.put(rule_version(REGULAR))
    other = engine.rulebook.put(rule_version(FREE_TEXT))
    evaluate = engine.evaluator()
    first = evaluate.run(engine.request(gst.rule_version_id))
    unrelated = evaluate.run(engine.request(other.rule_version_id))
    engine.profiles.put({"registration_type": "composition"}, version=4)
    second = evaluate.run(engine.request(gst.rule_version_id, trigger=Trigger.PROFILE_UPDATED))
    assert second.result is Applicability.NOT_APPLICABLE
    assert len(engine.store.events) == 3

    listing = ListDecisions(engine.store)
    every = listing.run(DecisionQuery(TENANT, BUSINESS, limit=10))
    assert [d.decision_id for d in every] == [
        second.decision_id,
        unrelated.decision_id,
        first.decision_id,
    ]
    of_gst = listing.run(
        DecisionQuery(TENANT, BUSINESS, limit=10, rule_version_id=gst.rule_version_id)
    )
    assert [d.decision_id for d in of_gst] == [second.decision_id, first.decision_id]
    after = listing.run(DecisionQuery(TENANT, BUSINESS, limit=10, after=DecisionKey.of(second)))
    assert [d.decision_id for d in after] == [unrelated.decision_id, first.decision_id]
    assert listing.run(DecisionQuery(OTHER_TENANT, BUSINESS, limit=10)) == ()


def test_reading_one_decision_is_scoped_to_its_tenant(engine: Engine) -> None:
    rule = engine.rulebook.put(rule_version(REGULAR))
    decision = engine.evaluator().run(engine.request(rule.rule_version_id))
    read = ReadDecision(engine.store)
    assert read.run(TENANT, decision.decision_id) == decision
    with pytest.raises(DecisionNotFoundError):
        read.run(OTHER_TENANT, decision.decision_id)
    with pytest.raises(DecisionNotFoundError):
        read.run(TENANT, DecisionId.new())


def test_a_failed_unit_of_work_keeps_neither_the_decision_nor_the_event(engine: Engine) -> None:
    rule = engine.rulebook.put(rule_version(REGULAR))
    decision = engine.evaluator().run(engine.request(rule.rule_version_id))

    def write_then_fail() -> None:
        with engine.store(TENANT) as uow:
            uow.decisions.add(replace(decision, decision_id=DecisionId.new()))
            uow.events.publish(ApplicabilityDecided.of(decision))
            raise RuntimeError("the transaction fails")

    with pytest.raises(RuntimeError):
        write_then_fail()
    assert list(engine.store.decisions) == [decision.decision_id]
    assert len(engine.store.events) == 1
