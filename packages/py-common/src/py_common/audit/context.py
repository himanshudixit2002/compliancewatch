"""Who acts, and for which request: the actor and the correlation id of an audit entry.

``audit_actor(service, principal)`` turns the verified principal of a request into the kernel's
``AuditActor``: a user, labelled with the roles they hold, or a service client. Any other caller
is the system itself, ``system:<service>``: the anonymous principal of ``header`` mode, and work
no request started, such as a consumer or a sweep. Without ``principal`` it reads the one
``py_common.auth`` bound for the request (``current_principal``).

``current_correlation_id()`` is the correlation id ``RequestContextMiddleware`` bound for the
request: the ``x-request-id`` it reused, or the one it minted. It is read from the log context,
where the middleware binds it, so this module loads no web framework. None outside a request, or
when the bound value does not have the shape an audit entry keeps.
"""

from typing import Final

import structlog

from domain_kernel.access import Principal, PrincipalKind
from domain_kernel.audit import CORRELATION_ID_PATTERN, AuditActor
from py_common.auth.context import principal_or_anonymous

CORRELATION_FIELD: Final = "correlation_id"
"""The log context field ``py_common.request_context`` binds the request's correlation id to."""


def audit_actor(service: str, principal: Principal | None = None) -> AuditActor:
    """The actor of an audit entry: ``principal``'s user or service client, else the system as
    ``system:<service>``. ``principal`` defaults to the request's bound principal."""
    caller = principal_or_anonymous() if principal is None else principal
    user_id = caller.user_id
    if user_id is not None:
        return AuditActor.user(user_id, caller.roles)
    if caller.kind is PrincipalKind.SERVICE:
        return AuditActor.service(caller.subject)
    return AuditActor.system(service)


def current_correlation_id() -> str | None:
    """The running request's correlation id, or None."""
    value = structlog.contextvars.get_contextvars().get(CORRELATION_FIELD)
    if isinstance(value, str) and CORRELATION_ID_PATTERN.fullmatch(value):
        return value
    return None
