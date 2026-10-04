"""Request-scoped context: the correlation id every log line and error response carries."""

import re
import uuid

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "x-request-id"
REQUEST_ID_SHAPE = re.compile(r"[A-Za-z0-9._-]{1,64}")
"""What a client value must look like to be reused: 1 to 64 of ``A-Z a-z 0-9 . _ -``.

Anything else (longer, spaces, other punctuation) is not echoed; a fresh id is minted instead,
so the correlation id fits the ledger column and never carries an arbitrary client string.
"""
_STATE_KEY = "correlation_id"


class RequestContextMiddleware:
    """Pure ASGI middleware: reuse or mint an ``x-request-id``, bind it as ``correlation_id``.

    A client value is reused only when it matches ``REQUEST_ID_SHAPE``. The id is also kept in
    ``scope["state"]`` so that handlers running outside this middleware (Starlette's 500 handler)
    can still read it. An id already in ``scope["state"]`` wins over both, and a response that
    already carries ``x-request-id`` gets no second one, so an app mounted inside another that
    runs this middleware too (several services in one process) keeps the outer id and sends
    the header once.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        state = scope.setdefault("state", {})
        correlation_id = (
            _reusable(state.get(_STATE_KEY))
            or _reusable(Headers(scope=scope).get(REQUEST_ID_HEADER))
            or uuid.uuid4().hex
        )
        state[_STATE_KEY] = correlation_id

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                if REQUEST_ID_HEADER not in headers:
                    headers.append(REQUEST_ID_HEADER, correlation_id)
            await send(message)

        with structlog.contextvars.bound_contextvars(correlation_id=correlation_id):
            await self.app(scope, receive, send_with_request_id)


def _reusable(offered: object) -> str | None:
    """The offered id when it is a string of the documented shape, else None."""
    if isinstance(offered, str) and REQUEST_ID_SHAPE.fullmatch(offered):
        return offered
    return None


def correlation_id_of(request: Request) -> str | None:
    """The request's correlation id: scope state first, then the log context, then the header."""
    from_state = request.scope.get("state", {}).get(_STATE_KEY)
    if isinstance(from_state, str):
        return from_state
    from_context = structlog.contextvars.get_contextvars().get(_STATE_KEY)
    if isinstance(from_context, str):
        return from_context
    return request.headers.get(REQUEST_ID_HEADER)
