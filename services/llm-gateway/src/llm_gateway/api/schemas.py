"""Request and response bodies of the llm-gateway API. Money is decimal text, never a float."""

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field

from domain_kernel.ids import TenantId
from domain_kernel.llm import CompletionRequest
from llm_gateway.application.complete import CompletionOutcome
from llm_gateway.application.embed import EmbeddingOutcome
from llm_gateway.application.usage import UsageReport
from llm_gateway.domain.budgets import BudgetScope
from llm_gateway.domain.embeddings import (
    MAX_EMBEDDING_INPUT_CHARS,
    MAX_EMBEDDING_INPUTS,
    EmbeddingRequest,
)
from llm_gateway.domain.features import Feature
from llm_gateway.domain.ledger import MAX_MODEL_ID
from llm_gateway.domain.prompts import PROMPT_NAME, PROMPT_VERSION, PromptSpec
from llm_gateway.domain.routing import MODEL_ID, Route

PROMPT_REF_PATTERN = f"^{PROMPT_NAME.pattern}@{PROMPT_VERSION.pattern}$"
"""``name@version`` exactly as the domain accepts it, so the API refuses what it would refuse."""
MODEL_ID_PATTERN = f"^{MODEL_ID.pattern}$"
"""``creator/model`` as the routing table accepts it; the length bound is the ledger column's."""
MONTH_PATTERN = r"^[0-9]{4}-(0[1-9]|1[0-2])$"
RATIO_PLACES = Decimal("0.000001")


def money(value: Decimal) -> str:
    """Plain decimal text without an exponent: ``0.0012``, not ``1.2E-3``."""
    return format(value, "f")


def ratio(value: Decimal) -> str:
    """A share of a budget as plain decimal text with six places."""
    return money(value.quantize(RATIO_PLACES, rounding=ROUND_HALF_UP))


class CompletionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature: Feature
    prompt: str = Field(
        pattern=PROMPT_REF_PATTERN,
        description="Registered prompt as name@version",
        examples=["smoke.echo@1"],
    )
    system: str = ""
    user: str = Field(min_length=1)
    model: str | None = Field(
        default=None,
        pattern=MODEL_ID_PATTERN,
        max_length=MAX_MODEL_ID,
        description="Model id override as creator/model; the routing table decides when absent",
        examples=["fake/echo"],
    )
    temperature: float = Field(default=0.0, ge=0, le=2)
    max_tokens: int = Field(default=1024, ge=1, le=32768)
    json_schema: dict[str, object] | None = None
    metadata: dict[str, str] | None = Field(
        default=None, description="Trace tags, for example a document id"
    )

    def to_request(self, tenant_id: TenantId | None) -> CompletionRequest:
        return CompletionRequest(
            feature=self.feature.value,
            prompt_version=self.prompt,
            system=self.system,
            user=self.user,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            json_schema=self.json_schema,
            tenant_id=tenant_id,
            metadata=self.metadata or {},
        )


class CompletionOut(BaseModel):
    text: str
    model_requested: str
    model_served: str
    provider: str
    input_tokens: int
    output_tokens: int
    cached: bool
    cost_usd: str | None
    cost_inr: str
    cost_source: str
    latency_ms: int
    trace_id: str
    generation_id: str
    correlation_id: str
    pii_masked: dict[str, int] = Field(
        description="How many identifiers of each kind were masked before the call"
    )

    @classmethod
    def from_outcome(cls, outcome: CompletionOutcome, *, correlation_id: str) -> Self:
        return cls(
            text=outcome.text,
            model_requested=outcome.model_requested,
            model_served=outcome.model_served,
            provider=outcome.provider,
            input_tokens=outcome.input_tokens,
            output_tokens=outcome.output_tokens,
            cached=outcome.cached,
            cost_usd=None if outcome.cost_usd is None else money(outcome.cost_usd),
            cost_inr=money(outcome.cost_inr),
            cost_source=outcome.cost_source.value,
            latency_ms=outcome.latency_ms,
            trace_id=outcome.trace_id,
            generation_id=outcome.generation_id,
            correlation_id=correlation_id,
            pii_masked=dict(outcome.pii_counts),
        )


EmbeddingInput = Annotated[str, Field(min_length=1, max_length=MAX_EMBEDDING_INPUT_CHARS)]


class EmbeddingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature: Literal["retrieval"]
    inputs: list[EmbeddingInput] = Field(
        min_length=1,
        max_length=MAX_EMBEDDING_INPUTS,
        description="Texts to embed, one vector each, in order; masked before they leave",
    )
    model: str | None = Field(
        default=None,
        pattern=MODEL_ID_PATTERN,
        max_length=MAX_MODEL_ID,
        description=(
            "Model id override as creator/model, for a re-embed; the routing table decides when "
            "absent. There is never a fallback"
        ),
        examples=["voyage/voyage-3.5-lite"],
    )
    metadata: dict[str, str] | None = Field(
        default=None, description="Trace tags, for example a document id"
    )

    def to_request(self, tenant_id: TenantId | None) -> EmbeddingRequest:
        return EmbeddingRequest(
            feature=self.feature,
            inputs=tuple(self.inputs),
            model=self.model,
            tenant_id=tenant_id,
            metadata=self.metadata or {},
        )


class EmbeddingOut(BaseModel):
    model_requested: str
    model_served: str = Field(
        description="Store it with every vector: only same-model vectors compare"
    )
    provider: str
    dims: int
    vectors: list[list[float]] = Field(description="One vector per input, in input order")
    input_tokens: int
    cost_usd: str | None
    cost_inr: str
    cost_source: str
    latency_ms: int
    trace_id: str
    generation_id: str
    correlation_id: str
    pii_masked: dict[str, int] = Field(
        description="How many identifiers of each kind were masked before the call"
    )

    @classmethod
    def from_outcome(cls, outcome: EmbeddingOutcome, *, correlation_id: str) -> Self:
        return cls(
            model_requested=outcome.model_requested,
            model_served=outcome.model_served,
            provider=outcome.provider,
            dims=outcome.dims,
            vectors=[list(vector) for vector in outcome.vectors],
            input_tokens=outcome.input_tokens,
            cost_usd=None if outcome.cost_usd is None else money(outcome.cost_usd),
            cost_inr=money(outcome.cost_inr),
            cost_source=outcome.cost_source.value,
            latency_ms=outcome.latency_ms,
            trace_id=outcome.trace_id,
            generation_id=outcome.generation_id,
            correlation_id=correlation_id,
            pii_masked=dict(outcome.pii_counts),
        )


class UsageOut(BaseModel):
    scope: BudgetScope
    key: str = Field(description="The tenant id or the feature name the budget belongs to")
    month: str = Field(pattern=MONTH_PATTERN)
    spent_inr: str
    budget_inr: str
    ratio: str = Field(description="spent_inr over budget_inr, decimal text")
    alarmed: bool
    resets_at: datetime

    @classmethod
    def from_report(cls, report: UsageReport) -> Self:
        return cls(
            scope=report.scope,
            key=report.key,
            month=report.month.strftime("%Y-%m"),
            spent_inr=money(report.spent_inr),
            budget_inr=money(report.budget_inr),
            ratio=ratio(report.ratio),
            alarmed=report.alarmed,
            resets_at=report.resets_at,
        )


class ModelRouteOut(BaseModel):
    feature: Feature
    primary: str
    fallback: str | None
    only: list[str]
    has: list[str]
    sort: str | None
    reasoning_effort: str | None
    timeout_seconds: float
    source: Literal["default", "override"]

    @classmethod
    def from_route(cls, route: Route) -> Self:
        return cls(
            feature=route.feature,
            primary=route.primary,
            fallback=route.fallback,
            only=list(route.only),
            has=list(route.has),
            sort=route.sort,
            reasoning_effort=route.reasoning_effort,
            timeout_seconds=route.timeout_seconds,
            source=route.source,
        )


class PromptOut(BaseModel):
    name: str
    version: str
    owner: str
    eval_cases: int
    sha256: str | None
    description: str

    @classmethod
    def from_spec(cls, spec: PromptSpec) -> Self:
        return cls(
            name=spec.name,
            version=spec.version,
            owner=spec.owner,
            eval_cases=spec.eval_cases,
            sha256=spec.sha256,
            description=spec.description,
        )
