"""Pre-fill a registration from its GSTIN and the GSTIN lookup, or ask a person to verify it later.

What the GSTIN itself says is written whatever the lookup answers: its first two digits are the
state code, so the entity's ``state_codes`` gains that code (source ``derived``, joined to the
codes already known). A code the ontology does not list, such as 97 (Other Territory) or 99
(Centre Jurisdiction), is not a place of business and is skipped.

The lookup answer becomes attribute values with source ``gstin_lookup`` (the path user input
takes, so the ontology validates them and ``profile.updated`` goes out). Entity-level attributes
(constitution) land on the registration's entity, registration-level ones on the registration.
``business_category`` is written only while the flag ``profile.gstin_category_prefill`` is on
for the tenant and the registry's activities mapped to exactly one category. When the lookup has
nothing, the registration keeps whatever the person entered and a ``verify_registration`` review
task is opened so the values are checked once a provider is available.

``run`` looks the GSTIN up outside any transaction and writes in one unit of work. ``look_up``
and ``apply`` are the two halves, for a use case that creates the registration and pre-fills it
in the same unit of work.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from domain_kernel.events import utc_now
from domain_kernel.identifiers import Gstin
from domain_kernel.ids import BusinessId, TenantId, UserId
from domain_kernel.ontology import AttributeLevel, AttributeSource, Ontology
from profile_service.application.attributes import apply_changes, open_review
from profile_service.domain.errors import InvalidHierarchyError, ProfileNodeNotFoundError
from profile_service.domain.events import ChangeSource
from profile_service.domain.flags import GSTIN_CATEGORY_PREFILL, FeatureFlags
from profile_service.domain.lookup import GstinLookupProvider, GstinLookupResult
from profile_service.domain.model import (
    AttributeChange,
    ProfileNode,
    ReviewReason,
    ReviewRequest,
    ValueState,
)
from profile_service.domain.repository import UnitOfWork, UnitOfWorkFactory

STATE_CODES = "state_codes"
BUSINESS_CATEGORY = "business_category"


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
        ontology: Ontology,
        flags: FeatureFlags,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._provider = provider
        self._ontology = ontology
        self._flags = flags
        self._clock = clock

    def run(
        self, tenant_id: TenantId, registration_id: BusinessId, *, by: UserId | None = None
    ) -> PrefillResult:
        with self._unit_of_work(tenant_id) as uow:
            gstin = Gstin(_registration(uow, registration_id).key)
        result = self.look_up(gstin)
        with self._unit_of_work(tenant_id) as uow:
            return self.apply(uow, tenant_id, _registration(uow, registration_id), result, by=by)

    def look_up(self, gstin: Gstin) -> GstinLookupResult | None:
        """The provider's answer; call it outside a transaction, since it may wait on a network."""
        return self._provider.lookup(gstin)

    def apply(
        self,
        uow: UnitOfWork,
        tenant_id: TenantId,
        registration: ProfileNode,
        result: GstinLookupResult | None,
        *,
        by: UserId | None = None,
    ) -> PrefillResult:
        """Write what the GSTIN and ``result`` say about ``registration`` inside ``uow``."""
        if registration.level is not AttributeLevel.REGISTRATION or registration.parent_id is None:
            raise InvalidHierarchyError("only a registration has a GSTIN to look up")
        entity = uow.profiles.get(registration.parent_id)
        if entity is None:
            raise ProfileNodeNotFoundError(str(registration.parent_id))
        now = self._clock()
        changes: dict[AttributeLevel, list[AttributeChange]] = {}
        derived = self._state_codes(entity, Gstin(registration.key))
        if derived is not None:
            changes.setdefault(AttributeLevel.ENTITY, []).append(derived)
        if result is not None:
            for key, value in self._looked_up_values(tenant_id, result).items():
                changes.setdefault(self._ontology.require(key).level, []).append(
                    AttributeChange(key=key, value=value, source=AttributeSource.GSTIN_LOOKUP)
                )
        applied: list[str] = []
        for node in (entity, registration):
            batch = changes.get(node.level, [])
            if batch:
                outcome = apply_changes(
                    uow,
                    tenant_id,
                    node,
                    batch,
                    ontology=self._ontology,
                    source=ChangeSource.GSTIN_LOOKUP,
                    by=by,
                    now=now,
                )
                applied.extend(outcome.changed)
        task = None if result is not None else _open_verification(uow, tenant_id, registration, now)
        return PrefillResult(registration.id, result is not None, result, tuple(applied), task)

    def _state_codes(self, entity: ProfileNode, gstin: Gstin) -> AttributeChange | None:
        """The entity's state codes joined with the GSTIN's, or None when there is nothing new."""
        definition = self._ontology.get(STATE_CODES)
        if definition is None or gstin.state_code not in definition.allowed_values:
            return None
        record = entity.value(STATE_CODES)
        known: frozenset[str] = frozenset()
        if record is not None and record.state is ValueState.KNOWN:
            known = definition.members(record.value)
        if gstin.state_code in known:
            return None
        return AttributeChange(
            key=STATE_CODES,
            value=sorted(known | {gstin.state_code}),
            source=AttributeSource.DERIVED,
        )

    def _looked_up_values(
        self, tenant_id: TenantId, result: GstinLookupResult
    ) -> dict[str, object]:
        values = result.attribute_values()
        if result.business_category and self._flags.enabled(GSTIN_CATEGORY_PREFILL, tenant_id):
            values[BUSINESS_CATEGORY] = result.business_category
        return values


def _registration(uow: UnitOfWork, registration_id: BusinessId) -> ProfileNode:
    node = uow.profiles.get(registration_id)
    if node is None:
        raise ProfileNodeNotFoundError(str(registration_id))
    if node.level is not AttributeLevel.REGISTRATION:
        raise InvalidHierarchyError("only a registration has a GSTIN to look up")
    return node


def _open_verification(
    uow: UnitOfWork, tenant_id: TenantId, registration: ProfileNode, now: datetime
) -> BusinessId:
    """The open verify_registration task of the registration, opened now when there is none."""
    for task in uow.profiles.open_review_tasks(registration.id):
        if task.reason is ReviewReason.VERIFY_REGISTRATION:
            return task.id
    request = ReviewRequest(registration.id, "registration_type", ReviewReason.VERIFY_REGISTRATION)
    return open_review(uow, tenant_id, request, now)
