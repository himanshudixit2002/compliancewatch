"""Create the nodes of the hierarchy: an entity from its PAN, a registration from its GSTIN
(finding or creating the entity the PAN names), a location under a registration.

``register_entity`` and ``register_registration`` do the work inside a unit of work the caller
holds, so a use case can create a business and fill it in one transaction; ``RegisterNodes``
opens one unit of work per call. Each node created writes its ``profile_node.registered`` audit
entry in the unit of work that creates it (``application.audit``); a node found writes none."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from domain_kernel.events import utc_now
from domain_kernel.identifiers import Gstin, Pan
from domain_kernel.ids import BusinessId, TenantId
from domain_kernel.ontology import AttributeLevel
from profile_service.application.audit import record_registered
from profile_service.domain.errors import InvalidHierarchyError, ProfileNodeNotFoundError
from profile_service.domain.model import ProfileNode
from profile_service.domain.repository import UnitOfWork, UnitOfWorkFactory


@dataclass(frozen=True, slots=True)
class Registered:
    node: ProfileNode
    created: bool


def register_entity(
    uow: UnitOfWork, tenant_id: TenantId, pan: Pan, name: str, now: datetime
) -> Registered:
    """The entity of ``pan``, created with ``name`` when the tenant has none."""
    existing = uow.profiles.find_by_key(AttributeLevel.ENTITY, pan.value)
    if existing is not None:
        return Registered(existing, False)
    node = ProfileNode.entity(tenant_id=tenant_id, pan=pan, name=name, at=now)
    uow.profiles.add(node)
    record_registered(uow, node, now)
    return Registered(node, True)


def register_registration(
    uow: UnitOfWork,
    tenant_id: TenantId,
    gstin: Gstin,
    name: str,
    *,
    entity_name: str,
    now: datetime,
) -> tuple[Registered, Registered]:
    """The entity the GSTIN's PAN names and the registration of ``gstin`` under it, each
    created when the tenant has none."""
    existing = uow.profiles.find_by_key(AttributeLevel.REGISTRATION, gstin.value)
    if existing is not None:
        entity = None if existing.parent_id is None else uow.profiles.get(existing.parent_id)
        if entity is None:  # pragma: no cover - a registration always has its entity
            raise InvalidHierarchyError(f"registration {existing.id} has no entity")
        return Registered(entity, False), Registered(existing, False)
    entity_registered = register_entity(uow, tenant_id, gstin.pan, entity_name or name, now)
    node = ProfileNode.registration(
        tenant_id=tenant_id, entity=entity_registered.node, gstin=gstin, name=name, at=now
    )
    uow.profiles.add(node)
    record_registered(uow, node, now)
    return entity_registered, Registered(node, True)


class RegisterNodes:
    def __init__(
        self, unit_of_work: UnitOfWorkFactory, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    def entity(self, tenant_id: TenantId, pan: Pan, name: str) -> Registered:
        with self._unit_of_work(tenant_id) as uow:
            return register_entity(uow, tenant_id, pan, name, self._clock())

    def registration(
        self, tenant_id: TenantId, gstin: Gstin, name: str, *, entity_name: str = ""
    ) -> Registered:
        """The entity is found by the GSTIN's PAN or created with ``entity_name``."""
        with self._unit_of_work(tenant_id) as uow:
            _, registration = register_registration(
                uow, tenant_id, gstin, name, entity_name=entity_name, now=self._clock()
            )
            return registration

    def location(
        self, tenant_id: TenantId, registration_id: BusinessId, label: str, name: str
    ) -> Registered:
        now = self._clock()
        with self._unit_of_work(tenant_id) as uow:
            registration = uow.profiles.get(registration_id)
            if registration is None:
                raise ProfileNodeNotFoundError(str(registration_id))
            if registration.level is not AttributeLevel.REGISTRATION:
                raise InvalidHierarchyError("a location belongs to a registration")
            for child in uow.profiles.children(registration_id):
                if child.key == label:
                    return Registered(child, False)
            node = ProfileNode.location(
                tenant_id=tenant_id,
                registration=registration,
                label=label,
                name=name,
                at=now,
            )
            uow.profiles.add(node)
            record_registered(uow, node, now)
            return Registered(node, True)
