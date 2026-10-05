"""The impact of a change in the public API: ``GET /v1/changes/{rule_version_id}/impact``.

It sits outside the service's prefix, beside the rulebook's ``GET /v1/changes``, as a path of the
public API (tag ``public``) with the roles that read it as ``x-roles``: every member of the tenant
(``deps.Tenant``, which also lets a service with tenant:act read for the tenant it names).
"""

from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Query

from applicability_engine.api.deps import PUBLIC_ROUTE, Tenant, Wired
from applicability_engine.api.schemas import ChangeImpactOut, ImpactCursor
from applicability_engine.domain.impact import ImpactQuery
from domain_kernel.ids import BusinessId, RuleVersionId
from domain_kernel.predicates import Applicability
from py_common.pagination import Pagination, page_of
from py_common.problems import problem_responses

public_router = APIRouter(tags=["public", "changes"])

SCOPE: Final = "applicability-engine.change-impact"


@public_router.get(
    "/v1/changes/{rule_version_id}/impact",
    summary="What a change means for the tenant: each business's latest decision, by client",
    responses=problem_responses(401, 403, 422),
    openapi_extra=PUBLIC_ROUTE,
)
def read_change_impact(
    rule_version_id: UUID,
    tenant: Tenant,
    wired: Wired,
    page: Pagination,
    result: Annotated[
        Applicability | None,
        Query(
            description=(
                "Only the businesses whose latest decision has this result (applies: the "
                "affected clients); every business without"
            )
        ),
    ] = None,
) -> ChangeImpactOut:
    """For the change's rule version, each of the tenant's businesses with its latest decision
    of the version (the fan-out of its publication, a profile change since, or a reviewer's
    settlement): the result, confidence, whether it needs review, when it was decided and every
    predicate's outcome in words. The businesses stand under their client, the legal entity at
    the top of their lineage, so a CA firm sees each affected client with its registrations; a
    page holds ``limit`` clients, in entity order. ``counts`` covers every business of the tenant
    with a decision of the version, and ``fan_out`` says how far the version's fan-out got. A
    version the engine never decided for the tenant has no clients and zero counts."""
    after = page.after(SCOPE, ImpactCursor)
    impact = wired.read_change_impact.run(
        ImpactQuery(
            tenant_id=tenant,
            rule_version_id=RuleVersionId(rule_version_id),
            limit=page.limit + 1,
            result=result,
            after=None if after is None else BusinessId(after.entity_id),
        )
    )
    groups, next_cursor = page_of(
        impact.groups,
        page.limit,
        SCOPE,
        lambda group: ImpactCursor(entity_id=group.entity_id.value),
    )
    return ChangeImpactOut.of(impact, groups, next_cursor)
