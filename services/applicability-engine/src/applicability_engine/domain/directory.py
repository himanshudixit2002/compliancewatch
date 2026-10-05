"""The business directory: every hierarchy node the engine has heard of, by tenant.

A profile.updated event names a node (a legal entity, a registration or a location); the engine
records it, and the registrations it finds under an entity, with the node's level, its parent
and the entity at the top of its lineage. The ids are what a fan-out over every business
(rule.published, ``domain.fanout``) reads across tenants, by tenant then node, before it opens one
tenant's unit of work at a time; a node's place in the hierarchy never changes, so an entry is
written once.
"""

from dataclasses import dataclass

from domain_kernel._validation import require_instance
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import BusinessId, TenantId
from domain_kernel.ontology import AttributeLevel


@dataclass(frozen=True, slots=True)
class DirectoryEntry:
    """One node: ``parent_id`` is None for a legal entity, and ``entity_id`` is the entity at the
    top of the node's lineage (the node itself for an entity)."""

    tenant_id: TenantId
    business_id: BusinessId
    level: AttributeLevel
    parent_id: BusinessId | None
    entity_id: BusinessId

    def __post_init__(self) -> None:
        require_instance(self.tenant_id, TenantId, "tenant_id")
        require_instance(self.business_id, BusinessId, "business_id")
        require_instance(self.level, AttributeLevel, "level")
        require_instance(self.entity_id, BusinessId, "entity_id")
        if self.level is AttributeLevel.ENTITY:
            if self.parent_id is not None or self.entity_id != self.business_id:
                raise InvariantViolationError("a legal entity has no parent and is its own entity")
        else:
            require_instance(self.parent_id, BusinessId, "parent_id")


@dataclass(frozen=True, slots=True)
class DirectoryKey:
    """Where a page of the directory ends: by tenant, then by node."""

    tenant_id: TenantId
    business_id: BusinessId

    def __post_init__(self) -> None:
        require_instance(self.tenant_id, TenantId, "tenant_id")
        require_instance(self.business_id, BusinessId, "business_id")

    @classmethod
    def of(cls, entry: DirectoryEntry) -> "DirectoryKey":
        return cls(entry.tenant_id, entry.business_id)
