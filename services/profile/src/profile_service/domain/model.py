"""The business hierarchy: legal entity (PAN), registration (GSTIN), location (ADR-016).

A ``ProfileNode`` holds the attribute values that live at its level. A value is ``known``
(with a value the ontology accepted), ``unsure`` (the business could not answer; the next
question asks for it) or ``not_applicable`` (the business says the attribute does not apply,
which raises a review task rather than a silent default). A per-financial-year attribute is
stored once per year. Every change bumps the node's version and yields a ``profile.updated``
event. A snapshot for the applicability engine merges the lineage from the entity down and
picks the values for the financial year asked about.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Self, cast

from domain_kernel._validation import (
    require_aware,
    require_instance,
    require_int,
    require_mapping,
    require_text,
)
from domain_kernel.errors import InvariantViolationError
from domain_kernel.financial_year import FinancialYear
from domain_kernel.identifiers import Gstin, Pan
from domain_kernel.ids import BusinessId, TenantId, UserId
from domain_kernel.ontology import AttributeLevel, AttributeSource, Ontology
from domain_kernel.profiles import ProfileSnapshot
from profile_service.domain.errors import (
    AttributeLevelMismatchError,
    FinancialYearRequiredError,
    InvalidHierarchyError,
)
from profile_service.domain.events import ChangeSource, ProfileUpdated


class ValueState(StrEnum):
    KNOWN = "known"
    UNSURE = "unsure"
    NOT_APPLICABLE = "not_applicable"


class ReviewReason(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    CONFIRM_FINANCIAL_YEAR = "confirm_financial_year"


type AttributeKey = tuple[str, str | None]
"""(attribute key, financial year label or None): what one stored value is keyed by."""


@dataclass(frozen=True, slots=True)
class AttributeRecord:
    key: str
    state: ValueState
    value: object = None
    as_of_fy: FinancialYear | None = None
    source: AttributeSource = AttributeSource.USER_INPUT
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        require_text(self.key, "key")
        require_instance(self.state, ValueState, "state")
        if self.state is ValueState.KNOWN and self.value is None:
            raise InvariantViolationError(f"{self.key}: a known value cannot be None")
        if self.state is not ValueState.KNOWN and self.value is not None:
            raise InvariantViolationError(f"{self.key}: only a known value carries a value")
        if self.as_of_fy is not None:
            require_instance(self.as_of_fy, FinancialYear, "as_of_fy")
        require_instance(self.source, AttributeSource, "source")
        if self.updated_at is not None:
            require_aware(self.updated_at, "updated_at")

    @property
    def storage_key(self) -> AttributeKey:
        return (self.key, None if self.as_of_fy is None else self.as_of_fy.label)


@dataclass(frozen=True, slots=True)
class AttributeChange:
    """What a caller asks to store: a value, or a state without one."""

    key: str
    value: object = None
    state: ValueState = ValueState.KNOWN
    as_of_fy: FinancialYear | None = None
    source: AttributeSource = AttributeSource.USER_INPUT

    def __post_init__(self) -> None:
        require_text(self.key, "key")
        require_instance(self.state, ValueState, "state")
        if self.state is ValueState.KNOWN and self.value is None:
            raise InvariantViolationError(f"{self.key}: a known value cannot be None")
        if self.as_of_fy is not None:
            require_instance(self.as_of_fy, FinancialYear, "as_of_fy")
        require_instance(self.source, AttributeSource, "source")


@dataclass(frozen=True, slots=True)
class ReviewRequest:
    """A review task the change asks for; the application layer persists it."""

    node_id: BusinessId
    attribute_key: str
    reason: ReviewReason
    as_of_fy: FinancialYear | None = None


@dataclass(frozen=True, slots=True)
class ChangeOutcome:
    node: "ProfileNode"
    event: ProfileUpdated | None
    reviews: tuple[ReviewRequest, ...]


@dataclass(frozen=True, slots=True)
class ProfileNode:
    id: BusinessId
    tenant_id: TenantId
    level: AttributeLevel
    key: str
    name: str
    parent_id: BusinessId | None
    version: int
    created_at: datetime
    updated_at: datetime
    attributes: Mapping[AttributeKey, AttributeRecord] = field(
        default_factory=lambda: MappingProxyType({}), hash=False
    )

    def __post_init__(self) -> None:
        require_instance(self.id, BusinessId, "id")
        require_instance(self.tenant_id, TenantId, "tenant_id")
        require_instance(self.level, AttributeLevel, "level")
        key = require_text(self.key, "key")
        require_instance(self.name, str, "name")
        require_int(self.version, "version", minimum=1)
        require_aware(self.created_at, "created_at")
        require_aware(self.updated_at, "updated_at")
        if (self.parent_id is None) != (self.level is AttributeLevel.ENTITY):
            raise InvalidHierarchyError(
                "an entity has no parent; a registration or location has exactly one"
            )
        if self.parent_id is not None:
            require_instance(self.parent_id, BusinessId, "parent_id")
        if self.level is AttributeLevel.ENTITY:
            Pan(key)
        elif self.level is AttributeLevel.REGISTRATION:
            Gstin(key)
        raw = cast(Mapping[AttributeKey, object], require_mapping(self.attributes, "attributes"))
        records: dict[AttributeKey, AttributeRecord] = {}
        for storage_key, item in raw.items():
            record = require_instance(item, AttributeRecord, "attributes[]")
            records[storage_key] = record
            if record.storage_key != storage_key:
                raise InvariantViolationError(
                    f"attribute {storage_key} is stored under the wrong key"
                )
        object.__setattr__(self, "attributes", MappingProxyType(records))

    @classmethod
    def entity(
        cls,
        *,
        tenant_id: TenantId,
        pan: Pan,
        name: str,
        at: datetime,
        node_id: BusinessId | None = None,
    ) -> Self:
        return cls(
            id=node_id or BusinessId.new(),
            tenant_id=tenant_id,
            level=AttributeLevel.ENTITY,
            key=pan.value,
            name=name,
            parent_id=None,
            version=1,
            created_at=at,
            updated_at=at,
        )

    @classmethod
    def registration(
        cls,
        *,
        tenant_id: TenantId,
        entity: "ProfileNode",
        gstin: Gstin,
        name: str,
        at: datetime,
        node_id: BusinessId | None = None,
    ) -> Self:
        if entity.level is not AttributeLevel.ENTITY or entity.tenant_id != tenant_id:
            raise InvalidHierarchyError("a registration belongs to an entity of the same tenant")
        if gstin.pan.value != entity.key:
            raise InvalidHierarchyError(
                f"gstin {gstin} carries PAN {gstin.pan}, the entity is {entity.key}"
            )
        return cls(
            id=node_id or BusinessId.new(),
            tenant_id=tenant_id,
            level=AttributeLevel.REGISTRATION,
            key=gstin.value,
            name=name,
            parent_id=entity.id,
            version=1,
            created_at=at,
            updated_at=at,
        )

    @classmethod
    def location(
        cls,
        *,
        tenant_id: TenantId,
        registration: "ProfileNode",
        label: str,
        name: str,
        at: datetime,
        node_id: BusinessId | None = None,
    ) -> Self:
        if (
            registration.level is not AttributeLevel.REGISTRATION
            or registration.tenant_id != tenant_id
        ):
            raise InvalidHierarchyError("a location belongs to a registration of the same tenant")
        return cls(
            id=node_id or BusinessId.new(),
            tenant_id=tenant_id,
            level=AttributeLevel.LOCATION,
            key=require_text(label, "label"),
            name=name,
            parent_id=registration.id,
            version=1,
            created_at=at,
            updated_at=at,
        )

    def apply(
        self,
        changes: Sequence[AttributeChange],
        *,
        ontology: Ontology,
        source: ChangeSource,
        at: datetime,
        by: UserId | None = None,
    ) -> ChangeOutcome:
        """Store the changes the ontology accepts at this level; one event for the batch."""
        require_aware(at, "at")
        records = dict(self.attributes)
        changed: list[str] = []
        reviews: list[ReviewRequest] = []
        for change in changes:
            definition = ontology.require(change.key)
            if definition.level is not self.level:
                raise AttributeLevelMismatchError(
                    change.key, definition.level.value, self.level.value
                )
            if definition.per_financial_year and change.as_of_fy is None:
                raise FinancialYearRequiredError(change.key)
            if not definition.per_financial_year and change.as_of_fy is not None:
                raise InvariantViolationError(
                    f"{change.key} is not stated per financial year; drop as_of_fy"
                )
            value = (
                ontology.validate_value(change.key, change.value)
                if change.state is ValueState.KNOWN
                else None
            )
            record = AttributeRecord(
                key=change.key,
                state=change.state,
                value=value,
                as_of_fy=change.as_of_fy,
                source=change.source,
                updated_at=at,
            )
            previous = records.get(record.storage_key)
            if previous is not None and _same(previous, record):
                continue
            records[record.storage_key] = record
            if change.key not in changed:
                changed.append(change.key)
            if change.state is ValueState.NOT_APPLICABLE:
                reviews.append(
                    ReviewRequest(self.id, change.key, ReviewReason.NOT_APPLICABLE, change.as_of_fy)
                )
        if not changed:
            return ChangeOutcome(self, None, ())
        node = replace(
            self, version=self.version + 1, updated_at=at, attributes=MappingProxyType(records)
        )
        event = ProfileUpdated(
            tenant_id=self.tenant_id,
            occurred_at=at,
            business_id=self.id,
            profile_version=node.version,
            changed_attributes=tuple(changed),
            ontology_version=ontology.version,
            source=source,
            changed_by=by,
        )
        return ChangeOutcome(node, event, tuple(reviews))

    def value(self, key: str, as_of_fy: FinancialYear | None = None) -> AttributeRecord | None:
        return self.attributes.get((key, None if as_of_fy is None else as_of_fy.label))

    def known_values(self, as_of_fy: FinancialYear | None) -> dict[str, object]:
        """Known values at this node: plain ones plus the per-year ones for ``as_of_fy``."""
        values: dict[str, object] = {}
        for (key, fy_label), record in self.attributes.items():
            if record.state is not ValueState.KNOWN:
                continue
            if fy_label is None or (as_of_fy is not None and fy_label == as_of_fy.label):
                values[key] = record.value
        return values

    def snapshot(
        self, lineage: Sequence["ProfileNode"], *, as_of_fy: FinancialYear | None
    ) -> ProfileSnapshot:
        """Attributes inherited from the entity down to this node, child values winning."""
        chain = [*lineage, self]
        _require_chain(chain)
        attributes: dict[str, object] = {}
        for node in chain:
            attributes.update(node.known_values(as_of_fy))
        return ProfileSnapshot(
            business_id=self.id,
            tenant_id=self.tenant_id,
            version=self.version,
            attributes=attributes,
            as_of_fy=as_of_fy,
            level=self.level,
            lineage=tuple(node.id for node in lineage),
        )

    def next_question(self, ontology: Ontology, *, as_of_fy: FinancialYear) -> str | None:
        """The first attribute of this level that is missing or unsure: one question at a time."""
        for definition in ontology:
            if definition.level is not self.level:
                continue
            record = self.value(definition.key, as_of_fy if definition.per_financial_year else None)
            if record is None or record.state is ValueState.UNSURE:
                return definition.key
        return None

    def missing_for_year(self, ontology: Ontology, fy: FinancialYear) -> tuple[str, ...]:
        """Per-financial-year attributes of this level with no known value for ``fy``."""
        return tuple(
            definition.key
            for definition in ontology
            if definition.level is self.level
            and definition.per_financial_year
            and (
                (record := self.value(definition.key, fy)) is None
                or record.state is not ValueState.KNOWN
            )
        )


def _same(previous: AttributeRecord, new: AttributeRecord) -> bool:
    return (
        previous.state is new.state
        and previous.value == new.value
        and previous.source is new.source
    )


def _require_chain(chain: Iterable[ProfileNode]) -> None:
    nodes = list(chain)
    expected_parent: BusinessId | None = None
    for node in nodes:
        if node.parent_id != expected_parent:
            raise InvalidHierarchyError(
                f"lineage is broken at {node.level.value} {node.key}: parent {node.parent_id} "
                f"expected {expected_parent}"
            )
        expected_parent = node.id
    if nodes and nodes[0].level is not AttributeLevel.ENTITY:
        raise InvalidHierarchyError("a lineage starts at the entity")


@dataclass(frozen=True, slots=True)
class ReviewTask:
    """A question for a person: an attribute the business says does not apply, or a per-year
    value to confirm when the financial year turns."""

    id: BusinessId
    tenant_id: TenantId
    node_id: BusinessId
    attribute_key: str
    reason: ReviewReason
    as_of_fy: FinancialYear | None
    open: bool
    created_at: datetime

    def __post_init__(self) -> None:
        require_instance(self.id, BusinessId, "id")
        require_instance(self.tenant_id, TenantId, "tenant_id")
        require_instance(self.node_id, BusinessId, "node_id")
        require_text(self.attribute_key, "attribute_key")
        require_instance(self.reason, ReviewReason, "reason")
        if self.as_of_fy is not None:
            require_instance(self.as_of_fy, FinancialYear, "as_of_fy")
        require_aware(self.created_at, "created_at")

    @property
    def dedupe_key(self) -> tuple[BusinessId, str, ReviewReason, str | None]:
        return (
            self.node_id,
            self.attribute_key,
            self.reason,
            None if self.as_of_fy is None else self.as_of_fy.label,
        )
