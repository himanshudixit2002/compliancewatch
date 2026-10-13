"""The regulatory team's reads of other tenants: ``/v1/identity/admin/tenants``.

- ``GET /admin/tenants?q&limit&cursor``: every tenant a page at a time, in the order of (name,
  id): id, kind, name, status, when it was created, the plan key and status of its newest
  subscription (null without one) and its user counts; never a person's details. ``q`` keeps the
  tenants whose name contains it (any case) or whose id is it.
- ``GET /admin/tenants/{tenant_id}``: one tenant's summary; 404 for an id identity does not know.
- ``GET /admin/tenants/{tenant_id}/users``: the tenant's users with their roles. It needs a
  reason in the ``x-reason`` header (a GET carries no body, and a reason in the URL would reach
  every access log); without one it is a 422. Every read is written to the tenant's audit trail
  as ``tenant.users_read`` with the reason, the tenant id and the admin, and no personal data
  (``identity.application.admin``).

The caller is an admin of the internal tenant a verified token names (403 for anyone else, a
customer tenant's owner included). Outside header mode a request without a token is a 401; in
header mode the anonymous caller passes, as on every route. The composition classes the three
routes ``admin``: the public listener serves them in token mode only.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request

from domain_kernel.access import Principal, Role
from domain_kernel.ids import TenantId
from identity.api.deps import Wired
from identity.api.schemas import AdminTenantKeyset, AdminTenantOut, UserOut, UsersOut
from identity.domain.data_requests import MAX_REASON_CHARS
from identity.domain.directory import MAX_QUERY_CHARS
from py_common.auth.errors import AuthTokenRequiredError
from py_common.auth.fastapi import authenticator_of, require_roles
from py_common.pagination import Page, Pagination, page_of
from py_common.problems import problem_responses

router = APIRouter(prefix="/v1/identity/admin", tags=["identity"])

CURSOR_SCOPE = "identity.admin.tenants"
REASON_HEADER = "x-reason"
"""Why a tenant's users are read, as the admin said; the trail keeps it verbatim."""

admin_role = require_roles(Role.ADMIN)


async def internal_admin(
    request: Request, principal: Annotated[Principal, Depends(admin_role)]
) -> Principal:
    """An admin a verified token names; outside header mode a request without a token is a
    401. The use cases check the session and the internal tenant."""
    if not principal.is_authenticated and authenticator_of(request).mode != "header":
        raise AuthTokenRequiredError(
            "The admin reads need an admin's access token as Authorization: Bearer <token>"
        )
    return principal


InternalAdmin = Annotated[Principal, Depends(internal_admin)]
Reason = Annotated[
    str,
    Header(
        alias=REASON_HEADER,
        min_length=1,
        max_length=MAX_REASON_CHARS,
        description=(
            "Why the users are read (a support case, a security review); written to the "
            "tenant's audit trail with the read. Required: a read without it is a 422."
        ),
    ),
]


@router.get(
    "/tenants",
    summary="Every tenant with its plan and user counts, a page at a time (internal admins)",
    responses=problem_responses(401, 403, 422),
)
def list_tenants(
    principal: InternalAdmin,
    wired: Wired,
    page: Pagination,
    q: Annotated[
        str,
        Query(
            max_length=MAX_QUERY_CHARS,
            description="Keep the tenants whose name contains this, any case, or whose id is it",
        ),
    ] = "",
) -> Page[AdminTenantOut]:
    after = page.after(CURSOR_SCOPE, AdminTenantKeyset)
    found = wired.list_tenants.run(
        principal,
        query=q,
        after=None if after is None else TenantId(after.id),
        limit=page.limit + 1,
    )
    kept, cursor = page_of(found, page.limit, CURSOR_SCOPE, AdminTenantKeyset.of)
    return Page[AdminTenantOut](
        items=[AdminTenantOut.from_summary(summary) for summary in kept], next_cursor=cursor
    )


@router.get(
    "/tenants/{tenant_id}",
    summary="One tenant with its plan and user counts (internal admins)",
    responses=problem_responses(401, 403, 404),
)
def read_tenant(tenant_id: UUID, principal: InternalAdmin, wired: Wired) -> AdminTenantOut:
    return AdminTenantOut.from_summary(wired.read_tenant.run(principal, TenantId(tenant_id)))


@router.get(
    "/tenants/{tenant_id}/users",
    summary="A tenant's users with their roles, for a reason that is audited (internal admins)",
    responses=problem_responses(401, 403, 404, 422),
)
def read_tenant_users(
    tenant_id: UUID, reason: Reason, principal: InternalAdmin, wired: Wired
) -> UsersOut:
    """The read is written to the tenant's audit trail as ``tenant.users_read`` with the
    reason; 422 without the ``x-reason`` header, 404 for a tenant identity does not know."""
    users = wired.read_tenant_users.run(principal, TenantId(tenant_id), reason=reason)
    return UsersOut(items=[UserOut.from_user(user) for user in users])
