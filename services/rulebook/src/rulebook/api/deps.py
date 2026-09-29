"""Request-scoped dependencies: the wiring and the two token checks.

The pipeline writes what it extracted (documents, mentions, relation candidates, clause
embeddings) with the write token. An analyst's decisions (entity reviews, relation approvals,
citations, the version lifecycle and the sweep) need the review token instead, so a leaked
pipeline secret cannot approve or publish a rule. Both are shared secrets: the approver ids in the
bodies are asserted by the caller until the identity service issues them.
"""

import hmac
from typing import Annotated

from fastapi import Depends, Header, Request
from pydantic import SecretStr

from rulebook.domain.errors import (
    ReviewsDisabledError,
    ReviewTokenInvalidError,
    WritesDisabledError,
    WriteTokenInvalidError,
)
from rulebook.wiring import Wiring


def wiring(request: Request) -> Wiring:
    wired: Wiring = request.app.state.wiring
    return wired


Wired = Annotated[Wiring, Depends(wiring)]


def _matches(configured: SecretStr, given: str | None) -> bool:
    """The comparison takes the same time for any wrong token."""
    return hmac.compare_digest(
        (given or "").encode("utf-8"), configured.get_secret_value().encode("utf-8")
    )


def require_write_token(
    wired: Wired,
    x_cw_write_token: Annotated[
        str | None, Header(description="Shared secret for writes (CW_RULEBOOK_WRITE_TOKEN)")
    ] = None,
) -> None:
    """Writes change tables every tenant reads, so they fail closed: no configured token is a
    503, a missing or wrong one a 401."""
    configured = wired.settings.rulebook_write_token
    if configured is None or not configured.get_secret_value():
        raise WritesDisabledError()
    if not _matches(configured, x_cw_write_token):
        raise WriteTokenInvalidError()


def require_review_token(
    wired: Wired,
    x_cw_review_token: Annotated[
        str | None,
        Header(description="Shared secret for analyst actions (CW_RULEBOOK_REVIEW_TOKEN)"),
    ] = None,
) -> None:
    """Analyst actions fail closed the same way: no configured token is a 503, a missing or
    wrong one a 401. The write token does not open them."""
    configured = wired.settings.rulebook_review_token
    if configured is None or not configured.get_secret_value():
        raise ReviewsDisabledError()
    if not _matches(configured, x_cw_review_token):
        raise ReviewTokenInvalidError()


WriteAccess = Depends(require_write_token)
ReviewAccess = Depends(require_review_token)
