"""What identity holds of a tenant's deletion: ``GET /v1/identity/erasures/{tenant_id}``.

The erasure consumer of every other service (``py_common.erasure``) asks it before erasing,
and erases only when the ``tenant.deletion.requested`` it received is the one identity last sent
for the tenant's open deletion request, the tenant is being deleted (or erased already) and is
not the internal tenant. The answer holds ids, the tenant's status and whether it is the
internal tenant: nothing of the tenant's data.

A service with ``erasure:verify``; a person's token is refused, and outside header mode so is a
request without a token. Served on the internal listener only (``cw_mvp.exposure``).
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from domain_kernel.access import Principal, PrincipalKind, Scope
from domain_kernel.ids import TenantId
from identity.api.deps import Wired
from identity.api.schemas import ErasureCheckOut
from identity.domain.errors import TenantNotFoundError
from py_common.auth.errors import AuthForbiddenError, AuthTokenRequiredError
from py_common.auth.fastapi import authenticator_of, require_roles
from py_common.problems import problem_responses

router = APIRouter(prefix="/v1/identity", tags=["identity"])

_verifiers = require_roles(scopes={Scope.ERASURE_VERIFY})


async def erasure_verifier(
    request: Request, principal: Annotated[Principal, Depends(_verifiers)]
) -> Principal:
    """A service with erasure:verify; a person is refused. Only header mode lets the anonymous
    caller through, as on the other service routes."""
    if principal.kind is PrincipalKind.USER:  # pragma: no cover - require_roles refuses it
        raise AuthForbiddenError("an erasure is checked by a service, not a person")
    if not principal.is_authenticated and authenticator_of(request).mode != "header":
        raise AuthTokenRequiredError(
            "Checking an erasure needs a service's access token as Authorization: Bearer <token>"
        )
    return principal


Verifier = Annotated[Principal, Depends(erasure_verifier)]


@router.get(
    "/erasures/{tenant_id}",
    summary="What identity holds of a tenant's deletion, checked before any service erases it",
    responses=problem_responses(401, 403, 404),
)
def check_erasure(tenant_id: UUID, principal: Verifier, wired: Wired) -> ErasureCheckOut:
    """404 identity-tenant-not-found for a tenant identity does not hold: the consumer then
    refuses the event. ``deletion_event_id`` is null when the tenant has no open deletion
    request."""
    check = wired.check_erasure.run(TenantId(tenant_id))
    if check.tenant_status is None:
        raise TenantNotFoundError()
    return ErasureCheckOut.from_check(check)
