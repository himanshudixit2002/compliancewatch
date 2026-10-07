"""Routes of the obligation service. Business logic lives in application use cases.

Every route acts for the request's tenant: the tenant a user's access token names, the one a
service with tenant:act names in ``x-tenant-id``, or without a token the header's. Reading is for
the tenant's members and for services acting for it (``deps.Tenant``); changing an obligation is
for its members alone (``deps.Writer``). Every change takes an ``Idempotency-Key``: a retry with
the same key and body gets the first response back for 24 hours instead of a second change.

The tracking routes are served twice, with the same handlers: under the service's prefix,
``/v1/obligation/obligations/{obligation_id}``, which the web app calls, and as part of the public
API (tag ``public``), ``/v1/obligations/{obligation_id}``, with the roles that may call them as
``x-roles``. The public API also lists a business's obligations a page at a time,
``/v1/businesses/{business_id}/obligations``, beside the profile service's business routes.

``/v1/obligation/data-export`` is the service's part of a tenant's data export, which identity
assembles: for the tenant's admins and for a service with data:export (``deps.ExportTenant``).
"""

from datetime import date
from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Query, status
from fastapi.responses import JSONResponse

from domain_kernel.ids import BusinessId, ObligationId, RuleVersionId, UserId
from domain_kernel.status import ObligationStatus
from obligation.api.deps import PUBLIC_ROUTE, ExportTenant, Tenant, Wired, Writer
from obligation.api.schemas import (
    AssigneeIn,
    BusinessObligationCursor,
    BusinessObligationOut,
    CommentIn,
    CommentOut,
    DataExportOut,
    ObligationDetailOut,
    ObligationOut,
    StatusIn,
)
from obligation.application.queries import (
    BusinessObligationsQuery,
    ListedObligation,
    ObligationQuery,
)
from obligation.application.tracking import Assignment, NewComment, StatusChange
from obligation.domain.model import DueWindow
from obligation.domain.repository import ListingAfter
from py_common.idempotency.fastapi import IDEMPOTENCY_RESPONSES, IdempotencyKey, run_idempotent
from py_common.pagination import Page, Pagination, page_of
from py_common.problems import problem_responses

router = APIRouter(prefix="/v1/obligation", tags=["obligation"])
public_router = APIRouter(prefix="/v1/obligations", tags=["public", "obligations"])
business_router = APIRouter(prefix="/v1/businesses", tags=["public", "obligations"])

ONE: Final = "/obligations/{obligation_id}"
"""One obligation under the service's prefix; the public API's path is ``/{obligation_id}``."""
READ_PROBLEMS: Final = problem_responses(401, 403, 404, 422, 503)
STATUS_PROBLEMS: Final = {**problem_responses(401, 403, 404, 409, 422), **IDEMPOTENCY_RESPONSES}
ASSIGN_PROBLEMS: Final = {
    **problem_responses(401, 403, 404, 409, 422, 503),
    **IDEMPOTENCY_RESPONSES,
}
COMMENT_PROBLEMS: Final = {**problem_responses(401, 403, 404, 422), **IDEMPOTENCY_RESPONSES}
LIST_PROBLEMS: Final = problem_responses(401, 403, 404, 422, 503)
LIST_SCOPE: Final = "obligation.business-obligations"


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


@router.get(
    "/data-export",
    summary="Everything the service holds of the tenant, for the tenant's data export",
    responses=problem_responses(401, 403),
)
def data_export(tenant: ExportTenant, wired: Wired) -> DataExportOut:
    """The tenant's obligations in any status (``obligations``), the change log of each
    (``changes``) and the comments on them (``comments``), each oldest first and then by id,
    every section present and empty when there is nothing. For a user with owner or ca_admin, and
    for a service with data:export naming the tenant in ``x-tenant-id`` (with tenant:act);
    anyone else is a 403, and no tenant a 401."""
    return DataExportOut.from_export(wired.export_tenant_data.run(tenant))


@business_router.get(
    "/{business_id}/obligations",
    summary="A business's obligations by due date, a page at a time",
    responses=LIST_PROBLEMS,
    openapi_extra=PUBLIC_ROUTE,
)
def list_business_obligations(
    business_id: UUID,
    tenant: Tenant,
    wired: Wired,
    page: Pagination,
    statuses: Annotated[
        list[ObligationStatus] | None,
        Query(
            alias="status",
            description="Keep the obligations in this status; repeat it for several",
        ),
    ] = None,
    due_from: Annotated[
        date | None, Query(description="First due day, in India (inclusive)")
    ] = None,
    due_to: Annotated[
        date | None,
        Query(description="Last due day, in India (inclusive); at most 366 days after due_from"),
    ] = None,
) -> Page[BusinessObligationOut]:
    """``business_id`` is any profile node of the tenant: a business (its legal entity, the id
    of ``/v1/businesses``), one of its registrations or a location. The list holds the
    obligations kept for that node; a GSTIN's returns are kept for its registration. Items come
    by due date, the ones without a date last, then by id, each with what the service keeps of
    its rule version (the title, the rule key, whether the seed rule is reviewed, the approvers)
    and the verified citations of its clause. With ``due_from`` or ``due_to`` only obligations
    with a due date in that window count, and a window longer than 366 days is a 422. 404 when
    the tenant has no such node, 503 when the profile service cannot say whether it has."""
    window = DueWindow(due_from, due_to)
    after = page.after(LIST_SCOPE, BusinessObligationCursor)
    found = wired.list_business_obligations.run(
        BusinessObligationsQuery(
            tenant_id=tenant,
            business_id=BusinessId(business_id),
            limit=page.limit + 1,
            window=window,
            statuses=frozenset(statuses or ()),
            after=None if after is None else ListingAfter(after.due_at, ObligationId(after.id)),
        )
    )
    items, next_cursor = page_of(found, page.limit, LIST_SCOPE, _cursor)
    return Page[BusinessObligationOut](
        items=[BusinessObligationOut.from_listed(listed) for listed in items],
        next_cursor=next_cursor,
    )


def _cursor(listed: ListedObligation) -> BusinessObligationCursor:
    obligation = listed.obligation
    return BusinessObligationCursor(due_at=obligation.due_at, id=obligation.id.value)


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
