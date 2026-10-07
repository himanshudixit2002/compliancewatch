"""Routes of the llm-gateway service. Business logic lives in the application use cases.

Who may call each route with an access token is in ``api.deps``: a service with llm:call for the
model calls, and also a user with a regulatory role for usage, the routing table and the prompt
registry."""

from datetime import UTC, date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from domain_kernel.access import PrincipalKind
from domain_kernel.ids import TenantId
from llm_gateway.api.deps import Correlation, Gateway, ModelCaller, Operator, Tenant
from llm_gateway.api.schemas import (
    MONTH_PATTERN,
    CompletionIn,
    CompletionOut,
    EmbeddingIn,
    EmbeddingOut,
    ModelRouteOut,
    PromptOut,
    ResidencyOut,
    UsageOut,
)
from llm_gateway.domain.features import Feature
from py_common.problems import problem_responses

router = APIRouter(prefix="/v1/llm-gateway", tags=["llm-gateway"])


@router.get("/ping", summary="Router liveness")
async def ping() -> dict[str, str]:
    return {"service": "llm-gateway", "status": "pong"}


@router.post(
    "/completions",
    summary="Run one completion through routing, cache, budget, provider and ledger",
    responses=problem_responses(401, 403, 422, 429, 502, 503),
)
def completions(
    body: CompletionIn,
    caller: ModelCaller,
    tenant: Tenant,
    correlation_id: Correlation,
    gateway: Gateway,
) -> CompletionOut:
    """Synchronous. No `Idempotency-Key` header yet; identical deterministic calls are cached."""
    outcome = gateway.complete.run(body.to_request(tenant), correlation_id=correlation_id)
    return CompletionOut.from_outcome(outcome, correlation_id=correlation_id)


@router.post(
    "/embeddings",
    summary="Embed texts for retrieval through routing, budget, provider and ledger",
    responses=problem_responses(401, 403, 422, 429, 502, 503),
)
def embeddings(
    body: EmbeddingIn,
    caller: ModelCaller,
    tenant: Tenant,
    correlation_id: Correlation,
    gateway: Gateway,
) -> EmbeddingOut:
    """Synchronous and uncached. One model, no fallback: store `model_served` with the vectors."""
    outcome = gateway.embed.run(body.to_request(tenant), correlation_id=correlation_id)
    return EmbeddingOut.from_outcome(outcome, correlation_id=correlation_id)


@router.get(
    "/usage",
    summary="Spend against one monthly budget, by tenant or by feature",
    responses=problem_responses(401, 403, 422),
)
def usage(
    caller: Operator,
    tenant: Tenant,
    gateway: Gateway,
    tenant_id: Annotated[
        UUID | None,
        Query(
            description=(
                "Defaults to the x-tenant-id header (not to a signed-in user's own tenant); "
                "empty means all"
            )
        ),
    ] = None,
    feature: Annotated[Feature | None, Query(description="Empty means all features")] = None,
    month: Annotated[
        str | None,
        Query(pattern=MONTH_PATTERN, description="YYYY-MM in UTC; defaults to the current month"),
    ] = None,
) -> UsageOut:
    """Tenant budget when a tenant is given (a feature narrows the sum), else the feature budget.
    A signed-in operator reads any tenant's spend by ``tenant_id``; their own tenant is the
    internal one, so it is no default."""
    default = None if caller.kind is PrincipalKind.USER else tenant
    resolved_tenant = TenantId(tenant_id) if tenant_id is not None else default
    report = gateway.usage.spent(
        tenant_id=resolved_tenant, feature=feature, month=_first_day_of(month)
    )
    return UsageOut.from_report(report)


@router.get(
    "/models",
    summary="The routing table with overrides applied, and the residency policy",
    responses=problem_responses(401, 403),
)
def models(caller: Operator, gateway: Gateway) -> list[ModelRouteOut]:
    """Every route carries the gateway's residency policy (`CW_LLM_RESIDENCY`): under
    `india_only` a call to any real model is refused with 503 `llm-residency-unavailable`."""
    residency = ResidencyOut.from_policy(gateway.residency)
    return [
        ModelRouteOut.from_route(route, residency=residency) for route in gateway.routing.routes()
    ]


@router.get("/prompts", summary="Registered prompts", responses=problem_responses(401, 403))
def prompts(caller: Operator, gateway: Gateway) -> list[PromptOut]:
    return [PromptOut.from_spec(spec) for spec in gateway.registry.list()]


def _first_day_of(month: str | None) -> date:
    if month is None:
        now = datetime.now(UTC)
        return date(now.year, now.month, 1)
    year, month_number = month.split("-")
    return date(int(year), int(month_number), 1)
