"""Request and response bodies of the ask route."""

from datetime import date
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from qa.application.ask import AskResult
from qa.application.context import MAX_QUESTION_CHARS
from qa.domain.answer import Layer, LayerResult, Outcome, Reason
from qa.domain.plan_schema import plan_to_mapping

FY_PATTERN = r"^[0-9]{4}-[0-9]{2}$"


class AskIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    as_of: date | None = Field(
        default=None, description="The date the question is about; today in India when absent"
    )
    business_node_id: UUID | None = Field(
        default=None,
        description="The profile node the question is about; its obligations are the business's",
    )
    fy: str | None = Field(
        default=None,
        pattern=FY_PATTERN,
        description="Financial year of the profile, 2025-26; the year of as_of when absent",
    )


class CitationOut(BaseModel):
    clause_ref: str
    document_id: UUID
    quote: str = Field(description="Verbatim from the clause, checked before it is returned")


class LayerOut(BaseModel):
    layer: Layer
    result: LayerResult
    reason: Reason | None


class AskOut(BaseModel):
    outcome: Outcome
    answer: str = Field(description="A fixed sentence when the outcome is not_covered")
    citations: list[CitationOut]
    layer: Layer = Field(description="The layer that decided")
    layers: list[LayerOut] = Field(description="Every layer that ran, in order")
    plan: dict[str, Any] | None = Field(
        description=(
            "The plan the KAG layer validated, in the planner's JSON form, even when a later "
            "layer answered; null when there was none"
        )
    )
    reason: Reason | None = Field(description="Why the question is not covered")
    as_of: date

    @classmethod
    def from_result(cls, result: AskResult) -> Self:
        return cls(
            outcome=result.outcome,
            answer=result.answer,
            citations=[
                CitationOut(
                    clause_ref=citation.clause_ref,
                    document_id=citation.document_id.value,
                    quote=citation.quote,
                )
                for citation in result.citations
            ],
            layer=result.layer,
            layers=[
                LayerOut(layer=record.layer, result=record.result, reason=record.reason)
                for record in result.layers
            ],
            plan=None if result.plan is None else plan_to_mapping(result.plan),
            reason=result.reason,
            as_of=result.as_of,
        )
