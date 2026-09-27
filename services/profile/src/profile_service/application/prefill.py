"""Pre-fill a registration from the GSTIN lookup, or ask a person to verify it later.

The lookup answer becomes attribute values with source ``gstin_lookup`` (the same path user
input takes, so the ontology validates them and ``profile.updated`` goes out). Entity-level
attributes (constitution) land on the registration's entity, registration-level ones on the
registration. Nothing comes back: the registration keeps whatever the person entered and a
``verify_registration`` review task is opened so the values are checked once a provider is
available.
"""

from dataclasses import dataclass

from domain_kernel.identifiers import Gstin
from domain_kernel.ids import BusinessId, TenantId, UserId
from domain_kernel.ontology import AttributeLevel, AttributeSource, Ontology
from profile_service.application.attributes import SetAttributes, open_review
from profile_service.domain.errors import InvalidHierarchyError, ProfileNodeNotFoundError
from profile_service.domain.events import ChangeSource
from profile_service.domain.lookup import GstinLookupProvider, GstinLookupResult
from profile_service.domain.model import (
    AttributeChange,
    ReviewReason,
    ReviewRequest,
    ValueState,
)
from profile_service.domain.repository import UnitOfWorkFactory


@dataclass(frozen=True, slots=True)
class PrefillResult:
    node_id: BusinessId
    looked_up: bool
    result: GstinLookupResult | None
    applied: tuple[str, ...]
    review_task: BusinessId | None


class PrefillFromGstin:
    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        provider: GstinLookupProvider,
        set_attributes: SetAttributes,
        ontology: Ontology,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._provider = provider
        self._set_attributes = set_attributes
        self._ontology = ontology

    def run(
        self, tenant_id: TenantId, registration_id: BusinessId, *, by: UserId | None = None
    ) -> PrefillResult:
        with self._unit_of_work(tenant_id) as uow:
            node = uow.profiles.get(registration_id)
            if node is None:
                raise ProfileNodeNotFoundError(str(registration_id))
            if node.level is not AttributeLevel.REGISTRATION:
                raise InvalidHierarchyError("only a registration has a GSTIN to look up")
            gstin = Gstin(node.key)
            entity_id = node.parent_id
        result = self._provider.lookup(gstin)
        if result is None:
            task_id = self._open_verification(tenant_id, registration_id)
            return PrefillResult(registration_id, False, None, (), task_id)
        by_node: dict[BusinessId, list[AttributeChange]] = {}
        for key, value in result.attribute_values().items():
            level = self._ontology.require(key).level
            target = entity_id if level is AttributeLevel.ENTITY else registration_id
            if target is None:
                continue
            by_node.setdefault(target, []).append(
                AttributeChange(
                    key=key,
                    value=value,
                    state=ValueState.KNOWN,
                    source=AttributeSource.GSTIN_LOOKUP,
                )
            )
        applied: list[str] = []
        for target, changes in by_node.items():
            outcome = self._set_attributes.run(
                tenant_id, target, changes, source=ChangeSource.GSTIN_LOOKUP, by=by
            )
            applied.extend(outcome.changed)
        return PrefillResult(registration_id, True, result, tuple(applied), None)

    def _open_verification(self, tenant_id: TenantId, node_id: BusinessId) -> BusinessId | None:
        request = ReviewRequest(node_id, "registration_type", ReviewReason.VERIFY_REGISTRATION)
        with self._unit_of_work(tenant_id) as uow:
            for task in uow.profiles.open_review_tasks(node_id):
                if task.reason is ReviewReason.VERIFY_REGISTRATION:
                    return task.id
            return open_review(uow, tenant_id, request, self._set_attributes.now())
