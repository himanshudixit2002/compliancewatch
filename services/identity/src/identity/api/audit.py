"""``GET /v1/identity/audit``: the audit trail, one page at a time, newest first.

Every service writes ``audit.event`` rows; identity reads them for people, in the scope their
roles give (``identity.application.audit.ReadAuditTrail``):

- owners, CA admins and compliance leads read their tenant's entries;
- analysts, reviewers and admins read the platform's entries (rows of no tenant: rule versions,
  entity reviews, relation candidates, review tasks, sources, raw documents, pipeline tasks,
  fan-out runs and holds, dry runs, service clients) and their own tenant's;
- staff, CA staff and services are refused (403).

A verified token's session is checked against the store, as on the user routes. Outside header
mode a request without a token is a 401; in header mode the anonymous caller reads the tenant the
header names, never the platform's entries. Filters: ``subject_type``, ``subject_id``,
``action``, ``from`` (inclusive) and ``to`` (exclusive). Pages are keyset pages on
(occurred_at, id), at most 200 entries; a cursor this route did not issue is a 422.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from domain_kernel.access import Principal, PrincipalKind
from domain_kernel.audit import MAX_ACTION_CHARS, MAX_SUBJECT_ID_CHARS, MAX_SUBJECT_TYPE_CHARS
from identity.api.audit_schemas import AuditEntryOut, AuditKeyset
from identity.api.deps import Tenant, Wired
from identity.domain.audit import AuditQuery
from py_common.auth.errors import AuthForbiddenError, AuthTokenRequiredError
from py_common.auth.fastapi import CurrentPrincipal, authenticator_of
from py_common.pagination import Page, Pagination, page_of
from py_common.problems import problem_responses

router = APIRouter(prefix="/v1/identity", tags=["identity"])

CURSOR_SCOPE = "identity.audit"


async def audit_reader(request: Request, principal: CurrentPrincipal) -> Principal:
    """A person; a service is refused, and outside header mode so is a request without a
    token."""
    if principal.kind is PrincipalKind.SERVICE:
        raise AuthForbiddenError("the audit trail answers for a person, not a service")
    if not principal.is_authenticated and authenticator_of(request).mode != "header":
        raise AuthTokenRequiredError(
            "Reading the audit trail needs an access token as Authorization: Bearer <token>"
        )
    return principal


AuditReader = Annotated[Principal, Depends(audit_reader)]


@router.get(
    "/audit",
    summary="The audit trail: who did what to which record, newest first",
    responses=problem_responses(401, 403, 422),
)
def read_audit_trail(
    principal: AuditReader,
    tenant: Tenant,
    wired: Wired,
    page: Pagination,
    subject_type: Annotated[
        str | None,
        Query(min_length=1, max_length=MAX_SUBJECT_TYPE_CHARS, description="user, rule_version"),
    ] = None,
    subject_id: Annotated[
        str | None, Query(min_length=1, max_length=MAX_SUBJECT_ID_CHARS, description="Its id")
    ] = None,
    action: Annotated[
        str | None,
        Query(min_length=1, max_length=MAX_ACTION_CHARS, description="Such as user.disabled"),
    ] = None,
    since: Annotated[
        datetime | None,
        Query(alias="from", description="Entries at or after this instant (with a zone)"),
    ] = None,
    until: Annotated[
        datetime | None,
        Query(alias="to", description="Entries before this instant (with a zone)"),
    ] = None,
) -> Page[AuditEntryOut]:
    """Owners, CA admins and compliance leads read their tenant's entries; analysts, reviewers
    and admins the platform's and their own tenant's. 403 for any other role or a service, 422
    for a cursor this route did not issue or a range whose from is not before its to."""
    after = page.after(CURSOR_SCOPE, AuditKeyset)
    query = AuditQuery(
        subject_type=subject_type,
        subject_id=subject_id,
        action=action,
        since=since,
        until=until,
        limit=page.limit,
        after=None if after is None else after.key(),
    )
    found = wired.read_audit_trail.run(principal, tenant, query)
    kept, cursor = page_of(found.entries, page.limit, CURSOR_SCOPE, AuditKeyset.of)
    return Page[AuditEntryOut](
        items=[AuditEntryOut.from_entry(entry) for entry in kept], next_cursor=cursor
    )
