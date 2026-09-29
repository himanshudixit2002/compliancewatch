"""The principal of the running request or job, and the log fields that name it.

``bind_principal`` sets ``current_principal`` and binds ``actor`` (``user:<uuid>``,
``service:<client>`` or ``anonymous``) into the structlog context, with ``tenant_id`` when the
principal belongs to a tenant, so every log line of the request names who acted.
``unbind_principal`` clears them. Worker loops that act for nobody bind their own actor label,
such as ``system:outbox-relay``, with ``bind_actor``.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Final

import structlog

from domain_kernel.access import ANONYMOUS, Principal

ACTOR_FIELD: Final = "actor"
TENANT_FIELD: Final = "tenant_id"

current_principal: ContextVar[Principal | None] = ContextVar("current_principal", default=None)
"""The principal bound for the running request or job; None outside one."""


def principal_or_anonymous() -> Principal:
    """The bound principal, or the anonymous one when none is bound."""
    return current_principal.get() or ANONYMOUS


def bind_actor(label: str) -> None:
    """Name who acts on every following log line of this context."""
    structlog.contextvars.bind_contextvars(**{ACTOR_FIELD: label})


def bind_principal(principal: Principal) -> None:
    """Make ``principal`` current and name it, and its tenant when it has one, in the logs."""
    current_principal.set(principal)
    fields = {ACTOR_FIELD: principal.actor_label}
    if principal.tenant_id is not None:
        fields[TENANT_FIELD] = str(principal.tenant_id)
    structlog.contextvars.bind_contextvars(**fields)


def unbind_principal(principal: Principal) -> None:
    """Undo ``bind_principal(principal)``: no principal is current and the log fields it bound
    are gone."""
    current_principal.set(None)
    fields = [ACTOR_FIELD]
    if principal.tenant_id is not None:
        fields.append(TENANT_FIELD)
    structlog.contextvars.unbind_contextvars(*fields)


@contextmanager
def principal_bound(principal: Principal) -> Iterator[Principal]:
    """``bind_principal`` for the body of a ``with`` block, then ``unbind_principal``."""
    bind_principal(principal)
    try:
        yield principal
    finally:
        unbind_principal(principal)
