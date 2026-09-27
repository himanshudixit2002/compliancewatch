"""Request and response bodies of the profile API."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from domain_kernel.financial_year import FinancialYear
from domain_kernel.ontology import AttributeSource
from domain_kernel.profiles import ProfileSnapshot
from profile_service.domain.model import (
    AttributeChange,
    AttributeRecord,
    ProfileNode,
    ReviewTask,
    ValueState,
)

FY_PATTERN = r"^[0-9]{4}-[0-9]{2}$"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EntityIn(Strict):
    pan: str = Field(min_length=10, max_length=12, description="PAN, any case or spacing")
    name: str = Field(min_length=1, max_length=200)


class RegistrationIn(Strict):
    gstin: str = Field(min_length=15, max_length=17, description="GSTIN, any case or spacing")
    name: str = Field(min_length=1, max_length=200)
    entity_name: str = Field(default="", max_length=200, description="Used when the entity is new")


class LocationIn(Strict):
    registration_id: UUID
    label: str = Field(
        min_length=1, max_length=80, description="Stable label such as a branch code"
    )
    name: str = Field(min_length=1, max_length=200)


class AttributeChangeIn(Strict):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    value: Any = None
    state: ValueState = ValueState.KNOWN
    as_of_fy: str | None = Field(default=None, pattern=FY_PATTERN, description="2025-26")
    source: AttributeSource = AttributeSource.USER_INPUT

    def to_change(self) -> AttributeChange:
        return AttributeChange(
            key=self.key,
            value=self.value,
            state=self.state,
            as_of_fy=None if self.as_of_fy is None else FinancialYear.parse(self.as_of_fy),
            source=self.source,
        )


class AttributesIn(Strict):
    changes: list[AttributeChangeIn] = Field(min_length=1, max_length=100)
    source: Literal["user_input", "gstin_lookup", "partner_api", "import"] = "user_input"
    changed_by: UUID | None = None


class AttributeOut(BaseModel):
    key: str
    state: ValueState
    value: Any = None
    as_of_fy: str | None
    source: AttributeSource
    updated_at: datetime | None

    @classmethod
    def from_record(cls, record: AttributeRecord) -> "AttributeOut":
        value = record.value
        if isinstance(value, frozenset):
            value = sorted(value)
        return cls(
            key=record.key,
            state=record.state,
            value=value,
            as_of_fy=None if record.as_of_fy is None else record.as_of_fy.label,
            source=record.source,
            updated_at=record.updated_at,
        )


class NodeOut(BaseModel):
    id: UUID
    level: str
    key: str
    name: str
    parent_id: UUID | None
    version: int
    created: bool = False
    attributes: list[AttributeOut]

    @classmethod
    def from_node(cls, node: ProfileNode, *, created: bool = False) -> "NodeOut":
        return cls(
            id=node.id.value,
            level=node.level.value,
            key=node.key,
            name=node.name,
            parent_id=None if node.parent_id is None else node.parent_id.value,
            version=node.version,
            created=created,
            attributes=[AttributeOut.from_record(r) for r in node.attributes.values()],
        )


class SetResultOut(BaseModel):
    node: NodeOut
    changed: list[str]
    review_tasks: list[UUID]


class SnapshotOut(BaseModel):
    business_id: UUID
    tenant_id: UUID
    version: int
    level: str | None
    lineage: list[UUID]
    as_of_fy: str | None
    attributes: dict[str, Any]

    @classmethod
    def from_snapshot(cls, snapshot: ProfileSnapshot) -> "SnapshotOut":
        attributes = {
            key: sorted(value) if isinstance(value, frozenset) else value
            for key, value in snapshot.attributes.items()
        }
        return cls(
            business_id=snapshot.business_id.value,
            tenant_id=snapshot.tenant_id.value,
            version=snapshot.version,
            level=None if snapshot.level is None else snapshot.level.value,
            lineage=[item.value for item in snapshot.lineage],
            as_of_fy=None if snapshot.as_of_fy is None else snapshot.as_of_fy.label,
            attributes=attributes,
        )


class NextQuestionOut(BaseModel):
    node_id: UUID
    as_of_fy: str
    attribute: str | None
    definition: str | None
    type: str | None
    allowed_values: list[str]


class ReviewTaskOut(BaseModel):
    id: UUID
    node_id: UUID
    attribute_key: str
    reason: str
    as_of_fy: str | None
    open: bool
    created_at: datetime

    @classmethod
    def from_task(cls, task: ReviewTask) -> "ReviewTaskOut":
        return cls(
            id=task.id.value,
            node_id=task.node_id.value,
            attribute_key=task.attribute_key,
            reason=task.reason.value,
            as_of_fy=None if task.as_of_fy is None else task.as_of_fy.label,
            open=task.open,
            created_at=task.created_at,
        )
