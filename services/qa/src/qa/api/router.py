"""Routes of the qa service. Business logic lives in application use cases.

A question is asked for the request's tenant (``deps.Tenant``): the tenant a user's access token
names, the one a service with tenant:act names in ``x-tenant-id``, or without a token the header's.

The ask route is served twice, with the same handler: under the service's prefix,
``POST /v1/qa/ask``, which the web app calls, and as the public API's ``POST /v1/qa`` (tag
``public``), with the roles that may call it as ``x-roles``. Asking creates nothing, so neither
takes an Idempotency-Key: a retry asks again.
"""

from typing import Final

from fastapi import APIRouter

from domain_kernel.errors import InvariantViolationError
from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import BusinessId
from py_common.problems import problem_responses
from qa.api.deps import PUBLIC_ROUTE, QuestionId, Tenant, Wired
from qa.api.schemas import AskIn, AskOut
from qa.application.context import AskRequest
from qa.domain.errors import QuestionInvalidError

router = APIRouter(prefix="/v1/qa", tags=["qa"])
public_router = APIRouter(prefix="/v1/qa", tags=["public", "questions"])

ASK_SUMMARY: Final = "Answer a question with verified citations, or say it is not covered"
ASK_PROBLEMS: Final = problem_responses(401, 403, 404, 422, 429, 503)


@router.get("/ping")
async def ping() -> dict[str, str]:
    return {"service": "qa", "status": "pong"}


@public_router.post("", summary=ASK_SUMMARY, responses=ASK_PROBLEMS, openapi_extra=PUBLIC_ROUTE)
@router.post("/ask", summary=ASK_SUMMARY, responses=ASK_PROBLEMS)
def ask(body: AskIn, tenant: Tenant, wired: Wired, question_id: QuestionId) -> AskOut:
    """The layers answer in turn, cheapest first: the business's own obligations for "when is
    my GSTR-3B due" and "what is due this month" (no model call), then the knowledge graph
    when it is on for the tenant, then a search of the clauses in force. ``outcome`` is
    ``answered`` with at least one citation whose quote was checked against its clause, or
    ``not_covered`` with a fixed sentence and the ``reason``. ``layers`` lists every layer that
    ran. 404 when ``business_node_id`` names no profile node of the tenant; 429 with the
    gateway's ``Retry-After`` when the model budget is used up; 503 when a service the answer
    needs did not answer."""
    try:
        fy = None if body.fy is None else FinancialYear.parse(body.fy)
    except InvariantViolationError as exc:
        raise QuestionInvalidError(exc.detail) from exc
    request = AskRequest(
        tenant=tenant,
        question=body.question,
        as_of=body.as_of or wired.today(),
        question_id=question_id,
        business=None if body.business_node_id is None else BusinessId(body.business_node_id),
        fy=fy,
    )
    return AskOut.from_result(wired.ask.run(request))
