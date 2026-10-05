"""The changes feed of the public API: ``GET /v1/changes``.

It sits outside the service's prefix, as a path of the public API (tag ``public``), with the
roles that read it as ``x-roles``: every tenant member and the regulatory team. Like the rest of
the rulebook's read API it is the same for every tenant and needs no tenant or token in any
mode.
"""

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Query

from domain_kernel.access import REGULATORY_ROLES, TENANT_MEMBER_ROLES, Role
from domain_kernel.errors import InvariantViolationError
from py_common.pagination import Page, page_of
from py_common.problems import problem_responses
from rulebook.api.change_schemas import ChangePageParams, RuleChangeCursor, RuleChangeOut
from rulebook.api.deps import Wired
from rulebook.domain.changes import ChangeQuery

public_router = APIRouter(tags=["public", "changes"])

SCOPE: Final = "rulebook.changes"
IST: Final = timezone(timedelta(hours=5, minutes=30), "Asia/Kolkata")
SINCE_PATTERN: Final = (
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}"
    r"(T[0-9]{2}:[0-9]{2}(:[0-9]{2}(\.[0-9]{1,6})?)?(Z|[+-][0-9]{2}:[0-9]{2}))?$"
)
DAY: Final = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
PUBLIC_ROLES: Final = tuple(
    role.value for role in Role if role in TENANT_MEMBER_ROLES | REGULATORY_ROLES
)
"""Who reads the feed, in the kernel's order: every tenant member and the regulatory team."""
PUBLIC_ROUTE: Final[dict[str, Any]] = {"x-roles": list(PUBLIC_ROLES)}

ChangePage = Annotated[ChangePageParams, Depends()]


def since_of(since: str | None) -> datetime | None:
    """The moment ``since`` names: a date is the start of that day in India, a date-time carries
    its offset. 422 for a day or a time that does not exist."""
    if since is None:
        return None
    try:
        if DAY.fullmatch(since):
            return datetime.combine(date.fromisoformat(since), time(), tzinfo=IST)
        return datetime.fromisoformat(since)
    except ValueError as exc:
        raise InvariantViolationError(f"since: {since!r} is not a date or a date-time") from exc


@public_router.get(
    "/v1/changes",
    summary="The published changes to the rulebook, newest first, a page at a time",
    responses=problem_responses(422),
    openapi_extra=PUBLIC_ROUTE,
)
def list_changes(
    wired: Wired,
    page: ChangePage,
    since: Annotated[
        str | None,
        Query(
            pattern=SINCE_PATTERN,
            description=(
                "Only changes published at or after this moment: a date (from the start of that "
                "day in India) or a date-time with its offset"
            ),
        ),
    ] = None,
    regulator: Annotated[
        str | None,
        Query(min_length=1, max_length=40, description="Only versions of this regulator's rules"),
    ] = None,
) -> Page[RuleChangeOut]:
    """One item per change the rule events announced: a version published, superseded or
    withdrawn, or a due date a published version moved (``deadline_changed``, about the version
    whose date moved). Each carries the version's rule, dates, regulator, seed status (needs_review
    until an analyst reviews it), the approvers of the round it was published from, its verified
    citations and the versions it acts on. Newest first (changed_at, then change_id); ``limit`` is
    at most 100."""
    query = ChangeQuery(
        limit=page.limit + 1,
        since=since_of(since),
        regulator=regulator,
        after=page.after(SCOPE),
    )
    found = wired.list_changes.run(query)
    items, next_cursor = page_of(
        found,
        page.limit,
        SCOPE,
        lambda change: RuleChangeCursor(
            changed_at=change.entry.changed_at, change_id=change.entry.change_id
        ),
    )
    return Page[RuleChangeOut](
        items=[RuleChangeOut.from_change(change) for change in items], next_cursor=next_cursor
    )
