"""What a decision is computed from, as protocols the infrastructure implements over HTTP."""

from typing import Protocol

from applicability_engine.domain.model import RuleVersionSpec
from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import BusinessId, RuleVersionId, TenantId
from domain_kernel.profiles import ProfileSnapshot


class ProfileReader(Protocol):
    def snapshot(
        self, tenant_id: TenantId, business_id: BusinessId, fy: FinancialYear | None
    ) -> ProfileSnapshot | None:
        """The business's attributes, inherited down its lineage, with the per-year ones of
        ``fy``; None when the tenant has no such business."""
        ...


class RulebookReader(Protocol):
    def rule_version(self, rule_version_id: RuleVersionId) -> RuleVersionSpec | None:
        """The rule version in any status; None when the rulebook has no such version."""
        ...
