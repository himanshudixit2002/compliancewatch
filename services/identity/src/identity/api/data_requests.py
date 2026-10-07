"""A tenant's data requests: ``/v1/identity/data-requests``.

- ``POST`` makes a request: ``kind`` export or deletion, and an optional ``reason``. The
  tenant's owner or CA admin makes it for their tenant; the regulatory team's admin makes one
  for the tenant ``tenant_id`` names, as support, with a reason. It is due 30 days later. A
  deletion turns the tenant ``deletion_requested`` at once: nobody signs in to it any more
  (403 identity-tenant-deleting), identity's own routes refuse its tokens but for reading its
  data requests and audit trail, and every service is asked to erase it. The other services take
  a token issued before the request until it expires, and answer 410 tenant-erased once they
  have erased the tenant. The internal tenant is never erased (422
  identity-tenant-not-erasable).
- ``GET`` lists the tenant's requests, newest first, and ``GET /{request_id}`` reads one, each
  with the services that have not answered it yet: those an export has not held, or those that
  have not erased the tenant. The owner of a tenant being deleted may still read them.
- ``GET /{request_id}/export`` downloads the export as a JSON attachment, assembled now from
  identity's data and each service's (``identity.application.data_requests``). A service that
  does not answer leaves the request in progress and is named in the bundle; the download itself
  still answers 200.

Owners and CA admins only, for their own tenant (staff, CA staff, compliance leads and services
get 403); the admin only makes support requests. Outside header mode a request without a token is
a 401; in header mode the header names the tenant, as on every tenant route.
"""

from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import StreamingResponse

from domain_kernel.access import TENANT_ADMIN_ROLES, Principal, Role
from domain_kernel.ids import TenantId
from identity.api.deps import Tenant, Wired
from identity.api.schemas import DataRequestIn, DataRequestOut, DataRequestsOut
from identity.domain.data_requests import DataRequest, DataRequestId, DataRequestKind
from identity.wiring import Wiring
from py_common.auth.errors import AuthForbiddenError, AuthTokenRequiredError
from py_common.auth.fastapi import authenticator_of, require_roles
from py_common.problems import problem_responses

router = APIRouter(prefix="/v1/identity", tags=["identity"])

EXPORT_MEDIA_TYPE: Final = "application/json"

_makers = require_roles(TENANT_ADMIN_ROLES, Role.ADMIN)
_readers = require_roles(TENANT_ADMIN_ROLES)


def _token_outside_header_mode(request: Request, principal: Principal) -> Principal:
    if not principal.is_authenticated and authenticator_of(request).mode != "header":
        raise AuthTokenRequiredError(
            "Data requests need an owner's or CA admin's access token as "
            "Authorization: Bearer <token>"
        )
    return principal


async def request_maker(
    request: Request, principal: Annotated[Principal, Depends(_makers)]
) -> Principal:
    """An owner, a CA admin, or the regulatory team's admin (support requests only)."""
    return _token_outside_header_mode(request, principal)


async def request_reader(
    request: Request, principal: Annotated[Principal, Depends(_readers)]
) -> Principal:
    """An owner or a CA admin of the tenant."""
    return _token_outside_header_mode(request, principal)


Maker = Annotated[Principal, Depends(request_maker)]
Reader = Annotated[Principal, Depends(request_reader)]


@router.post(
    "/data-requests",
    summary="Ask for a copy of the tenant's data or its deletion; it is due within 30 days",
    status_code=status.HTTP_201_CREATED,
    responses=problem_responses(401, 403, 404, 422),
)
def make_data_request(
    body: DataRequestIn, principal: Maker, tenant: Tenant, wired: Wired
) -> DataRequestOut:
    """``tenant_id`` is for the regulatory team's admin recording a support request for that
    tenant (a reason is then required); anyone else leaves it out or names their own tenant. A
    deletion shuts the tenant out of identity at once: 403 identity-tenant-deleting on its
    sign-ins and on its later requests to identity but reading its data requests and its audit
    trail. The other services take a token issued before it until the token expires (ten minutes
    by default), and answer 410 tenant-erased once each has erased the tenant."""
    for_tenant = None if body.tenant_id is None else TenantId(body.tenant_id)
    if for_tenant is not None and for_tenant != tenant:
        if not principal.has_role(Role.ADMIN):
            raise AuthForbiddenError("only the regulatory team's admin names another tenant")
    elif not principal.has_role(*TENANT_ADMIN_ROLES) and principal.is_authenticated:
        raise AuthForbiddenError("data requests are made by the tenant's owner or CA admin")
    use = (
        wired.request_deletion
        if DataRequestKind(body.kind) is DataRequestKind.DELETION
        else wired.request_export
    )
    made = use.run(principal, tenant, reason=body.reason, for_tenant=for_tenant)
    return _out(made, wired)


def _out(request: DataRequest, wired: Wiring) -> DataRequestOut:
    """The request with the services it waits for: an export's sources, or the services that
    erase."""
    services = (
        wired.settings.erasure_services
        if request.is_deletion
        else wired.export_tenant_data.services
    )
    return DataRequestOut.from_request(request, services)


@router.get(
    "/data-requests",
    summary="The tenant's data requests, newest first",
    responses=problem_responses(401, 403, 404),
)
def list_data_requests(principal: Reader, tenant: Tenant, wired: Wired) -> DataRequestsOut:
    found = wired.list_data_requests.run(principal, tenant)
    return DataRequestsOut(items=[_out(item, wired) for item in found])


@router.get(
    "/data-requests/{request_id}",
    summary="One data request, with the services that have not answered it yet",
    responses=problem_responses(401, 403, 404),
)
def read_data_request(
    request_id: UUID, principal: Reader, tenant: Tenant, wired: Wired
) -> DataRequestOut:
    found = wired.read_data_request.run(principal, tenant, DataRequestId(request_id))
    return _out(found, wired)


@router.get(
    "/data-requests/{request_id}/export",
    summary="Download the tenant's data as a JSON file, assembled now",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": (
                "The export: one entry per service with its generated_at, or status "
                "unavailable and why; services_pending names those still owed"
            ),
            "content": {EXPORT_MEDIA_TYPE: {"schema": {"type": "object"}}},
        },
        **problem_responses(401, 403, 404, 409),
    },
)
def download_export(
    request_id: UUID, principal: Reader, tenant: Tenant, wired: Wired
) -> StreamingResponse:
    """409 identity-export-not-ready for a request that is not an export. The bundle is
    assembled before the answer starts (a refusal is still a problem) and then written a service
    at a time. The file name is built from the request id alone."""
    bundle = wired.export_tenant_data.run(principal, tenant, DataRequestId(request_id))
    filename = f"compliancewatch-export-{UUID(str(bundle.request.id))}.json"
    return StreamingResponse(
        bundle.chunks(),
        media_type=EXPORT_MEDIA_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
