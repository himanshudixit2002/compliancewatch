"""Request-scoped dependencies: the wiring and the write-token check."""

import hmac
from typing import Annotated

from fastapi import Depends, Header, Request

from rulebook.domain.errors import WritesDisabledError, WriteTokenInvalidError
from rulebook.wiring import Wiring


def wiring(request: Request) -> Wiring:
    wired: Wiring = request.app.state.wiring
    return wired


Wired = Annotated[Wiring, Depends(wiring)]


def require_write_token(
    wired: Wired,
    x_cw_write_token: Annotated[
        str | None, Header(description="Shared secret for writes (CW_RULEBOOK_WRITE_TOKEN)")
    ] = None,
) -> None:
    """Writes change tables every tenant reads, so they fail closed: no configured token is a
    503, a missing or wrong one a 401. The comparison takes the same time for any wrong token."""
    configured = wired.settings.rulebook_write_token
    if configured is None or not configured.get_secret_value():
        raise WritesDisabledError()
    given = (x_cw_write_token or "").encode("utf-8")
    if not hmac.compare_digest(given, configured.get_secret_value().encode("utf-8")):
        raise WriteTokenInvalidError()


WriteAccess = Depends(require_write_token)
