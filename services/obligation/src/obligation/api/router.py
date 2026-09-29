"""Routes of the obligation service. Business logic lives in application use cases."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from domain_kernel.ids import BusinessId, RuleVersionId
from obligation.api.deps import Tenant, Wired
from obligation.api.schemas import ObligationOut
from obligation.application.queries import ObligationQuery
from obligation.domain.model import DueWindow
from py_common.problems import problem_responses

router = APIRouter(prefix="/v1/obligation", tags=["obligation"])


@router.get("/ping")
async def ping() -> dict[str, str]:
    return {"service": "obligation", "status": "pong"}


@router.get(
    "/obligations",
    summary="A business's obligations, due date first, optionally inside a window of days",
    responses=problem_responses(401, 422),
)
def list_obligations(
    tenant: Tenant,
    wired: Wired,
    business_id: Annotated[UUID, Query(description="The profile node the obligations are for")],
    due_from: Annotated[
        date | None, Query(description="First due day, in India (inclusive)")
    ] = None,
    due_to: Annotated[
        date | None, Query(description="Last due day, in India (inclusive); at most 366 days")
    ] = None,
    rule_version_id: Annotated[
        UUID | None, Query(description="Only obligations of this rule version")
    ] = None,
) -> list[ObligationOut]:
    found = wired.list_obligations.run(
        ObligationQuery(
            tenant_id=tenant,
            business_id=BusinessId(business_id),
            window=DueWindow(due_from, due_to),
            rule_version_id=None if rule_version_id is None else RuleVersionId(rule_version_id),
        )
    )
    return [ObligationOut.from_obligation(obligation) for obligation in found]
