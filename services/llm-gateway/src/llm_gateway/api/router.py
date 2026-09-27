"""Routes of the llm-gateway service. Business logic lives in the application use cases."""

from datetime import UTC, date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from domain_kernel.ids import TenantId
from llm_gateway.api.deps import Correlation, Gateway, Tenant
from llm_gateway.api.schemas import (
    MONTH_PATTERN,
    CompletionIn,
    CompletionOut,
    ModelRouteOut,
    PromptOut,
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
    responses=problem_responses(422, 429, 502, 503),
)
def completions(
    body: CompletionIn, tenant: Tenant, correlation_id: Correlation, gateway: Gateway
) -> CompletionOut:
    """Synchronous. No `Idempotency-Key` header yet; identical deterministic calls are cached."""
    outcome = gateway.complete.run(body.to_request(tenant), correlation_id=correlation_id)
    return CompletionOut.from_outcome(outcome, correlation_id=correlation_id)


@router.get(
    "/usage",
    summary="Spend against one monthly budget, by tenant or by feature",
    responses=problem_responses(422),
)
def usage(
    tenant: Tenant,
    gateway: Gateway,
    tenant_id: Annotated[
        UUID | None, Query(description="Defaults to the x-tenant-id header; empty means all")
    ] = None,
    feature: Annotated[Feature | None, Query(description="Empty means all features")] = None,
    month: Annotated[
        str | None,
        Query(pattern=MONTH_PATTERN, description="YYYY-MM in UTC; defaults to the current month"),
    ] = None,
) -> UsageOut:
    """Tenant budget when a tenant is given (a feature narrows the sum), else the feature budget."""
    resolved_tenant = TenantId(tenant_id) if tenant_id is not None else tenant
    report = gateway.usage.spent(
        tenant_id=resolved_tenant, feature=feature, month=_first_day_of(month)
    )
    return UsageOut.from_report(report)


@router.get("/models", summary="The routing table with overrides applied")
def models(gateway: Gateway) -> list[ModelRouteOut]:
    return [ModelRouteOut.from_route(route) for route in gateway.routing.routes()]


@router.get("/prompts", summary="Registered prompts")
def prompts(gateway: Gateway) -> list[PromptOut]:
    return [PromptOut.from_spec(spec) for spec in gateway.registry.list()]


def _first_day_of(month: str | None) -> date:
    if month is None:
        now = datetime.now(UTC)
        return date(now.year, now.month, 1)
    year, month_number = month.split("-")
    return date(int(year), int(month_number), 1)
