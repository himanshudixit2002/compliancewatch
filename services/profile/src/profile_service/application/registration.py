"""Create the nodes of the hierarchy: an entity from its PAN, a registration from its GSTIN
(finding or creating the entity the PAN names), a location under a registration.

``register_entity`` and ``register_registration`` do the work inside a unit of work the caller
holds, so a use case can create a business and fill it in one transaction; ``RegisterNodes``
opens one unit of work per call. Each node created writes its ``profile_node.registered`` audit
entry in the unit of work that creates it (``application.audit``); a node found writes none.

A new registration counts against the tenant's plan: the use cases read the limit from their
``EntitlementsReader`` before they open the unit of work (an HTTP call to identity must not hold
a transaction), and ``register_registration`` refuses a new GSTIN once the tenant holds that many
(``PlanLimitReachedError``, 402). A GSTIN the tenant already holds is found, never refused. Two
registrations racing for the last place can both pass; the plan is a commercial limit, not an
invariant, so that is accepted."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from domain_kernel.events import utc_now
from domain_kernel.identifiers import Gstin, Pan
from domain_kernel.ids import BusinessId, TenantId
from domain_kernel.ontology import AttributeLevel
from profile_service.application.audit import record_registered
from profile_service.domain.entitlements import EntitlementsReader
from profile_service.domain.errors import (
    InvalidHierarchyError,
    PlanLimitReachedError,
    ProfileNodeNotFoundError,
)
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


def registration_limit(entitlements: EntitlementsReader | None, tenant_id: TenantId) -> int | None:
    """How many registrations the tenant may hold; None is no limit (and no reader)."""
    return None if entitlements is None else entitlements.registration_limit(tenant_id)


def register_registration(
    uow: UnitOfWork,
    tenant_id: TenantId,
    gstin: Gstin,
    name: str,
    *,
    entity_name: str,
    now: datetime,
    limit: int | None = None,
) -> tuple[Registered, Registered]:
    """The entity the GSTIN's PAN names and the registration of ``gstin`` under it, each
    created when the tenant has none; a new registration past ``limit`` is refused."""
    existing = uow.profiles.find_by_key(AttributeLevel.REGISTRATION, gstin.value)
    if existing is not None:
        entity = None if existing.parent_id is None else uow.profiles.get(existing.parent_id)
        if entity is None:  # pragma: no cover - a registration always has its entity
            raise InvalidHierarchyError(f"registration {existing.id} has no entity")
        return Registered(entity, False), Registered(existing, False)
    if limit is not None:
        used = uow.profiles.count(AttributeLevel.REGISTRATION)
        if used >= limit:
            raise PlanLimitReachedError(limit=limit, used=used)
    entity_registered = register_entity(uow, tenant_id, gstin.pan, entity_name or name, now)
    node = ProfileNode.registration(
        tenant_id=tenant_id, entity=entity_registered.node, gstin=gstin, name=name, at=now
    )
    uow.profiles.add(node)
    record_registered(uow, node, now)
    return entity_registered, Registered(node, True)


class RegisterNodes:
    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        *,
        clock: Callable[[], datetime] = utc_now,
        entitlements: EntitlementsReader | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._entitlements = entitlements

    def entity(self, tenant_id: TenantId, pan: Pan, name: str) -> Registered:
        with self._unit_of_work(tenant_id) as uow:
            return register_entity(uow, tenant_id, pan, name, self._clock())

    def registration(
        self, tenant_id: TenantId, gstin: Gstin, name: str, *, entity_name: str = ""
    ) -> Registered:
        """The entity is found by the GSTIN's PAN or created with ``entity_name``."""
        limit = registration_limit(self._entitlements, tenant_id)
        with self._unit_of_work(tenant_id) as uow:
            _, registration = register_registration(
                uow,
                tenant_id,
                gstin,
                name,
                entity_name=entity_name,
                now=self._clock(),
                limit=limit,
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
