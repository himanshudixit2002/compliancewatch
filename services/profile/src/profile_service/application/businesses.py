"""The use cases of the business API: a business is a legal entity with its registrations.

``CreateBusiness`` creates one from its GSTIN (the entity comes from the PAN inside it, and the
registration is pre-filled as ``PrefillFromGstin`` does) or, without a GSTIN, from its PAN, and
stores the first answers. ``UpdateBusiness`` stores answers across the entity and its
registrations and may rename the business. ``ReadBusiness``, ``ListBusinesses`` (the tenant's
businesses by name, a page at a time) and ``AddRegistration`` complete the set. Each write runs
in one unit of work: a value the ontology refuses rolls every node back, and every node that
changed publishes ``profile.updated`` through the outbox, the event that recomputes the
business's obligations.

An answer goes to the node of its attribute's level. An entity-level attribute goes to the
entity. A registration-level one goes to the registration ``node_id`` names or, without one, to
the business's only registration; with none or several, RegistrationAmbiguousError. A
location-level one goes to the location ``node_id`` names, or to the only location.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from domain_kernel.events import utc_now
from domain_kernel.identifiers import Gstin, Pan
from domain_kernel.ids import BusinessId, TenantId, UserId
from domain_kernel.ontology import AttributeLevel, Ontology
from profile_service.application.attributes import apply_changes, financial_year_in_india
from profile_service.application.prefill import PrefillFromGstin, PrefillResult
from profile_service.application.registration import register_entity, register_registration
from profile_service.domain.errors import (
    BusinessIdentifierRequiredError,
    InvalidHierarchyError,
    NotABusinessError,
    ProfileNodeNotFoundError,
    RegistrationAmbiguousError,
)
from profile_service.domain.events import ChangeSource
from profile_service.domain.model import AttributeChange, ProfileNode
from profile_service.domain.onboarding import Checklist, build_checklist
from profile_service.domain.repository import UnitOfWork, UnitOfWorkFactory


@dataclass(frozen=True, slots=True)
class Business:
    """A legal entity and its registrations in the order they were created."""

    entity: ProfileNode
    registrations: tuple[ProfileNode, ...] = ()

    @property
    def id(self) -> BusinessId:
        """A business is known by its entity's node id."""
        return self.entity.id

    @property
    def nodes(self) -> tuple[ProfileNode, ...]:
        return (self.entity, *self.registrations)


@dataclass(frozen=True, slots=True)
class Answer:
    """A value, or an unsure or does-not-apply answer, for one attribute. ``node_id`` names the
    registration or location it is for when the business has several."""

    change: AttributeChange
    node_id: BusinessId | None = None


@dataclass(frozen=True, slots=True)
class BusinessCreated:
    business: Business
    created: bool
    """False when the tenant already had the business (the same PAN)."""
    prefill: PrefillResult | None
    """What the GSTIN pre-filled; None for a business created from its PAN alone."""
    checklist: Checklist


@dataclass(frozen=True, slots=True)
class RegistrationAdded:
    business: Business
    registration: ProfileNode
    created: bool
    prefill: PrefillResult


def load_business(uow: UnitOfWork, business_id: BusinessId) -> Business:
    """The business ``business_id`` names: ProfileNodeNotFoundError when the tenant has no such
    node, NotABusinessError when the node is a registration or a location."""
    node = uow.profiles.get(business_id)
    if node is None:
        raise ProfileNodeNotFoundError(str(business_id))
    if node.level is not AttributeLevel.ENTITY:
        raise NotABusinessError(str(business_id))
    return Business(node, tuple(uow.profiles.registrations_of([node.id])[node.id]))


def store_answers(
    uow: UnitOfWork,
    tenant_id: TenantId,
    business: Business,
    answers: Sequence[Answer],
    *,
    ontology: Ontology,
    by: UserId | None,
    now: datetime,
) -> Business:
    """Route each answer to its node and store the answers of each node as one batch, inside
    ``uow``. Returns the business as it stands afterwards."""
    if not answers:
        return business
    nodes = {node.id: node for node in business.nodes}
    batches: dict[BusinessId, list[AttributeChange]] = {}
    for answer in answers:
        target = _target(uow, business, answer, ontology)
        nodes.setdefault(target.id, target)
        batches.setdefault(target.id, []).append(answer.change)
    for node_id, changes in batches.items():
        apply_changes(
            uow,
            tenant_id,
            nodes[node_id],
            changes,
            ontology=ontology,
            source=ChangeSource.USER_INPUT,
            by=by,
            now=now,
        )
    return load_business(uow, business.id)


def _target(uow: UnitOfWork, business: Business, answer: Answer, ontology: Ontology) -> ProfileNode:
    key = answer.change.key
    level = ontology.require(key).level
    if answer.node_id is not None:
        node = next((node for node in business.nodes if node.id == answer.node_id), None)
        if node is None:
            node = next(
                (loc for loc in _locations(uow, business) if loc.id == answer.node_id), None
            )
        if node is None:
            raise InvalidHierarchyError(
                f"node {answer.node_id} is not part of business {business.id}"
            )
        return node
    if level is AttributeLevel.ENTITY:
        return business.entity
    candidates = (
        business.registrations
        if level is AttributeLevel.REGISTRATION
        else _locations(uow, business)
    )
    if len(candidates) != 1:
        raise RegistrationAmbiguousError(key, level.value, len(candidates))
    return candidates[0]


def _locations(uow: UnitOfWork, business: Business) -> list[ProfileNode]:
    return [
        child
        for registration in business.registrations
        for child in uow.profiles.children(registration.id)
        if child.level is AttributeLevel.LOCATION
    ]


def _require_pan(business: Business, gstin: Gstin) -> None:
    if gstin.pan.value != business.entity.key:
        raise InvalidHierarchyError(
            f"gstin {gstin} carries PAN {gstin.pan}; the business is PAN {business.entity.key}"
        )


class CreateBusiness:
    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        ontology: Ontology,
        prefill: PrefillFromGstin,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._ontology = ontology
        self._prefill = prefill
        self._clock = clock

    def run(
        self,
        tenant_id: TenantId,
        *,
        name: str,
        pan: Pan | None = None,
        gstin: Gstin | None = None,
        registration_name: str = "",
        answers: Sequence[Answer] = (),
        by: UserId | None = None,
    ) -> BusinessCreated:
        """``gstin``, when given, decides the PAN; ``pan`` alone creates the entity with no
        registration. ``name`` names the entity, and the registration too unless
        ``registration_name`` is given."""
        entity_pan = pan if gstin is None else gstin.pan
        if entity_pan is None:
            raise BusinessIdentifierRequiredError()
        if pan is not None and pan != entity_pan:
            raise InvalidHierarchyError(f"gstin {gstin} carries PAN {entity_pan}, not {pan}")
        looked_up = None if gstin is None else self._prefill.look_up(gstin)
        now = self._clock()
        prefilled: PrefillResult | None = None
        with self._unit_of_work(tenant_id) as uow:
            if gstin is None:
                entity = register_entity(uow, tenant_id, entity_pan, name, now)
            else:
                entity, registration = register_registration(
                    uow, tenant_id, gstin, registration_name or name, entity_name=name, now=now
                )
                prefilled = self._prefill.apply(uow, tenant_id, registration.node, looked_up, by=by)
            business = store_answers(
                uow,
                tenant_id,
                load_business(uow, entity.node.id),
                answers,
                ontology=self._ontology,
                by=by,
                now=now,
            )
        checklist = build_checklist(
            business.entity, business.registrations, self._ontology, financial_year_in_india(now)
        )
        return BusinessCreated(business, entity.created, prefilled, checklist)


class UpdateBusiness:
    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        ontology: Ontology,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._ontology = ontology
        self._clock = clock

    def run(
        self,
        tenant_id: TenantId,
        business_id: BusinessId,
        *,
        answers: Sequence[Answer] = (),
        name: str | None = None,
        by: UserId | None = None,
    ) -> Business:
        """Rename the business when ``name`` differs and store ``answers``, all or nothing."""
        now = self._clock()
        with self._unit_of_work(tenant_id) as uow:
            business = load_business(uow, business_id)
            if name is not None:
                renamed = business.entity.renamed(name, now)
                if renamed is not business.entity:
                    uow.profiles.save(renamed)
                    business = replace(business, entity=renamed)
            return store_answers(
                uow, tenant_id, business, answers, ontology=self._ontology, by=by, now=now
            )


class ReadBusiness:
    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self, tenant_id: TenantId, business_id: BusinessId) -> Business:
        with self._unit_of_work(tenant_id) as uow:
            return load_business(uow, business_id)


class ListBusinesses:
    """The tenant's businesses by name, for a CA's client list."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(
        self,
        tenant_id: TenantId,
        *,
        after: BusinessId | None = None,
        limit: int,
        query: str = "",
    ) -> list[Business]:
        """At most ``limit`` businesses after the business ``after``, whose name, PAN or GSTIN
        contains ``query``. ProfileNodeNotFoundError when ``after`` is not a business of the
        tenant."""
        if limit < 1:
            raise ValueError(f"limit must be at least 1, got {limit}")
        with self._unit_of_work(tenant_id) as uow:
            entities = uow.profiles.page_entities(after, limit, query)
            registrations = uow.profiles.registrations_of([entity.id for entity in entities])
        return [Business(entity, tuple(registrations[entity.id])) for entity in entities]


class AddRegistration:
    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        prefill: PrefillFromGstin,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._prefill = prefill
        self._clock = clock

    def run(
        self,
        tenant_id: TenantId,
        business_id: BusinessId,
        gstin: Gstin,
        *,
        name: str = "",
        by: UserId | None = None,
    ) -> RegistrationAdded:
        """Add the GSTIN under the business its PAN names and pre-fill it; a GSTIN the business
        already holds is returned as it is, with ``created`` False."""
        with self._unit_of_work(tenant_id) as uow:
            _require_pan(load_business(uow, business_id), gstin)
        looked_up = self._prefill.look_up(gstin)
        with self._unit_of_work(tenant_id) as uow:
            business = load_business(uow, business_id)
            _require_pan(business, gstin)
            _, registered = register_registration(
                uow,
                tenant_id,
                gstin,
                name or business.entity.name,
                entity_name=business.entity.name,
                now=self._clock(),
            )
            prefilled = self._prefill.apply(uow, tenant_id, registered.node, looked_up, by=by)
            business = load_business(uow, business_id)
        registration = next(node for node in business.registrations if node.id == prefilled.node_id)
        return RegistrationAdded(business, registration, registered.created, prefilled)
