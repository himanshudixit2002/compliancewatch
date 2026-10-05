"""Routes of the obligation service. Business logic lives in application use cases.

Every route acts for the request's tenant: the tenant a user's access token names, the one a
service with tenant:act names in ``x-tenant-id``, or without a token the header's. Reading is for
the tenant's members and for services acting for it (``deps.Tenant``); changing an obligation is
for its members alone (``deps.Writer``). Every change takes an ``Idempotency-Key``: a retry with
the same key and body gets the first response back for 24 hours instead of a second change.

The tracking routes are served twice, with the same handlers: under the service's prefix,
``/v1/obligation/obligations/{obligation_id}``, which the web app calls, and as part of the public
API (tag ``public``), ``/v1/obligations/{obligation_id}``, with the roles that may call them as
``x-roles``.
"""

from datetime import date
from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Query, status
from fastapi.responses import JSONResponse

from domain_kernel.ids import BusinessId, ObligationId, RuleVersionId, UserId
from obligation.api.deps import PUBLIC_ROUTE, Tenant, Wired, Writer
from obligation.api.schemas import (
    AssigneeIn,
    CommentIn,
    CommentOut,
    ObligationDetailOut,
    ObligationOut,
    StatusIn,
)
from obligation.application.queries import ObligationQuery
from obligation.application.tracking import Assignment, NewComment, StatusChange
from obligation.domain.model import DueWindow
from py_common.idempotency.fastapi import IDEMPOTENCY_RESPONSES, IdempotencyKey, run_idempotent
from py_common.problems import problem_responses

router = APIRouter(prefix="/v1/obligation", tags=["obligation"])
public_router = APIRouter(prefix="/v1/obligations", tags=["public", "obligations"])

ONE: Final = "/obligations/{obligation_id}"
"""One obligation under the service's prefix; the public API's path is ``/{obligation_id}``."""
READ_PROBLEMS: Final = problem_responses(401, 403, 404, 422, 503)
STATUS_PROBLEMS: Final = {**problem_responses(401, 403, 404, 409, 422), **IDEMPOTENCY_RESPONSES}
ASSIGN_PROBLEMS: Final = {
    **problem_responses(401, 403, 404, 409, 422, 503),
    **IDEMPOTENCY_RESPONSES,
}
COMMENT_PROBLEMS: Final = {**problem_responses(401, 403, 404, 422), **IDEMPOTENCY_RESPONSES}


@router.get("/ping")
async def ping() -> dict[str, str]:
    return {"service": "obligation", "status": "pong"}


@router.get(
    "/obligations",
    summary="A business's obligations, due date first, optionally inside a window of days",
    responses=problem_responses(401, 403, 422),
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


@public_router.get(
    "/{obligation_id}",
    summary="One obligation with its rule's review, citations, history and comments",
    responses=READ_PROBLEMS,
    openapi_extra=PUBLIC_ROUTE,
)
@router.get(
    ONE,
    summary="One obligation with its rule's review, citations, history and comments",
    responses=READ_PROBLEMS,
)
def read_obligation(obligation_id: UUID, tenant: Tenant, wired: Wired) -> ObligationDetailOut:
    """``rule_version`` holds what the obligation service keeps of the rule version: its title
    and rule key, ``reviewed`` false while the seed rule is not reviewed, and the approvers of
    the round it was published from with when (the reviewed-by line). ``citations`` are the
    verified quotes of the clause it comes from, ``history`` every change oldest first, and
    ``comments`` oldest first. An obligation made before its service kept rule versions is read
    from the rulebook once; 503 when the rulebook cannot answer then. 404 when the tenant has no
    such obligation."""
    detail = wired.read_obligation.run(tenant, ObligationId(obligation_id))
    return ObligationDetailOut.from_detail(detail)


@public_router.post(
    "/{obligation_id}/status",
    summary="Start, complete or waive an obligation",
    response_model=ObligationOut,
    responses=STATUS_PROBLEMS,
    openapi_extra=PUBLIC_ROUTE,
)
@router.post(
    f"{ONE}/status",
    summary="Start, complete or waive an obligation",
    response_model=ObligationOut,
    responses=STATUS_PROBLEMS,
)
def change_status(
    obligation_id: UUID, body: StatusIn, acting: Writer, key: IdempotencyKey, wired: Wired
) -> JSONResponse:
    """``start`` moves an open obligation to in progress. ``complete`` closes it as done and
    ``waive`` as waived, which needs a reason of at least ten characters; both publish
    obligation.closed, which sends no message. Every action appends to the history and writes an
    audit entry (obligation.status.start, .complete or .waive) with the reason. 404 when the
    tenant has no such obligation, 409 when it is closed, 422 when the action does not fit its
    status (starting one in progress)."""

    def produce() -> ObligationOut:
        changed = wired.change_status.run(
            StatusChange(acting, ObligationId(obligation_id), body.action, body.reason)
        )
        return ObligationOut.from_obligation(changed)

    return run_idempotent(wired.idempotency, acting.tenant_id, key, status.HTTP_200_OK, produce)


@public_router.put(
    "/{obligation_id}/assignee",
    summary="Give an obligation to a user of the tenant, or to nobody",
    response_model=ObligationOut,
    responses=ASSIGN_PROBLEMS,
    openapi_extra=PUBLIC_ROUTE,
)
@router.put(
    f"{ONE}/assignee",
    summary="Give an obligation to a user of the tenant, or to nobody",
    response_model=ObligationOut,
    responses=ASSIGN_PROBLEMS,
)
def assign(
    obligation_id: UUID, body: AssigneeIn, acting: Writer, key: IdempotencyKey, wired: Wired
) -> JSONResponse:
    """With a verified caller the identity service is asked first whether the assignee is an
    active user of the tenant: 422 when not, 503 when it cannot say. Without a token (header
    mode, or dual mode without one) nobody can be checked, and the assignee is kept as named.
    Naming the assignee it has changes nothing; any other change appends assigned or unassigned
    to the history and writes an audit entry, obligation.assign. 404 when the tenant has no such
    obligation, 409 when it is closed."""

    def produce() -> ObligationOut:
        assignee = None if body.assignee_id is None else UserId(body.assignee_id)
        changed = wired.assign.run(Assignment(acting, ObligationId(obligation_id), assignee))
        return ObligationOut.from_obligation(changed)

    return run_idempotent(wired.idempotency, acting.tenant_id, key, status.HTTP_200_OK, produce)


@public_router.post(
    "/{obligation_id}/comments",
    summary="Comment on an obligation",
    status_code=status.HTTP_201_CREATED,
    response_model=CommentOut,
    responses=COMMENT_PROBLEMS,
    openapi_extra=PUBLIC_ROUTE,
)
@router.post(
    f"{ONE}/comments",
    summary="Comment on an obligation",
    status_code=status.HTTP_201_CREATED,
    response_model=CommentOut,
    responses=COMMENT_PROBLEMS,
)
def add_comment(
    obligation_id: UUID, body: CommentIn, acting: Writer, key: IdempotencyKey, wired: Wired
) -> JSONResponse:
    """The author is the user a verified token names, labelled with their roles; without a token
    it is nobody, labelled system:obligation. A closed obligation takes comments too. Comments are
    never changed or deleted. The audit entry, obligation.comment, names the comment, not its
    text. 404 when the tenant has no such obligation."""

    def produce() -> CommentOut:
        comment = wired.add_comment.run(NewComment(acting, ObligationId(obligation_id), body.body))
        return CommentOut.from_comment(comment)

    return run_idempotent(
        wired.idempotency, acting.tenant_id, key, status.HTTP_201_CREATED, produce
    )
