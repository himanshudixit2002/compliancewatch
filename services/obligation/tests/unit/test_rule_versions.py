"""The cached facts of a rule version and the guard's rules: a merge never moves a version back,
a version governs the periods whose last day it is in force on, a one-off belongs to the version
in force on its due day, and a newer version takes over what falls on or after its first day."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import BusinessId, DecisionId, ObligationId, RuleVersionId, TenantId
from domain_kernel.recurrence import Period, Recurrence
from domain_kernel.status import ObligationStatus, RuleVersionStatus
from obligation.application.materialise import IST
from obligation.domain.model import Obligation, due_at_end_of_day
from obligation.domain.rule_versions import (
    AppliedDecision,
    Refusal,
    RuleVersionRead,
    holds_due,
    holds_period,
    refusal,
    taken_over,
)
from obligation.testing import BUSINESS, DECISION, NOW, TENANT, ref_of, rule

OCTOBER = Recurrence.monthly(20).period_containing(date(2026, 10, 1))
NOVEMBER = Recurrence.monthly(20).period_containing(date(2026, 11, 1))


def test_a_merge_keeps_the_further_lifecycle_and_the_later_facts() -> None:
    the_rule = rule()
    published = ref_of(the_rule, title="Old title", fetched_at=NOW)
    withdrawn = ref_of(the_rule, status=RuleVersionStatus.WITHDRAWN, fetched_at=NOW)
    later = ref_of(the_rule, title="New title", fetched_at=NOW + timedelta(minutes=5))

    merged = withdrawn.merge(later)
    assert (merged.status, merged.title) == (RuleVersionStatus.WITHDRAWN, "New title")
    assert merged.fetched_at == later.fetched_at
    assert published.merge(withdrawn).status is RuleVersionStatus.WITHDRAWN, "a tie takes the other"

    cut = ref_of(the_rule, effective_to=date(2026, 11, 1), fetched_at=NOW)
    uncut = ref_of(the_rule, fetched_at=NOW + timedelta(hours=1))
    assert cut.merge(uncut).effective_to == date(2026, 11, 1), "an end only moves earlier"
    assert uncut.merge(cut).effective_to == date(2026, 11, 1)
    with pytest.raises(InvariantViolationError, match="cannot merge"):
        cut.merge(ref_of(rule()))


def test_ending_ranks_withdrawn_above_superseded() -> None:
    ref = ref_of(rule())
    superseded = ref.ended(RuleVersionStatus.SUPERSEDED, date(2026, 11, 1))
    assert (superseded.status, superseded.effective_to) == (
        RuleVersionStatus.SUPERSEDED,
        date(2026, 11, 1),
    )
    assert superseded.ended(RuleVersionStatus.PUBLISHED, None) is superseded
    withdrawn = superseded.ended(RuleVersionStatus.WITHDRAWN, date(2026, 12, 1))
    assert (withdrawn.status, withdrawn.effective_to) == (
        RuleVersionStatus.WITHDRAWN,
        date(2026, 11, 1),
    )
    assert withdrawn.ended(RuleVersionStatus.SUPERSEDED, None).status is (
        RuleVersionStatus.WITHDRAWN
    )
    with pytest.raises(InvariantViolationError):
        ref.ended(RuleVersionStatus.SUPERSEDED, ref.effective_from)


def test_the_guard_refuses_a_withdrawn_or_uncited_version() -> None:
    ref = ref_of(rule())
    assert refusal(ref) is None
    assert refusal(replace(ref, status=RuleVersionStatus.WITHDRAWN)) is Refusal.RULE_WITHDRAWN
    assert refusal(replace(ref, citations=())) is Refusal.UNCITED
    superseded = ref.ended(RuleVersionStatus.SUPERSEDED, date(2026, 11, 1))
    assert refusal(superseded) is None, "a superseded version still makes its earlier periods"


def test_a_version_governs_the_periods_whose_last_day_it_is_in_force_on() -> None:
    ref = ref_of(rule())
    assert holds_period(ref, NOVEMBER), "no end"
    cut = ref.ended(RuleVersionStatus.SUPERSEDED, date(2026, 11, 1))
    assert holds_period(cut, OCTOBER)
    assert not holds_period(cut, NOVEMBER)
    mid = ref.ended(RuleVersionStatus.SUPERSEDED, date(2026, 10, 15))
    assert not holds_period(mid, OCTOBER), "October's last day belongs to the newer version"


def test_a_one_off_belongs_to_the_version_in_force_on_its_due_day() -> None:
    ref = ref_of(rule(recurrence=None, due_in_days=30))
    cut = ref.ended(RuleVersionStatus.PUBLISHED, date(2026, 11, 1))
    assert holds_due(cut, date(2026, 10, 31))
    assert not holds_due(cut, date(2026, 11, 1))
    assert holds_due(ref, date(2030, 1, 1))
    assert holds_due(cut, None), "undated, while it is still published"
    assert not holds_due(cut.ended(RuleVersionStatus.SUPERSEDED, None), None)


def obligation(period: Period | None, due_on: date | None) -> Obligation:
    return Obligation(
        id=ObligationId.new(),
        tenant_id=TENANT,
        business_id=BUSINESS,
        rule_version_id=RuleVersionId.new(),
        decision_id=DECISION,
        title="File GSTR-3B",
        steps=(),
        evidence_type="",
        period=period,
        due_at=None if due_on is None else due_at_end_of_day(due_on, IST),
        status=ObligationStatus.OPEN,
        created_at=NOW,
        updated_at=NOW,
    )


def test_a_newer_version_takes_over_what_falls_on_or_after_its_first_day() -> None:
    first = date(2026, 11, 1)
    assert not taken_over(obligation(OCTOBER, date(2026, 11, 20)), first, IST)
    assert taken_over(obligation(NOVEMBER, date(2026, 12, 20)), first, IST)
    assert taken_over(obligation(OCTOBER, None), date(2026, 10, 15), IST), "October ends after"
    assert taken_over(obligation(None, first), first, IST)
    assert not taken_over(obligation(None, date(2026, 10, 31)), first, IST)
    assert taken_over(obligation(None, None), first, IST), "undated"


def test_an_applied_decision_replaces_only_an_earlier_one() -> None:
    made = datetime(2026, 10, 1, tzinfo=UTC)
    stored = AppliedDecision(
        TenantId.new(), BusinessId.new(), RuleVersionId.new(), DecisionId.new(), True, made
    )
    assert stored.supersedes(None)
    assert replace(stored, decided_at=made).supersedes(stored), "the same moment"
    assert not replace(stored, decided_at=made - timedelta(seconds=1)).supersedes(stored)
    with pytest.raises(InvariantViolationError):
        replace(stored, decided_at=datetime(2026, 10, 1))


def test_a_read_names_one_version() -> None:
    the_rule, other = rule(), rule()
    assert RuleVersionRead(the_rule, ref_of(the_rule)).ref.rule_version_id == (
        the_rule.rule_version_id
    )
    with pytest.raises(InvariantViolationError, match="other versions"):
        RuleVersionRead(the_rule, ref_of(other))
