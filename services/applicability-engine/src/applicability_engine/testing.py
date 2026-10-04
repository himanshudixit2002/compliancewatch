"""Fakes and builders for tests of this service and of services that consume its events: fixed
ids, a fixed clock, a profile service and a rulebook held in memory."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from applicability_engine.domain.model import RuleInForce, RuleVersionSpec
from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import BusinessId, RuleVersionId, TenantId
from domain_kernel.ontology import AttributeLevel
from domain_kernel.predicates import Specification, specification_from_mapping
from domain_kernel.profiles import ProfileSnapshot
from domain_kernel.status import RuleVersionStatus

TENANT = TenantId.new()
OTHER_TENANT = TenantId.new()
BUSINESS = BusinessId.new()
NOW = datetime(2026, 10, 1, 4, 30, tzinfo=UTC)
FY = FinancialYear(2026)
EFFECTIVE = date(2026, 4, 1)


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


def rule_in_force(
    specification: Specification | Mapping[str, object],
    *,
    rule_key: str = "example_rule",
    level: AttributeLevel = AttributeLevel.REGISTRATION,
    effective_from: date = EFFECTIVE,
    effective_to: date | None = None,
    rule_version_id: RuleVersionId | None = None,
) -> RuleInForce:
    """A published version in force from ``effective_from`` for nodes of ``level``."""
    return RuleInForce(
        spec=rule_version(specification, rule_version_id=rule_version_id),
        rule_key=rule_key,
        level=level,
        effective_from=effective_from,
        effective_to=effective_to,
    )


@dataclass
class MemoryProfiles:
    """``ProfileReader`` over snapshots keyed by tenant and business, and the registrations of
    each entity; records the years asked."""

    snapshots: dict[tuple[TenantId, BusinessId], ProfileSnapshot] = field(default_factory=dict)
    children: dict[tuple[TenantId, BusinessId], list[BusinessId]] = field(default_factory=dict)
    asked: list[FinancialYear | None] = field(default_factory=list)

    def put(
        self,
        attributes: Mapping[str, object],
        *,
        tenant_id: TenantId = TENANT,
        business_id: BusinessId = BUSINESS,
        version: int = 1,
        level: AttributeLevel | None = AttributeLevel.REGISTRATION,
        lineage: Sequence[BusinessId] = (),
    ) -> ProfileSnapshot:
        snapshot = ProfileSnapshot(
            business_id,
            tenant_id,
            version,
            attributes,
            as_of_fy=FY,
            level=level,
            lineage=tuple(lineage),
        )
        self.snapshots[(tenant_id, business_id)] = snapshot
        if lineage and level is AttributeLevel.REGISTRATION:
            registrations = self.children.setdefault((tenant_id, lineage[0]), [])
            if business_id not in registrations:
                registrations.append(business_id)
        return snapshot

    def snapshot(
        self, tenant_id: TenantId, business_id: BusinessId, fy: FinancialYear | None
    ) -> ProfileSnapshot | None:
        self.asked.append(fy)
        return self.snapshots.get((tenant_id, business_id))

    def registrations(
        self, tenant_id: TenantId, entity_id: BusinessId
    ) -> Sequence[BusinessId] | None:
        if (tenant_id, entity_id) not in self.snapshots:
            return None
        return tuple(self.children.get((tenant_id, entity_id), ()))


@dataclass
class MemoryRulebook:
    """``RulebookReader`` over rule versions keyed by id, and the versions in force; records
    the days asked for."""

    versions: dict[RuleVersionId, RuleVersionSpec] = field(default_factory=dict)
    in_force: list[RuleInForce] = field(default_factory=list)
    asked: list[date] = field(default_factory=list)

    def put(self, version: RuleVersionSpec) -> RuleVersionSpec:
        self.versions[version.rule_version_id] = version
        return version

    def put_in_force(self, rule: RuleInForce) -> RuleInForce:
        self.put(rule.spec)
        self.in_force.append(rule)
        return rule

    def rule_version(self, rule_version_id: RuleVersionId) -> RuleVersionSpec | None:
        return self.versions.get(rule_version_id)

    def rules_in_force(self, as_of: date, level: AttributeLevel) -> Sequence[RuleInForce]:
        self.asked.append(as_of)
        return tuple(
            rule
            for rule in self.in_force
            if rule.level is level
            and rule.effective_from <= as_of
            and (rule.effective_to is None or as_of < rule.effective_to)
        )
