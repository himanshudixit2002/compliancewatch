"""What a decision is computed from, as protocols the infrastructure implements over HTTP, and
the fan-out workflows the controls start and signal (Temporal in a deployment)."""

from collections.abc import Sequence
from datetime import date
from typing import Protocol

from applicability_engine.domain.fanout import FanOutSignal, FanOutStart
from applicability_engine.domain.model import RuleInForce, RuleVersionSpec
from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import BusinessId, RuleVersionId, TenantId
from domain_kernel.ontology import AttributeLevel
from domain_kernel.profiles import ProfileSnapshot


class ProfileReader(Protocol):
    def snapshot(
        self, tenant_id: TenantId, business_id: BusinessId, fy: FinancialYear | None
    ) -> ProfileSnapshot | None:
        """The business's attributes, inherited down its lineage, with the per-year ones of
        ``fy``; None when the tenant has no such business."""
        ...

    def registrations(
        self, tenant_id: TenantId, entity_id: BusinessId
    ) -> Sequence[BusinessId] | None:
        """The GSTIN registrations under the legal entity ``entity_id``, oldest first; None
        when the tenant has no such entity."""
        ...


class RulebookReader(Protocol):
    def rule_version(self, rule_version_id: RuleVersionId) -> RuleVersionSpec | None:
        """The rule version in any status; None when the rulebook has no such version."""
        ...

    def rules_in_force(self, as_of: date, level: AttributeLevel) -> Sequence[RuleInForce]:
        """The published rule versions in force on ``as_of`` whose rules apply to nodes of
        ``level``, by rule key."""
        ...

    def forget_in_force(self) -> None:
        """Drop any cached listing of the versions in force, so the next read asks the rulebook:
        a version was published or withdrawn."""
        ...


class FanOutWorkflows(Protocol):
    """The workflows that run the fan-outs, one per rule version."""

    def start(self, start: FanOutStart) -> bool:
        """Start the fan-out of ``start``; False when the version's fan-out was started before
        (a duplicate start is refused, finished or not)."""
        ...

    def signal(self, rule_version_id: RuleVersionId, signal: FanOutSignal) -> None:
        """Tell the version's workflow its row changed. Best effort: a signal that cannot be
        delivered is logged, never raised, and the workflow sees the change when it next reads
        its row (at its next batch boundary, or its next poll while it waits)."""
        ...
