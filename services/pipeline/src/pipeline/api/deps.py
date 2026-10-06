"""Request-scoped dependencies: the wiring, and who may read and change the sources.

The routes are the regulatory team's (composition class admin), the way the rulebook's analyst
routes are. The caller comes from ``py_common.auth.fastapi`` by ``CW_AUTH_MODE``:

- ``SourceRead`` (the sources, their documents, a document and its stored bytes): a user with a
  regulatory role (analyst, reviewer or admin) a token names; a service or a tenant's member is a
  403. Without a token (``header`` mode, or ``dual`` mode without one) the reads stay open, as
  the rulebook's do.
- ``SourceWrite`` (adding and editing a source, starting a crawl): an admin a token names, or,
  in ``header`` and ``dual`` mode and without a bearer, the shared write token
  (``CW_RULEBOOK_WRITE_TOKEN``, the pipeline's copy of the rulebook's) in ``x-cw-write-token``.
  Unset, it is a 503 ``pipeline-writes-disabled`` in ``header`` mode and a 401 asking for a token
  in ``dual`` mode; a missing or wrong one is a 401, compared in constant time. ``token`` mode
  takes the bearer alone.

A write names its actor and gives a reason (at least ten characters). With a user's token the
audit entry names that user with the roles they hold, and the body's ``actor_id`` is ignored;
with the shared token the entry names the ``actor_id`` the body asserts, as the rulebook's
analyst steps do, since nobody was verified.
"""

from typing import Annotated, Final
from uuid import UUID

from fastapi import Depends, Request

from domain_kernel.access import REGULATORY_ROLES, Principal, Role
from domain_kernel.audit import AuditActor
from domain_kernel.ids import UserId
from pipeline.domain.errors import WritesDisabledError, WriteTokenInvalidError
from pipeline.wiring import Wiring
from py_common.audit import audit_actor
from py_common.auth.fastapi import require_roles, shared_token_or_roles

SERVICE_NAME: Final = "pipeline"
WRITE_TOKEN_HEADER: Final = "x-cw-write-token"


def wiring(request: Request) -> Wiring:
    wired: Wiring = request.app.state.wiring
    return wired


Wired = Annotated[Wiring, Depends(wiring)]

source_read = require_roles(REGULATORY_ROLES)
source_write = shared_token_or_roles(
    "rulebook_write_token",
    WRITE_TOKEN_HEADER,
    [Role.ADMIN],
    disabled_error=WritesDisabledError,
    invalid_error=WriteTokenInvalidError,
    description=(
        "The shared write token (CW_RULEBOOK_WRITE_TOKEN), accepted when CW_AUTH_MODE is header "
        "or dual and the request carries no bearer token; a bearer needs the admin role"
    ),
)

SourceRead = Depends(source_read)
"""For the reads: ``dependencies=[SourceRead]``."""
SourceWrite = Annotated[Principal, Depends(source_write)]


def admin_actor(principal: Principal, offered: UUID) -> AuditActor:
    """Who the audit entry names: the verified caller, else the ``actor_id`` the body
    asserts."""
    if principal.is_authenticated:
        return audit_actor(SERVICE_NAME, principal)
    return AuditActor.user(UserId(offered))
