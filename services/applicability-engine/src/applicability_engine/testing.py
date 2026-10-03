"""Fakes and builders for tests of this service and of services that consume its events: fixed
ids, a fixed clock, a profile service and a rulebook held in memory."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime

from applicability_engine.domain.model import RuleVersionSpec
from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import BusinessId, RuleVersionId, TenantId
from domain_kernel.predicates import Specification, specification_from_mapping
from domain_kernel.profiles import ProfileSnapshot
from domain_kernel.status import RuleVersionStatus

TENANT = TenantId.new()
OTHER_TENANT = TenantId.new()
BUSINESS = BusinessId.new()
NOW = datetime(2026, 10, 1, 4, 30, tzinfo=UTC)
FY = FinancialYear(2026)


def clock() -> datetime:
    return NOW


def rule_version(
    specification: Specification | Mapping[str, object],
    *,
    status: RuleVersionStatus = RuleVersionStatus.PUBLISHED,
    rule_version_id: RuleVersionId | None = None,
) -> RuleVersionSpec:
    return RuleVersionSpec(
        rule_version_id=rule_version_id or RuleVersionId.new(),
        status=status,
        specification=specification
        if isinstance(specification, Specification)
        else specification_from_mapping(specification),
    )


@dataclass
class MemoryProfiles:
    """``ProfileReader`` over snapshots keyed by tenant and business; records the years asked."""

    snapshots: dict[tuple[TenantId, BusinessId], ProfileSnapshot] = field(default_factory=dict)
    asked: list[FinancialYear | None] = field(default_factory=list)

    def put(
        self,
        attributes: Mapping[str, object],
        *,
        tenant_id: TenantId = TENANT,
        business_id: BusinessId = BUSINESS,
        version: int = 1,
    ) -> ProfileSnapshot:
        snapshot = ProfileSnapshot(business_id, tenant_id, version, attributes, as_of_fy=FY)
        self.snapshots[(tenant_id, business_id)] = snapshot
        return snapshot

    def snapshot(
        self, tenant_id: TenantId, business_id: BusinessId, fy: FinancialYear | None
    ) -> ProfileSnapshot | None:
        self.asked.append(fy)
        return self.snapshots.get((tenant_id, business_id))


@dataclass
class MemoryRulebook:
    """``RulebookReader`` over rule versions keyed by id."""

    versions: dict[RuleVersionId, RuleVersionSpec] = field(default_factory=dict)

    def put(self, version: RuleVersionSpec) -> RuleVersionSpec:
        self.versions[version.rule_version_id] = version
        return version

    def rule_version(self, rule_version_id: RuleVersionId) -> RuleVersionSpec | None:
        return self.versions.get(rule_version_id)
