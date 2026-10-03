"""ApplyDecision on the memory store: applies materialises once, not_applicable closes the
business's open obligations of the rule version, and a decision that needs review does nothing."""

from datetime import UTC, datetime

import pytest

from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import BusinessId, DecisionId, TenantId
from domain_kernel.predicates import Applicability
from domain_kernel.rules import RuleVersionSnapshot
from domain_kernel.status import ClosureReason, ObligationStatus
from obligation.application.decisions import ApplyDecision, Decision, DecisionOutcome
from obligation.domain.errors import RulebookUnavailableError, RuleVersionNotFoundError
from obligation.domain.events import ObligationClosed, ObligationCreated
from obligation.infrastructure.memory import MemoryStore
from obligation.testing import FakeRuleVersionReader, rule

DECIDED_AT = datetime(2026, 9, 30, 20, 0, tzinfo=UTC)  # 1 October in India
NOW = datetime(2026, 10, 1, 2, 0, tzinfo=UTC)


def decision(
    the_rule: RuleVersionSnapshot,
    *,
    tenant: TenantId,
    business: BusinessId,
    result: Applicability = Applicability.APPLIES,
    needs_review: bool = False,
) -> Decision:
    return Decision(
        tenant_id=tenant,
        decision_id=DecisionId.new(),
        business_id=business,
        rule_version_id=the_rule.rule_version_id,
        result=result,
        needs_review=needs_review,
        decided_at=DECIDED_AT,
    )


def test_applies_materialises_once_as_of_the_day_in_india() -> None:
    store, tenant, business, the_rule = MemoryStore(), TenantId.new(), BusinessId.new(), rule()
    reader = FakeRuleVersionReader([the_rule])
    apply = ApplyDecision(store, reader, clock=lambda: NOW)
    applies = decision(the_rule, tenant=tenant, business=business)

    first = apply.run(applies)
    assert first.outcome is DecisionOutcome.MATERIALISED
    assert len(first.created) == 2
    labels = sorted(o.period_label or "" for o in store.of_tenant(tenant))
    assert labels == ["2026-10", "2026-11"], "the period of 1 October and the next one"
    assert {o.decision_id for o in store.of_tenant(tenant)} == {applies.decision_id}

    again = apply.run(applies)
    assert again.created == ()
    assert len([e for e in store.events if isinstance(e, ObligationCreated)]) == 2


def test_not_applicable_closes_only_that_business_and_rule_version() -> None:
    store, tenant, the_rule, other_rule = MemoryStore(), TenantId.new(), rule(), rule()
    business, neighbour = BusinessId.new(), BusinessId.new()
    apply = ApplyDecision(store, FakeRuleVersionReader([the_rule, other_rule]), clock=lambda: NOW)
    for target, rv in ((business, the_rule), (neighbour, the_rule), (business, other_rule)):
        apply.run(decision(rv, tenant=tenant, business=target))

    flipped = decision(
        the_rule, tenant=tenant, business=business, result=Applicability.NOT_APPLICABLE
    )
    closed = apply.run(flipped)
    assert closed.outcome is DecisionOutcome.CLOSED
    assert len(closed.closed) == 2
    for obligation in store.of_tenant(tenant):
        hit = obligation.business_id == business and obligation.rule_version_id == (
            the_rule.rule_version_id
        )
        assert obligation.is_open is not hit
        if hit:
            assert obligation.status is ObligationStatus.CLOSED_NOT_APPLICABLE
            assert obligation.closed_reason is ClosureReason.PROFILE_CHANGED
    closures = [e for e in store.events if isinstance(e, ObligationClosed)]
    assert len(closures) == 2
    assert len(store.changes) == 6 + 2, "every closure writes its change row"

    assert apply.run(flipped).closed == (), "a redelivery closes nothing more"
    reopened = apply.run(decision(the_rule, tenant=tenant, business=business))
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
    apply = ApplyDecision(store, reader, clock=lambda: NOW)
    apply.run(decision(the_rule, tenant=tenant, business=business))
    events = len(store.events)
    outcome = apply.run(
        decision(
            the_rule, tenant=tenant, business=business, result=result, needs_review=needs_review
        )
    )
    assert outcome.outcome is DecisionOutcome.AWAITING_REVIEW
    assert len(store.events) == events
    assert all(o.is_open for o in store.of_tenant(tenant))


def test_an_unknown_rule_version_or_a_rulebook_outage_raises() -> None:
    store, tenant, business, the_rule = MemoryStore(), TenantId.new(), BusinessId.new(), rule()
    with pytest.raises(RuleVersionNotFoundError, match=str(the_rule.rule_version_id)):
        ApplyDecision(store, FakeRuleVersionReader()).run(
            decision(the_rule, tenant=tenant, business=business)
        )
    with pytest.raises(RulebookUnavailableError):
        ApplyDecision(store, FakeRuleVersionReader([the_rule], down=True)).run(
            decision(the_rule, tenant=tenant, business=business)
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
