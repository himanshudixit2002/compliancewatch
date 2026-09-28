"""Builders for tests of this service and of services that consume its events: fixed ids, a
fixed clock and a sample recurring rule version."""

from datetime import UTC, date, datetime

from domain_kernel.ids import BusinessId, DecisionId, RuleId, RuleVersionId, TenantId
from domain_kernel.operators import Operator
from domain_kernel.periods import EffectivePeriod
from domain_kernel.predicates import Predicate
from domain_kernel.recurrence import Recurrence
from domain_kernel.rules import ObligationTemplate, RuleVersionSnapshot

TENANT = TenantId.new()
OTHER_TENANT = TenantId.new()
BUSINESS = BusinessId.new()
DECISION = DecisionId.new()
NOW = datetime(2026, 9, 28, 10, 0, tzinfo=UTC)


def clock() -> datetime:
    return NOW


MONTHLY_ON_THE_20TH = Recurrence.monthly(20)


def rule(
    *,
    recurrence: Recurrence | None = MONTHLY_ON_THE_20TH,
    due_in_days: int | None = None,
    effective_from: date = date(2026, 4, 1),
) -> RuleVersionSnapshot:
    return RuleVersionSnapshot(
        rule_id=RuleId.new(),
        rule_version_id=RuleVersionId.new(),
        version=1,
        regulator="cbic",
        title="File GSTR-3B every month",
        specification=Predicate("registration_type", Operator.EQ, "regular"),
        effective=EffectivePeriod(effective_from),
        obligation_template=ObligationTemplate(
            "File GSTR-3B", ("Reconcile", "File"), due_in_days, "filing_acknowledgement"
        ),
        recurrence=recurrence,
    )
