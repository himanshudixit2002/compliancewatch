"""Request-scoped dependencies: the tenant from the header (required here), the wiring, and
the question id every model call of the request is tagged with."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID, uuid4

import structlog
from fastapi import Depends, Header, Request

from domain_kernel.ids import TenantId
from py_common.request_context import correlation_id_of
from qa.domain.errors import QaTenantRequiredError
from qa.wiring import Wiring


async def tenant_id_from_header(
    x_tenant_id: Annotated[
        UUID | None,
        Header(description="Tenant UUID; required until the identity service issues tokens"),
    ] = None,
) -> AsyncIterator[TenantId]:
    """Answers read tenant data (profiles, obligations), so the header is required: a missing
    one is a 401 problem."""
    if x_tenant_id is None:
        raise QaTenantRequiredError()
    tenant_id = TenantId(x_tenant_id)
    structlog.contextvars.bind_contextvars(tenant_id=str(tenant_id))
    try:
        yield tenant_id
    finally:
        structlog.contextvars.unbind_contextvars("tenant_id")


def wiring(request: Request) -> Wiring:
    wired: Wiring = request.app.state.wiring
    return wired


def question_id(request: Request) -> str:
    """The request's ``x-request-id`` (or the one the middleware minted)."""
    return correlation_id_of(request) or uuid4().hex


Tenant = Annotated[TenantId, Depends(tenant_id_from_header)]
Wired = Annotated[Wiring, Depends(wiring)]
QuestionId = Annotated[str, Depends(question_id)]
