"""A tenant's data requests: ``/v1/identity/data-requests``.

- ``POST`` makes a request: ``kind`` export (a deletion is a 422 until the erasure cascade
  exists) and an optional ``reason``. The tenant's owner or CA admin makes it for their tenant;
  the regulatory team's admin makes one for the tenant ``tenant_id`` names, as support, with a
  reason. It is due 30 days later.
- ``GET`` lists the tenant's requests, newest first, and ``GET /{request_id}`` reads one, each
  with the services that have not answered its export yet.
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
from fastapi.responses import JSONResponse

from domain_kernel.access import TENANT_ADMIN_ROLES, Principal, Role
from domain_kernel.ids import TenantId
from identity.api.deps import Tenant, Wired
from identity.api.schemas import DataRequestIn, DataRequestOut, DataRequestsOut
from identity.domain.data_requests import DataRequestId, DataRequestKind
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
    summary="Ask for a copy of the tenant's data; it is due within 30 days",
    status_code=status.HTTP_201_CREATED,
    responses=problem_responses(401, 403, 404, 422),
)
def make_data_request(
    body: DataRequestIn, principal: Maker, tenant: Tenant, wired: Wired
) -> DataRequestOut:
    """``tenant_id`` is for the regulatory team's admin recording a support request for that
    tenant (a reason is then required); anyone else leaves it out or names their own tenant."""
    for_tenant = None if body.tenant_id is None else TenantId(body.tenant_id)
    if for_tenant is not None and for_tenant != tenant:
        if not principal.has_role(Role.ADMIN):
            raise AuthForbiddenError("only the regulatory team's admin names another tenant")
    elif not principal.has_role(*TENANT_ADMIN_ROLES) and principal.is_authenticated:
        raise AuthForbiddenError("data requests are made by the tenant's owner or CA admin")
    made = wired.request_export.run(
        principal,
        tenant,
        DataRequestKind(body.kind),
        reason=body.reason,
        for_tenant=for_tenant,
    )
    return DataRequestOut.from_request(made, wired.export_tenant_data.services)


@router.get(
    "/data-requests",
    summary="The tenant's data requests, newest first",
    responses=problem_responses(401, 403, 404),
)
def list_data_requests(principal: Reader, tenant: Tenant, wired: Wired) -> DataRequestsOut:
    services = wired.export_tenant_data.services
    found = wired.list_data_requests.run(principal, tenant)
    return DataRequestsOut(items=[DataRequestOut.from_request(item, services) for item in found])


@router.get(
    "/data-requests/{request_id}",
    summary="One data request, with the services that have not answered it yet",
    responses=problem_responses(401, 403, 404),
)
def read_data_request(
    request_id: UUID, principal: Reader, tenant: Tenant, wired: Wired
) -> DataRequestOut:
    found = wired.read_data_request.run(principal, tenant, DataRequestId(request_id))
    return DataRequestOut.from_request(found, wired.export_tenant_data.services)


@router.get(
    "/data-requests/{request_id}/export",
    summary="Download the tenant's data as a JSON file, assembled now",
    response_class=JSONResponse,
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
) -> JSONResponse:
    """409 identity-export-not-ready for a request that is not an export. The file name is
    built from the request id alone."""
    bundle = wired.export_tenant_data.run(principal, tenant, DataRequestId(request_id))
    filename = f"compliancewatch-export-{UUID(str(bundle.request.id))}.json"
    return JSONResponse(
        bundle.document(),
        media_type=EXPORT_MEDIA_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
