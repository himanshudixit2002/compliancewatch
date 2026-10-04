"""The review queue on the memory store: which decisions need a person, an item's life, and the
use cases that list and settle items."""

from dataclasses import replace
from datetime import timedelta

import pytest

import ontology as ontology_package
from applicability_engine.application.evaluate import EvaluateRequest, EvaluateRule
from applicability_engine.application.review import (
    ListReviewItems,
    ResolveRequest,
    ResolveReviewItem,
    ReviewQuery,
    review_trigger_ref,
)
from applicability_engine.domain.errors import ReviewItemNotFoundError, ReviewItemResolvedError
from applicability_engine.domain.events import ApplicabilityDecided
from applicability_engine.domain.model import Decision, Trigger, decision_id_for
from applicability_engine.domain.review import (
    Resolution,
    ReviewItem,
    ReviewItemId,
    ReviewItemKey,
    ReviewReason,
    ReviewStatus,
    review_item_id_for,
    review_reason,
)
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
from domain_kernel.confidence import CERTAIN, ZERO, Confidence
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import BusinessId, DecisionId, RuleVersionId, UserId
from domain_kernel.operators import Operator
from domain_kernel.predicates import Applicability, Predicate, PredicateResult

REGULAR = {"attribute": "registration_type", "operator": "eq", "value": "regular"}
FREE_TEXT = {"attribute": "business_category", "free_text": "Example premises shared with a hotel"}
REVIEWER = UserId.new()
FREE = Predicate("business_category", free_text="Example premises shared with a hotel")
STRUCTURED = Predicate("registration_type", Operator.EQ, "regular")


def decision(
    *evaluated: PredicateResult,
    result: Applicability = Applicability.UNSURE,
    confidence: Confidence = ZERO,
    business_id: BusinessId = BUSINESS,
    rule_version_id: RuleVersionId | None = None,
    minutes: int = 0,
) -> Decision:
    return Decision(
        decision_id=DecisionId.new(),
        tenant_id=TENANT,
        business_id=business_id,
        rule_version_id=rule_version_id or RuleVersionId(BUSINESS.value),
        result=result,
        confidence=confidence,
        evaluated=evaluated,
        profile_version=2,
        decided_at=NOW + timedelta(minutes=minutes),
        trigger=Trigger.PROFILE_UPDATED,
        as_of_fy=FY,
    )


def free_text_unsure() -> PredicateResult:
    return PredicateResult(FREE, Applicability.UNSURE, ZERO, "needs judgement")


def missing() -> PredicateResult:
    return PredicateResult(STRUCTURED, Applicability.UNSURE, ZERO, "not set")


def test_free_text_left_unsure_needs_a_reviewer() -> None:
    assert review_reason(decision(missing(), free_text_unsure())) is ReviewReason.FREE_TEXT


def test_a_judgement_below_the_threshold_needs_a_reviewer() -> None:
    judged = PredicateResult(FREE, Applicability.APPLIES, Confidence(0.55), "judged")
    low = decision(judged, result=Applicability.APPLIES, confidence=Confidence(0.55))
    assert review_reason(low) is ReviewReason.LOW_CONFIDENCE
    certain_leaf = PredicateResult(STRUCTURED, Applicability.APPLIES, CERTAIN, "holds")
    unsure_overall = decision(
        certain_leaf, result=Applicability.APPLIES, confidence=Confidence(0.5)
    )
    assert review_reason(unsure_overall) is ReviewReason.LOW_CONFIDENCE


def test_a_missing_attribute_or_a_certain_decision_needs_none() -> None:
    assert review_reason(decision(missing())) is None
    certain = PredicateResult(STRUCTURED, Applicability.APPLIES, CERTAIN, "holds")
    assert (
        review_reason(decision(certain, result=Applicability.APPLIES, confidence=CERTAIN)) is None
    )


def test_an_item_opens_follows_and_is_settled_within_its_pair() -> None:
    first = decision(free_text_unsure())
    item = ReviewItem.open(first, ReviewReason.FREE_TEXT)
    assert item.item_id == review_item_id_for(first.decision_id)
    assert (item.status, item.opened_at, item.is_open) == (
        ReviewStatus.OPEN,
        first.decided_at,
        True,
    )

    later = decision(free_text_unsure(), rule_version_id=first.rule_version_id, minutes=5)
    moved = item.follow(later, ReviewReason.FREE_TEXT)
    assert (moved.decision_id, moved.opened_at) == (later.decision_id, first.decided_at)

    other_pair = decision(free_text_unsure(), business_id=BusinessId.new())
    with pytest.raises(InvariantViolationError, match="another business"):
        item.follow(other_pair, ReviewReason.FREE_TEXT)

    certain = replace(later, decision_id=DecisionId.new(), result=Applicability.APPLIES)
    settled = moved.settled_by(certain, at=NOW)
    assert (settled.resolution, settled.resolved_by, settled.resolution_decision_id) == (
        Resolution.DISMISS,
        None,
        None,
    )
    with pytest.raises(InvariantViolationError, match="already resolved"):
        settled.follow(later, ReviewReason.FREE_TEXT)
    with pytest.raises(InvariantViolationError, match="already resolved"):
        settled.resolve(Resolution.DISMISS, by=REVIEWER, at=NOW, note="again", decision_id=None)


def test_a_resolution_to_a_result_names_its_decision_and_its_person() -> None:
    item = ReviewItem.open(decision(free_text_unsure()), ReviewReason.FREE_TEXT)
    with pytest.raises(InvariantViolationError, match="names the decision"):
        item.resolve(Resolution.APPLIES, by=REVIEWER, at=NOW, note="ok", decision_id=None)
    with pytest.raises(InvariantViolationError, match="names the decision"):
        item.resolve(
            Resolution.DISMISS, by=REVIEWER, at=NOW, note="ok", decision_id=DecisionId.new()
        )
    with pytest.raises(InvariantViolationError, match="only a person"):
        replace(
            item,
            status=ReviewStatus.RESOLVED,
            resolution=Resolution.APPLIES,
            resolved_at=NOW,
            resolution_decision_id=DecisionId.new(),
        )
    with pytest.raises(InvariantViolationError, match="no resolution yet"):
        replace(item, note="early")
    with pytest.raises(InvariantViolationError, match="at most"):
        item.resolve(Resolution.DISMISS, by=REVIEWER, at=NOW, note="x" * 2001, decision_id=None)
    assert Resolution.APPLIES.result is Applicability.APPLIES
    assert Resolution.DISMISS.result is None


class Queue:
    """A store with one item opened by a manual evaluation of a free-text rule."""

    def __init__(self) -> None:
        self.store = MemoryStore()
        self.profiles = MemoryProfiles()
        self.rulebook = MemoryRulebook()
        self.profiles.put({"registration_type": "regular"}, version=4)
        self.rule = self.rulebook.put(rule_version({"all_of": [REGULAR, FREE_TEXT]}))
        self.evaluate = EvaluateRule(
            self.store, self.profiles, self.rulebook, ontology_package.load(), clock=lambda: NOW
        )
        self.decision = self.evaluate.run(
            EvaluateRequest(TENANT, BUSINESS, self.rule.rule_version_id)
        )
        (self.item,) = self.store.reviews.values()
        self.resolve = ResolveReviewItem(self.store, clock=lambda: NOW + timedelta(hours=1))

    def request(self, resolution: Resolution, **changes: object) -> ResolveRequest:
        values: dict[str, object] = {
            "tenant_id": TENANT,
            "item_id": self.item.item_id,
            "resolution": resolution,
            "resolved_by": REVIEWER,
            "note": "Example premises checked against the clause",
        }
        values.update(changes)
        return ResolveRequest(**values)  # type: ignore[arg-type]


def test_a_manual_evaluation_keeps_the_queue_in_step() -> None:
    queue = Queue()
    assert (queue.item.decision_id, queue.item.reason) == (
        queue.decision.decision_id,
        ReviewReason.FREE_TEXT,
    )


@pytest.mark.parametrize("resolution", [Resolution.APPLIES, Resolution.NOT_APPLICABLE])
def test_resolving_to_a_result_appends_a_review_decision_and_its_event(
    resolution: Resolution,
) -> None:
    queue = Queue()
    entry = queue.resolve.run(queue.request(resolution))

    resolved = entry.item
    assert (resolved.status, resolved.resolution, resolved.resolved_by) == (
        ReviewStatus.RESOLVED,
        resolution,
        REVIEWER,
    )
    assert resolved.resolved_at == NOW + timedelta(hours=1)
    assert entry.decision == queue.decision, "the response shows the decision reviewed"
    reference = review_trigger_ref(queue.item.item_id)
    expected_id = decision_id_for(reference, BUSINESS, queue.rule.rule_version_id)
    assert resolved.resolution_decision_id == expected_id
    appended = queue.store.decisions[expected_id]
    assert (appended.result.value, appended.confidence, appended.trigger) == (
        resolution.value,
        CERTAIN,
        Trigger.REVIEW,
    )
    assert (appended.trigger_ref, appended.profile_version, appended.as_of_fy) == (
        reference,
        4,
        queue.decision.as_of_fy,
    )
    assert appended.evaluated == queue.decision.evaluated
    assert not appended.needs_review
    review_events = [
        e
        for e in queue.store.events
        if isinstance(e, ApplicabilityDecided) and e.trigger is Trigger.REVIEW
    ]
    assert [e.decision_id for e in review_events] == [expected_id]

    with pytest.raises(ReviewItemResolvedError):
        queue.resolve.run(queue.request(resolution))


def test_dismissing_appends_nothing() -> None:
    queue = Queue()
    decisions, events = dict(queue.store.decisions), list(queue.store.events)
    entry = queue.resolve.run(
        queue.request(Resolution.DISMISS, note="Not a question for this rule")
    )
    assert (entry.item.resolution, entry.item.resolution_decision_id) == (Resolution.DISMISS, None)
    assert entry.item.note == "Not a question for this rule"
    assert queue.store.decisions == decisions
    assert queue.store.events == events


def test_another_tenant_cannot_see_or_settle_the_item() -> None:
    queue = Queue()
    with pytest.raises(ReviewItemNotFoundError):
        queue.resolve.run(queue.request(Resolution.APPLIES, tenant_id=OTHER_TENANT))
    with pytest.raises(ReviewItemNotFoundError):
        queue.resolve.run(queue.request(Resolution.APPLIES, item_id=ReviewItemId.new()))
    assert ListReviewItems(queue.store).run(ReviewQuery(OTHER_TENANT, limit=10)) == ()


def test_the_listing_pages_oldest_first_with_a_status_filter() -> None:
    queue = Queue()
    later_rule = queue.rulebook.put(rule_version({"all_of": [REGULAR, FREE_TEXT]}))
    evaluate = EvaluateRule(
        queue.store,
        queue.profiles,
        queue.rulebook,
        ontology_package.load(),
        clock=lambda: NOW + timedelta(minutes=10),
    )
    evaluate.run(EvaluateRequest(TENANT, BUSINESS, later_rule.rule_version_id))
    listing = ListReviewItems(queue.store)

    everything = listing.run(ReviewQuery(TENANT, limit=10))
    assert [entry.item.rule_version_id for entry in everything] == [
        queue.rule.rule_version_id,
        later_rule.rule_version_id,
    ]
    assert everything[0].decision == queue.decision
    after_first = listing.run(
        ReviewQuery(TENANT, limit=10, after=ReviewItemKey.of(everything[0].item))
    )
    assert [entry.item.item_id for entry in after_first] == [everything[1].item.item_id]

    queue.resolve.run(queue.request(Resolution.DISMISS))
    open_items = listing.run(ReviewQuery(TENANT, limit=10, status=ReviewStatus.OPEN))
    resolved = listing.run(ReviewQuery(TENANT, limit=10, status=ReviewStatus.RESOLVED))
    assert [entry.item.rule_version_id for entry in open_items] == [later_rule.rule_version_id]
    assert [entry.item.item_id for entry in resolved] == [queue.item.item_id]


def test_the_memory_store_keeps_one_open_item_per_pair_and_refuses_another_tenant() -> None:
    queue = Queue()
    duplicate = ReviewItem.open(
        replace(queue.decision, decision_id=DecisionId.new()), ReviewReason.FREE_TEXT
    )
    with queue.store(TENANT) as uow:
        assert not uow.reviews.add(duplicate)
        assert not uow.reviews.add(queue.item), "the same id"
    with queue.store(OTHER_TENANT) as uow, pytest.raises(ValueError, match="another tenant"):
        uow.reviews.add(duplicate)
