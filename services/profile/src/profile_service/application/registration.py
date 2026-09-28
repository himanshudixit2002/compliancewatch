"""Create the nodes of the hierarchy: an entity from its PAN, a registration from its GSTIN
(finding or creating the entity the PAN names), a location under a registration."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from domain_kernel.events import utc_now
from domain_kernel.identifiers import Gstin, Pan
from domain_kernel.ids import BusinessId, TenantId
from domain_kernel.ontology import AttributeLevel
from profile_service.domain.errors import InvalidHierarchyError, ProfileNodeNotFoundError
from profile_service.domain.model import ProfileNode
from profile_service.domain.repository import UnitOfWorkFactory


@dataclass(frozen=True, slots=True)
class Registered:
    node: ProfileNode
    created: bool


class RegisterNodes:
    def __init__(
        self, unit_of_work: UnitOfWorkFactory, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    def entity(self, tenant_id: TenantId, pan: Pan, name: str) -> Registered:
        with self._unit_of_work(tenant_id) as uow:
            existing = uow.profiles.find_by_key(AttributeLevel.ENTITY, pan.value)
            if existing is not None:
                return Registered(existing, False)
            node = ProfileNode.entity(tenant_id=tenant_id, pan=pan, name=name, at=self._clock())
            uow.profiles.add(node)
            return Registered(node, True)

    def registration(
        self, tenant_id: TenantId, gstin: Gstin, name: str, *, entity_name: str = ""
    ) -> Registered:
        """The entity is found by the GSTIN's PAN or created with ``entity_name``."""
        with self._unit_of_work(tenant_id) as uow:
            existing = uow.profiles.find_by_key(AttributeLevel.REGISTRATION, gstin.value)
            if existing is not None:
                return Registered(existing, False)
            now = self._clock()
            entity = uow.profiles.find_by_key(AttributeLevel.ENTITY, gstin.pan.value)
            if entity is None:
                entity = ProfileNode.entity(
                    tenant_id=tenant_id, pan=gstin.pan, name=entity_name or name, at=now
                )
                uow.profiles.add(entity)
            node = ProfileNode.registration(
                tenant_id=tenant_id, entity=entity, gstin=gstin, name=name, at=now
            )
            uow.profiles.add(node)
            return Registered(node, True)

    def location(
        self, tenant_id: TenantId, registration_id: BusinessId, label: str, name: str
    ) -> Registered:
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
                at=self._clock(),
            )
            uow.profiles.add(node)
            return Registered(node, True)
