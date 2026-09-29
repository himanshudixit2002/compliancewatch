"""Routes of the qa service. Business logic lives in application use cases."""

from fastapi import APIRouter

from domain_kernel.errors import InvariantViolationError
from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import BusinessId
from py_common.problems import problem_responses
from qa.api.deps import QuestionId, Tenant, Wired
from qa.api.schemas import AskIn, AskOut
from qa.application.context import AskRequest
from qa.domain.errors import QuestionInvalidError

router = APIRouter(prefix="/v1/qa", tags=["qa"])


@router.get("/ping")
async def ping() -> dict[str, str]:
    return {"service": "qa", "status": "pong"}


@router.post(
    "/ask",
    summary="Answer a question with verified citations, or say it is not covered",
    responses=problem_responses(401, 404, 422, 429, 503),
)
def ask(body: AskIn, tenant: Tenant, wired: Wired, question_id: QuestionId) -> AskOut:
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
