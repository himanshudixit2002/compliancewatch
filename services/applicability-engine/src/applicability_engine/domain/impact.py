"""The impact of a change on one tenant: each business's latest decision of a rule version, by
the client it belongs to.

A change of the rulebook is about one rule version (``GET /v1/changes``); its impact on a tenant
is the latest decision of that version for each of the tenant's businesses, which the fan-out of
its publication made, a profile change made since, or a reviewer settled. Each business is placed
under the legal entity at the top of its lineage, as the business directory records it, so a CA
firm sees its affected clients with the registrations under each; a business the directory does
not list stands under itself. The fan-out of the version, when there is one, says how far the
platform got deciding it.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

from applicability_engine.domain.fanout import FanOutRun
from applicability_engine.domain.model import Decision
from domain_kernel._validation import require_instance
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import BusinessId, RuleVersionId, TenantId
from domain_kernel.ontology import AttributeLevel
from domain_kernel.predicates import Applicability

MAX_ENTITIES: Final = 201
"""The most clients one read returns: the longest page and the one that tells there is another."""


@dataclass(frozen=True, slots=True)
class ImpactEntry:
    """One business's latest decision of the version, with the entity it stands under and its
    level; both from the business directory, the business itself and None when it is not
    listed."""

    entity_id: BusinessId
    level: AttributeLevel | None
    decision: Decision

    def __post_init__(self) -> None:
        require_instance(self.entity_id, BusinessId, "entity_id")
        require_instance(self.decision, Decision, "decision")

    @property
    def business_id(self) -> BusinessId:
        return self.decision.business_id


@dataclass(frozen=True, slots=True)
class ImpactGroup:
    """The businesses of one client (a legal entity), each with its latest decision."""

    entity_id: BusinessId
    entries: tuple[ImpactEntry, ...]


@dataclass(frozen=True, slots=True)
class ImpactQuery:
    """One page of the impact on ``tenant_id``: the clients after ``after`` (by entity id), at
    most ``limit``, keeping the businesses whose latest decision is ``result`` when one is
    named."""

    tenant_id: TenantId
    rule_version_id: RuleVersionId
    limit: int
    result: Applicability | None = None
    after: BusinessId | None = None

    def __post_init__(self) -> None:
        require_instance(self.tenant_id, TenantId, "tenant_id")
        require_instance(self.rule_version_id, RuleVersionId, "rule_version_id")
        if self.limit < 1:
            raise InvariantViolationError("limit must be at least 1")


@dataclass(frozen=True, slots=True)
class ChangeImpact:
    """A page of the impact: the clients in entity order, ``counts`` of the latest decisions of
    every business of the tenant by result (all of them, whatever the page and the filter), and
    the version's fan-out, or None when it never had one."""

    rule_version_id: RuleVersionId
    groups: tuple[ImpactGroup, ...]
    counts: Mapping[Applicability, int] = field(default_factory=dict)
    fan_out: FanOutRun | None = None


def grouped(entries: Sequence[ImpactEntry]) -> tuple[ImpactGroup, ...]:
    """``entries``, which come by entity then business, as one group per entity."""
    groups: list[ImpactGroup] = []
    for entry in entries:
        if groups and groups[-1].entity_id == entry.entity_id:
            last = groups[-1]
            groups[-1] = ImpactGroup(last.entity_id, (*last.entries, entry))
        else:
            groups.append(ImpactGroup(entry.entity_id, (entry,)))
    return tuple(groups)


def every_result(counts: Mapping[Applicability, int]) -> dict[Applicability, int]:
    """``counts`` with every result, zero where none was counted."""
    return {result: counts.get(result, 0) for result in Applicability}
