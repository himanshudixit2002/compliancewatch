"""Request-scoped dependencies: the wiring and who may write.

The rulebook's tables are read by every tenant, so every write is guarded and fails closed. The
caller comes from ``py_common.auth.fastapi`` by ``CW_AUTH_MODE``, and a write is one of two kinds:

- ``PipelineWrite``: what the pipeline extracted (documents, mentions, relation candidates,
  clause embeddings). A service token with the rulebook:write scope, or the write token
  (``CW_RULEBOOK_WRITE_TOKEN`` in ``x-cw-write-token``).
- ``AnalystWrite``: an analyst's decisions. A signed-in user with the route's regulatory roles,
  or the review token (``CW_RULEBOOK_REVIEW_TOKEN`` in ``x-cw-review-token``). The write token
  does not open these routes, so a leaked pipeline secret cannot approve or publish a rule.

Which roles an analyst's route takes:

- review decisions (entity groups, relation approvals and rejections) and the sweep: analyst,
  reviewer or admin (``analyst_write``);
- citing a version and submitting it: analyst, or a service with rulebook:write
  (``Drafting``); returning it to draft also takes a reviewer (``Returning``);
- approving, publishing and withdrawing it: reviewer (``Reviewing``);
- claiming a review task and editing its draft: analyst (``AnalystWork``), a person and never a
  service; deciding a task and opening the seed tasks: analyst, reviewer or admin
  (``AnalystWrite``).

The shared tokens are accepted only in ``header`` and ``dual`` mode and without a bearer; token
mode takes the bearer alone. Without a bearer, an unset token is a 503 in ``header`` mode and a
401 asking for an access token in ``dual`` mode; a missing or wrong one is a 401, compared in
constant time. A caller a token names but who lacks the role or scope is a 403
``auth-forbidden``, whatever token it also sends.

With a user's token the routes record that user as the one who decided or acted
(``decided_by``, ``actor_id``) and ignore the body's value; without one the body names them, as
before tokens existed.

The review queues an analyst works through (open entity groups, their mentions, relation
candidates, review tasks and their stats) are read with ``ReviewRead``: in ``token`` mode a user
with a regulatory role, and in ``dual`` mode such a user when a bearer is sent. Without a token
they stay open as before. The rest of the read API (rule versions, rules, documents, entities,
relations, clauses, search) is the same for every tenant and needs no token in any mode.
"""

from collections.abc import Awaitable, Callable, Iterable
from typing import Annotated, Final
from uuid import UUID

from fastapi import Depends, Request

from domain_kernel.access import REGULATORY_ROLES, Principal, Role, Scope
from domain_kernel.ids import UserId
from py_common.auth.fastapi import require_roles, shared_token_or_roles
from rulebook.domain.errors import (
    ReviewsDisabledError,
    ReviewTokenInvalidError,
    WritesDisabledError,
    WriteTokenInvalidError,
)
from rulebook.wiring import Wiring

WRITE_TOKEN_HEADER: Final = "x-cw-write-token"
REVIEW_TOKEN_HEADER: Final = "x-cw-review-token"


def wiring(request: Request) -> Wiring:
    wired: Wiring = request.app.state.wiring
    return wired


Wired = Annotated[Wiring, Depends(wiring)]

pipeline_write = shared_token_or_roles(
    "rulebook_write_token",
    WRITE_TOKEN_HEADER,
    scopes=[Scope.RULEBOOK_WRITE],
    disabled_error=WritesDisabledError,
    invalid_error=WriteTokenInvalidError,
    description=(
        "Shared secret for writes (CW_RULEBOOK_WRITE_TOKEN), accepted when CW_AUTH_MODE is header "
        "or dual and the request carries no bearer token; a service token needs rulebook:write"
    ),
)


def analyst_action(
    *roles: Role | Iterable[Role], scopes: Iterable[Scope] = ()
) -> Callable[..., Awaitable[Principal]]:
    """The guard of an analyst's route: a user with one of ``roles``, a service with one of
    ``scopes``, or the review token without a bearer in ``header`` and ``dual`` mode."""
    return shared_token_or_roles(
        "rulebook_review_token",
        REVIEW_TOKEN_HEADER,
        roles,
        scopes,
        disabled_error=ReviewsDisabledError,
        invalid_error=ReviewTokenInvalidError,
        description=(
            "Shared secret for analyst actions (CW_RULEBOOK_REVIEW_TOKEN), accepted when "
            "CW_AUTH_MODE is header or dual and the request carries no bearer token"
        ),
    )


analyst_write = analyst_action(REGULATORY_ROLES)
drafting = analyst_action(Role.ANALYST, scopes=[Scope.RULEBOOK_WRITE])
returning = analyst_action(Role.ANALYST, Role.REVIEWER, scopes=[Scope.RULEBOOK_WRITE])
reviewing = analyst_action(Role.REVIEWER)
analyst_work = analyst_action(Role.ANALYST)

PipelineWrite = Annotated[Principal, Depends(pipeline_write)]
AnalystWrite = Annotated[Principal, Depends(analyst_write)]
Drafting = Annotated[Principal, Depends(drafting)]
Returning = Annotated[Principal, Depends(returning)]
Reviewing = Annotated[Principal, Depends(reviewing)]
AnalystWork = Annotated[Principal, Depends(analyst_work)]
"""Claiming a review task and editing its draft: an analyst a token names, or the review token
without a bearer; no service."""

ReviewRead = Depends(require_roles(REGULATORY_ROLES))
"""For the review queues: an analyst, reviewer or admin a token names; a service is refused."""

PipelineAccess = Depends(pipeline_write)
"""For a route that needs the guard but not the principal: ``dependencies=[PipelineAccess]``."""
AnalystAccess = Depends(analyst_write)
WriteAccess = PipelineAccess
"""The name the pipeline's writes had before the split; kept for code that still imports it."""
ReviewAccess = AnalystAccess
"""The name the analyst's actions had before the split; kept for code that still imports it."""


def decided_by(principal: Principal, offered: str) -> str:
    """Who decided: the user a verified token names, else the body's ``decided_by``."""
    return principal.subject if principal.is_authenticated else offered


def actor_of(principal: Principal, offered: UUID) -> UserId:
    """Who takes a step on a version: the user a verified token names, else the body's
    ``actor_id`` (also for a service, which is no person)."""
    user = principal.user_id
    return user if user is not None else UserId(offered)
