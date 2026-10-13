"""The regulatory team's read across tenants: ``GET /v1/profile/admin/attribute-usage``.

How many profile nodes hold each attribute in each state (known, unsure, not_applicable), over
every tenant, for the ontology browser: counts only, never a value, a node or a tenant. In
Postgres the counts come from ``profile.attribute_usage()``, a SECURITY DEFINER function owned
by the NOLOGIN role ``cw_profile_directory`` (``infra/dev/postgres/roles.sql``), since
row-level security shows this service's own role one tenant at a time. The caller is an analyst,
a reviewer or an admin a verified token names (403 for a tenant's member or a service); outside
header mode a request without a token is a 401. The composition classes the route ``admin``: the
public listener serves it in token mode only.
"""

from fastapi import APIRouter

from profile_service.api.deps import RegulatoryReader, Wired
from profile_service.api.schemas import AttributeUsageOut, AttributeUsagesOut
from py_common.problems import problem_responses

router = APIRouter(prefix="/v1/profile/admin", tags=["profile"])


@router.get(
    "/attribute-usage",
    summary="How many profiles hold each attribute, in which state, across every tenant",
    responses=problem_responses(401, 403),
)
def attribute_usage(principal: RegulatoryReader, wired: Wired) -> AttributeUsagesOut:
    return AttributeUsagesOut(
        items=[AttributeUsageOut.from_usage(entry) for entry in wired.attribute_usage.usage()]
    )
