"""ApplyDecision on the memory store: applies materialises once, not_applicable closes the
business's open obligations of the rule version, a decision that needs review does nothing, a
decision older than the one applied changes nothing, and the guard keeps a withdrawn, uncited or
superseded version from making what it no longer governs, whichever of the decision and the rule
event comes first."""

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import BusinessId, DecisionId, TenantId
from domain_kernel.predicates import Applicability
from domain_kernel.rules import RuleVersionSnapshot
from domain_kernel.status import ClosureReason, ObligationStatus, RuleVersionStatus
from obligation.application.changes import WithdrawRule
from obligation.application.decisions import (
    ApplyDecision,
    Decision,
    DecisionOutcome,
    DecisionPlan,
)
from obligation.domain.errors import RulebookUnavailableError, RuleVersionNotFoundError
from obligation.domain.events import ObligationClosed, ObligationCreated
from obligation.domain.rule_versions import AppliedDecision, Refusal
from obligation.infrastructure.memory import MemoryStore
from obligation.testing import FakeRuleVersionReader, ref_of, rule

DECIDED_AT = datetime(2026, 9, 30, 20, 0, tzinfo=UTC)  # 1 October in India
NOW = datetime(2026, 10, 1, 2, 0, tzinfo=UTC)


def decision(
    the_rule: RuleVersionSnapshot,
    *,
    tenant: TenantId,
    business: BusinessId,
    result: Applicability = Applicability.APPLIES,
    needs_review: bool = False,
    decided_at: datetime = DECIDED_AT,
) -> Decision:
    return Decision(
        tenant_id=tenant,
        decision_id=DecisionId.new(),
        business_id=business,
        rule_version_id=the_rule.rule_version_id,
        result=result,
        needs_review=needs_review,
        decided_at=decided_at,
    )


def test_applies_materialises_once_as_of_the_day_in_india() -> None:
    store, tenant, business, the_rule = MemoryStore(), TenantId.new(), BusinessId.new(), rule()
    reader = FakeRuleVersionReader([the_rule])
    apply = ApplyDecision(reader, clock=lambda: NOW)
    applies = decision(the_rule, tenant=tenant, business=business)

    first = apply.run(applies, store)
    assert first.outcome is DecisionOutcome.MATERIALISED
    assert len(first.created) == 3
    assert (first.refusal, first.cached) == (None, True), "the miss filled the cache"
    labels = sorted(o.period_label or "" for o in store.of_tenant(tenant))
    assert labels == ["2026-09", "2026-10", "2026-11"], (
        "September, due 20 October and so still ahead on 1 October, then the period of 1 October "
        "and the next one"
    )
    assert {o.decision_id for o in store.of_tenant(tenant)} == {applies.decision_id}
    assert store.rule_versions[the_rule.rule_version_id] == ref_of(the_rule)
    assert store.decisions[business, the_rule.rule_version_id] == AppliedDecision(
        tenant, business, the_rule.rule_version_id, applies.decision_id, True, DECIDED_AT
    )

    again = apply.run(applies, store)
    assert again.created == ()
    assert again.cached is False, "a hit"
    assert len([e for e in store.events if isinstance(e, ObligationCreated)]) == 3


def test_not_applicable_closes_only_that_business_and_rule_version() -> None:
    store, tenant, the_rule, other_rule = MemoryStore(), TenantId.new(), rule(), rule()
    business, neighbour = BusinessId.new(), BusinessId.new()
    apply = ApplyDecision(FakeRuleVersionReader([the_rule, other_rule]), clock=lambda: NOW)
    for target, rv in ((business, the_rule), (neighbour, the_rule), (business, other_rule)):
        apply.run(decision(rv, tenant=tenant, business=target), store)

    flipped = decision(
        the_rule, tenant=tenant, business=business, result=Applicability.NOT_APPLICABLE
    )
    assert apply.plan(flipped) == DecisionPlan(flipped), "nothing to read for a closure"
    closed = apply.run(flipped, store)
    assert closed.outcome is DecisionOutcome.CLOSED
    assert len(closed.closed) == 3
    for obligation in store.of_tenant(tenant):
        hit = obligation.business_id == business and obligation.rule_version_id == (
            the_rule.rule_version_id
        )
        assert obligation.is_open is not hit
        if hit:
            assert obligation.status is ObligationStatus.CLOSED_NOT_APPLICABLE
            assert obligation.closed_reason is ClosureReason.PROFILE_CHANGED
    closures = [e for e in store.events if isinstance(e, ObligationClosed)]
    assert len(closures) == 3
    assert len(store.changes) == 9 + 3, "every closure writes its change row"
    assert store.decisions[business, the_rule.rule_version_id].applies is False

    assert apply.run(flipped, store).closed == (), "a redelivery closes nothing more"
    reopened = apply.run(decision(the_rule, tenant=tenant, business=business), store)
    assert reopened.created == (), "closed periods stay closed"


@pytest.mark.parametrize(
    ("result", "needs_review"),
    [
        (Applicability.UNSURE, True),
        (Applicability.APPLIES, True),
        (Applicability.NOT_APPLICABLE, True),
        (Applicability.UNSURE, False),
    ],
)
def test_a_decision_that_needs_review_changes_nothing(
    result: Applicability, needs_review: bool
) -> None:
    store, tenant, business, the_rule = MemoryStore(), TenantId.new(), BusinessId.new(), rule()
    reader = FakeRuleVersionReader([the_rule])
    apply = ApplyDecision(reader, clock=lambda: NOW)
    apply.run(decision(the_rule, tenant=tenant, business=business), store)
    events = len(store.events)
    review = decision(
        the_rule, tenant=tenant, business=business, result=result, needs_review=needs_review
    )
    outcome = apply.run(review, store)
    assert outcome.outcome is DecisionOutcome.AWAITING_REVIEW
    assert len(store.events) == events
    assert all(o.is_open for o in store.of_tenant(tenant))
    assert reader.reads == [the_rule.rule_version_id], "a review reads nothing"


def test_a_decision_older_than_the_one_applied_changes_nothing() -> None:
    store, tenant, business, the_rule = MemoryStore(), TenantId.new(), BusinessId.new(), rule()
    apply = ApplyDecision(FakeRuleVersionReader([the_rule]), clock=lambda: NOW)
    later = decision(
        the_rule,
        tenant=tenant,
        business=business,
        result=Applicability.NOT_APPLICABLE,
        decided_at=DECIDED_AT.replace(hour=22),
    )
    assert apply.run(later, store).outcome is DecisionOutcome.CLOSED
    late = apply.run(decision(the_rule, tenant=tenant, business=business), store)
    assert late.outcome is DecisionOutcome.STALE
    assert store.obligations == {}
    assert store.decisions[business, the_rule.rule_version_id].applies is False


def test_an_unknown_rule_version_or_a_rulebook_outage_raises() -> None:
    store, tenant, business, the_rule = MemoryStore(), TenantId.new(), BusinessId.new(), rule()
    with pytest.raises(RuleVersionNotFoundError, match=str(the_rule.rule_version_id)):
        ApplyDecision(FakeRuleVersionReader()).run(
            decision(the_rule, tenant=tenant, business=business), store
        )
    with pytest.raises(RulebookUnavailableError):
        ApplyDecision(FakeRuleVersionReader([the_rule], down=True)).run(
            decision(the_rule, tenant=tenant, business=business), store
        )
    with pytest.raises(InvariantViolationError, match="with its rule version"):
        ApplyDecision(FakeRuleVersionReader()).apply(
            DecisionPlan(decision(the_rule, tenant=tenant, business=business)), store
        )
    assert store.obligations == {}


def test_a_decision_needs_an_aware_time() -> None:
    with pytest.raises(InvariantViolationError, match="decided_at"):
        Decision(
            tenant_id=TenantId.new(),
            decision_id=DecisionId.new(),
            business_id=BusinessId.new(),
            rule_version_id=rule().rule_version_id,
            result=Applicability.APPLIES,
            needs_review=False,
            decided_at=datetime(2026, 10, 1),
        )


# ---------------------------------------------------------------- the guard, both orders


def test_a_decision_before_the_withdrawal_is_closed_by_it() -> None:
    store, tenant, business, the_rule = MemoryStore(), TenantId.new(), BusinessId.new(), rule()
    reader = FakeRuleVersionReader([the_rule])
    applied = ApplyDecision(reader, clock=lambda: NOW).run(
        decision(the_rule, tenant=tenant, business=business), store
    )
    assert len(applied.created) == 3
    reader.end(the_rule.rule_version_id, RuleVersionStatus.WITHDRAWN)
    closed = WithdrawRule(store, clock=lambda: NOW).run(tenant, the_rule.rule_version_id)
    assert set(closed.changed) == set(applied.created)
    assert {o.closed_reason for o in store.of_tenant(tenant)} == {ClosureReason.RULE_WITHDRAWN}


def test_a_decision_after_the_withdrawal_makes_nothing() -> None:
    """The decision is planned while the reader still has the version as published (a batch in
    flight, or a read kept from a minute ago); the cache already says withdrawn."""
    store, tenant, business, the_rule = MemoryStore(), TenantId.new(), BusinessId.new(), rule()
    apply = ApplyDecision(FakeRuleVersionReader([the_rule]), clock=lambda: NOW)
    late = apply.plan(decision(the_rule, tenant=tenant, business=business))
    assert late.read is not None
    assert late.read.ref.status is RuleVersionStatus.PUBLISHED
    store.rule_versions[the_rule.rule_version_id] = ref_of(
        the_rule, status=RuleVersionStatus.WITHDRAWN, fetched_at=NOW
    )

    refused = apply.apply(late, store)
    assert refused.outcome is DecisionOutcome.REFUSED
    assert refused.refusal is Refusal.RULE_WITHDRAWN
    assert refused.ref is not None
    assert refused.ref.status is RuleVersionStatus.WITHDRAWN, "the cache's view wins"
    assert store.obligations == {}
    assert store.rule_versions[the_rule.rule_version_id].status is RuleVersionStatus.WITHDRAWN


def test_the_rulebook_saying_withdrawn_is_enough_on_a_miss() -> None:
    store, tenant, business, the_rule = MemoryStore(), TenantId.new(), BusinessId.new(), rule()
    reader = FakeRuleVersionReader([the_rule])
    reader.end(the_rule.rule_version_id, RuleVersionStatus.WITHDRAWN)
    refused = ApplyDecision(reader, clock=lambda: NOW).run(
        decision(the_rule, tenant=tenant, business=business), store
    )
    assert (refused.outcome, refused.refusal, refused.cached) == (
        DecisionOutcome.REFUSED,
        Refusal.RULE_WITHDRAWN,
        True,
    )
    assert store.rule_versions[the_rule.rule_version_id].status is RuleVersionStatus.WITHDRAWN


def test_a_version_without_a_verified_citation_makes_nothing() -> None:
    store, tenant, business, the_rule = MemoryStore(), TenantId.new(), BusinessId.new(), rule()
    reader = FakeRuleVersionReader([the_rule], refs=[ref_of(the_rule, citations=())])
    refused = ApplyDecision(reader, clock=lambda: NOW).run(
        decision(the_rule, tenant=tenant, business=business), store
    )
    assert (refused.outcome, refused.refusal) == (DecisionOutcome.REFUSED, Refusal.UNCITED)
    assert store.obligations == {}
    assert store.rule_versions[the_rule.rule_version_id].citations == ()


def test_a_superseded_version_makes_only_the_periods_before_its_replacement() -> None:
    """Superseded from 1 November: September (still due on 1 October) and October are still its
    own, November is the newer version's."""
    store, tenant, business, the_rule = MemoryStore(), TenantId.new(), BusinessId.new(), rule()
    reader = FakeRuleVersionReader([the_rule])
    plan = ApplyDecision(reader, clock=lambda: NOW).plan(
        decision(the_rule, tenant=tenant, business=business)
    )
    store.rule_versions[the_rule.rule_version_id] = ref_of(
        the_rule,
        status=RuleVersionStatus.SUPERSEDED,
        effective_to=date(2026, 11, 1),
        fetched_at=NOW,
    )
    applied = ApplyDecision(reader, clock=lambda: NOW).apply(plan, store)
    assert applied.outcome is DecisionOutcome.MATERIALISED
    assert (applied.refusal, applied.refused_periods) == (Refusal.RULE_SUPERSEDED, ("2026-11",))
    assert [o.period_label for o in store.of_tenant(tenant)] == ["2026-09", "2026-10"]


def test_a_one_off_due_after_the_replacement_is_refused() -> None:
    one_off = rule(recurrence=None, due_in_days=45)
    store, tenant, business = MemoryStore(), TenantId.new(), BusinessId.new()
    cut = ref_of(one_off, effective_to=date(2026, 11, 1))
    reader = FakeRuleVersionReader([one_off], refs=[cut])
    applied = ApplyDecision(reader, clock=lambda: NOW).run(
        decision(one_off, tenant=tenant, business=business), store
    )
    assert applied.refused_periods == ("one-off due 2026-11-15",)
    assert store.obligations == {}

    early = replace(cut, effective_to=date(2026, 11, 16))
    reader.refs[one_off.rule_version_id] = replace(early, fetched_at=NOW.replace(hour=3))
    store.rule_versions.clear()
    made = ApplyDecision(reader, clock=lambda: NOW).run(
        decision(one_off, tenant=tenant, business=business), store
    )
    assert len(made.created) == 1, "due the day before the replacement takes over"
