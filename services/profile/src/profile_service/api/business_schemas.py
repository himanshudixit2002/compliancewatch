"""Request and response bodies of the business API (``/v1/businesses``)."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import BusinessId
from domain_kernel.ontology import AttributeDefinition, AttributeSource, Ontology, OntologyWording
from profile_service.api.schemas import (
    FY_PATTERN,
    AttributeOut,
    NodeOut,
    PrefillOut,
    Strict,
)
from profile_service.application.businesses import (
    Answer,
    Business,
    BusinessCreated,
    RegistrationAdded,
)
from profile_service.domain.model import AttributeChange, ValueState
from profile_service.domain.onboarding import Checklist, ChecklistItem, ItemState

ATTRIBUTE_KEY_PATTERN = r"^[a-z][a-z0-9_]*$"


class AnswerIn(Strict):
    key: str = Field(pattern=ATTRIBUTE_KEY_PATTERN, max_length=64, description="Ontology key")
    value: Any = Field(default=None, description="The value; absent for unsure or not_applicable")
    state: ValueState = ValueState.KNOWN
    as_of_fy: str | None = Field(
        default=None,
        pattern=FY_PATTERN,
        description="2025-26; required for an attribute stated per financial year",
    )

    def answer(self) -> Answer:
        change = AttributeChange(
            key=self.key,
            value=self.value,
            state=self.state,
            as_of_fy=None if self.as_of_fy is None else FinancialYear.parse(self.as_of_fy),
            source=AttributeSource.USER_INPUT,
        )
        return Answer(change, self.target())

    def target(self) -> BusinessId | None:
        """The node the answer names. A new business has no node ids to name yet: its
        registration-level answers go to the GSTIN's registration."""
        return None


class BusinessChangeIn(AnswerIn):
    node_id: UUID | None = Field(
        default=None,
        description=(
            "The registration or location the answer is for, needed when the business has "
            "several; without it the attribute's level picks the node"
        ),
    )

    def target(self) -> BusinessId | None:
        return None if self.node_id is None else BusinessId(self.node_id)


class BusinessIn(Strict):
    name: str = Field(min_length=1, max_length=200, description="The name the business goes by")
    gstin: str | None = Field(
        default=None,
        min_length=15,
        max_length=17,
        description=(
            "GSTIN, any case or spacing. Its PAN makes the business, and the registration is "
            "pre-filled from the GSTIN and the GSTIN lookup"
        ),
    )
    pan: str | None = Field(
        default=None,
        min_length=10,
        max_length=12,
        description="PAN, any case or spacing; enough on its own when there is no GSTIN yet",
    )
    registration_name: str = Field(
        default="",
        max_length=200,
        description="Name of the registration; the business name when empty",
    )
    answers: list[AnswerIn] = Field(
        default_factory=list, max_length=100, description="First answers, stored with the business"
    )


class BusinessPatchIn(Strict):
    name: str | None = Field(default=None, min_length=1, max_length=200, description="Rename")
    changes: list[BusinessChangeIn] = Field(
        default_factory=list,
        max_length=100,
        description="Answers to store; all of them or none are stored",
    )


class RegistrationAddIn(Strict):
    gstin: str = Field(
        min_length=15,
        max_length=17,
        description="GSTIN, any case or spacing; it must carry the business's PAN",
    )
    name: str = Field(
        default="",
        max_length=200,
        description="Name of the registration; the business name when empty",
    )


class BusinessOut(BaseModel):
    id: UUID = Field(description="The business id: the node id of its legal entity")
    name: str
    pan: str
    version: int
    created_at: datetime
    updated_at: datetime
    attributes: list[AttributeOut] = Field(description="Values stored on the legal entity")
    registrations: list[NodeOut] = Field(description="Its GSTIN registrations, oldest first")

    @classmethod
    def from_business(cls, business: Business) -> "BusinessOut":
        entity = business.entity
        return cls(
            id=entity.id.value,
            name=entity.name,
            pan=entity.key,
            version=entity.version,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            attributes=[AttributeOut.from_record(r) for r in entity.attributes.values()],
            registrations=[NodeOut.from_node(node) for node in business.registrations],
        )


class BusinessSummaryOut(BaseModel):
    id: UUID
    name: str
    pan: str
    gstins: list[str]
    updated_at: datetime

    @classmethod
    def from_business(cls, business: Business) -> "BusinessSummaryOut":
        return cls(
            id=business.id.value,
            name=business.entity.name,
            pan=business.entity.key,
            gstins=[node.key for node in business.registrations],
            updated_at=business.entity.updated_at,
        )


class OptionOut(BaseModel):
    value: str
    label: str


def options_of(definition: AttributeDefinition, wording: OntologyWording) -> list[OptionOut]:
    """The allowed values of an attribute with their labels; the raw value when unlabelled."""
    return [
        OptionOut(value=value, label=wording.label(definition.key, value))
        for value in definition.allowed_values
    ]


def bound(value: int | Decimal | None) -> int | float | None:
    """A minimum or maximum as JSON can carry it."""
    return float(value) if isinstance(value, Decimal) else value


class QuestionOut(BaseModel):
    node_id: UUID = Field(description="The entity or registration the answer is stored on")
    level: str
    key: str
    state: ItemState = Field(description="missing or unsure")
    per_financial_year: bool
    as_of_fy: str | None = Field(description="The financial year a per-year answer is for")
    type: str
    question: str
    help: str
    options: list[OptionOut] = Field(description="Allowed values with their labels, in order")
    min: int | float | None = None
    max: int | float | None = None

    @classmethod
    def of(
        cls,
        item: ChecklistItem,
        definition: AttributeDefinition,
        wording: OntologyWording,
        fy: FinancialYear,
    ) -> "QuestionOut":
        worded = wording.for_key(item.key)
        return cls(
            node_id=item.node_id.value,
            level=item.level.value,
            key=item.key,
            state=item.state,
            per_financial_year=item.per_financial_year,
            as_of_fy=fy.label if item.per_financial_year else None,
            type=definition.type.value,
            question="" if worded is None else worded.question,
            help="" if worded is None else worded.help,
            options=options_of(definition, wording),
            min=bound(definition.minimum),
            max=bound(definition.maximum),
        )


class OnboardingOut(BaseModel):
    business_id: UUID
    as_of_fy: str = Field(description="The financial year per-year questions are asked for")
    answered: int
    total: int
    complete: bool
    next: QuestionOut | None = Field(description="The one question to ask now; null when complete")

    @classmethod
    def from_checklist(
        cls,
        business_id: BusinessId,
        checklist: Checklist,
        ontology: Ontology,
        wording: OntologyWording,
    ) -> "OnboardingOut":
        item = checklist.next
        return cls(
            business_id=business_id.value,
            as_of_fy=checklist.as_of_fy.label,
            answered=checklist.answered,
            total=checklist.total,
            complete=checklist.complete,
            next=None
            if item is None
            else QuestionOut.of(item, ontology.require(item.key), wording, checklist.as_of_fy),
        )


class BusinessCreatedOut(BaseModel):
    business: BusinessOut
    created: bool = Field(description="False when the tenant already had this business")
    prefill: PrefillOut | None = Field(description="What the GSTIN filled in; null without one")
    onboarding: OnboardingOut

    @classmethod
    def from_created(
        cls, created: BusinessCreated, ontology: Ontology, wording: OntologyWording
    ) -> "BusinessCreatedOut":
        return cls(
            business=BusinessOut.from_business(created.business),
            created=created.created,
            prefill=None if created.prefill is None else PrefillOut.from_result(created.prefill),
            onboarding=OnboardingOut.from_checklist(
                created.business.id, created.checklist, ontology, wording
            ),
        )


class RegistrationCreatedOut(BaseModel):
    business: BusinessOut
    registration: NodeOut
    created: bool = Field(description="False when the business already held this GSTIN")
    prefill: PrefillOut

    @classmethod
    def from_added(cls, added: RegistrationAdded) -> "RegistrationCreatedOut":
        return cls(
            business=BusinessOut.from_business(added.business),
            registration=NodeOut.from_node(added.registration, created=added.created),
            created=added.created,
            prefill=PrefillOut.from_result(added.prefill),
        )
