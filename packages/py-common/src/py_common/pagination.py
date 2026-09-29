"""Keyset pagination for list routes: the page parameters, an opaque cursor and the page body.

A list route takes ``page: Pagination``, which reads ``limit`` (1 to 200, default 50) and
``cursor`` (at most 512 characters) from the query. It asks its repository for ``limit + 1`` rows
in the order of a unique key, starting after the keyset ``page.after(...)`` decodes, and answers
with a ``Page``. ``page_of`` keeps the first ``limit`` rows and, when the extra row came back,
makes the next cursor from the last row kept.

A cursor is base64url JSON without padding: ``{"k": {...}, "s": <scope>, "v": 1}``. ``v`` is the
format version, ``s`` names the list the cursor belongs to (``"profile.businesses"``) and ``k`` is
the keyset: the fields of a small pydantic model the route declares, such as ``name`` and ``id``.
``decode_cursor`` turns anything else into ``InvalidCursorError`` (422): text that is not base64url
JSON, another format version, the cursor of another list, or a keyset that does not fit the model.
Cursors are opaque but not signed. A client that crafts one only moves where its page starts,
inside the rows it may read anyway, so there is nothing to protect with a key.
"""

import base64
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Annotated, Final, NoReturn

from fastapi import Depends, Query
from pydantic import BaseModel, Field, ValidationError

from domain_kernel.errors import DomainError

CURSOR_VERSION: Final = 1
DEFAULT_LIMIT: Final = 50
MAX_LIMIT: Final = 200
MAX_CURSOR_CHARS: Final = 512
_BASE64URL = re.compile(r"[A-Za-z0-9_-]+")
_ENVELOPE_KEYS: Final = frozenset({"k", "s", "v"})


class InvalidCursorError(DomainError):
    """A cursor this list did not issue: not base64url JSON, another format version, the cursor
    of another list, or a keyset that does not fit the list's keyset model."""

    type_slug = "pagination-cursor-invalid"
    title = "Pagination cursor is invalid"


def encode_cursor(scope: str, keyset: BaseModel) -> str:
    """The cursor of the page that starts after ``keyset`` in the list named ``scope``.

    Raises ``ValueError`` when the cursor would be longer than ``MAX_CURSOR_CHARS``, since the
    next request could not send it back: key a list on short columns (ids, dates, bounded
    names) so every cursor fits.
    """
    if not scope:
        raise ValueError("a cursor needs the name of its list")
    payload = {"k": keyset.model_dump(mode="json"), "s": scope, "v": CURSOR_VERSION}
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    # surrogatepass: a text key holding a lone surrogate still round-trips instead of failing.
    raw = text.encode("utf-8", "surrogatepass")
    cursor = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    if len(cursor) > MAX_CURSOR_CHARS:
        raise ValueError(
            f"the {scope} cursor takes {len(cursor)} characters; at most {MAX_CURSOR_CHARS} fit"
        )
    return cursor


def decode_cursor[K: BaseModel](cursor: str, scope: str, keyset: type[K]) -> K:
    """The keyset ``cursor`` holds, as an instance of ``keyset``; ``InvalidCursorError`` when the
    cursor is malformed, of another version or of another list than ``scope``."""
    if len(cursor) > MAX_CURSOR_CHARS or not _BASE64URL.fullmatch(cursor):
        _invalid("it is not base64url text of at most 512 characters")
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        payload = json.loads(raw.decode("utf-8", "surrogatepass"), parse_constant=_reject_constant)
    except ValueError as exc:
        _invalid("it does not decode to JSON", exc)
    if not isinstance(payload, dict) or payload.keys() != _ENVELOPE_KEYS:
        _invalid("it is not a cursor this API issued")
    version = payload["v"]
    if type(version) is not int or version != CURSOR_VERSION:
        _invalid(f"its format version is {version!r}, not {CURSOR_VERSION}")
    if payload["s"] != scope:
        _invalid("it belongs to another list")
    try:
        return keyset.model_validate(payload["k"])
    except ValidationError as exc:
        _invalid("its keyset does not fit this list", exc)


@dataclass(frozen=True, slots=True)
class PageParams:
    """The ``limit`` and ``cursor`` query parameters of a list route (``Pagination`` reads them).

    ``cursor`` is the ``next_cursor`` of the previous page and is absent for the first one.
    """

    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT, description="Items per page, 1 to 200")] = (
        DEFAULT_LIMIT
    )
    cursor: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=MAX_CURSOR_CHARS,
            description="The next_cursor of the previous page; absent for the first page",
        ),
    ] = None

    def after[K: BaseModel](self, scope: str, keyset: type[K]) -> K | None:
        """The keyset the page starts after, or None for the first page."""
        return None if self.cursor is None else decode_cursor(self.cursor, scope, keyset)


Pagination = Annotated[PageParams, Depends()]
"""The dependency a list route declares: ``page: Pagination``."""


class Page[T](BaseModel):
    """One page of a list: the items in the list's order and the cursor of the next page."""

    items: list[T]
    next_cursor: str | None = Field(
        description="Send as cursor to read the next page; null on the last page"
    )


def page_of[R](
    rows: Sequence[R], limit: int, scope: str, keyset: Callable[[R], BaseModel]
) -> tuple[list[R], str | None]:
    """The first ``limit`` of ``rows``, which the repository read as ``limit + 1``, and the cursor
    after the last row kept; the cursor is None when no extra row came back (the last page)."""
    if limit < 1:
        raise ValueError(f"limit must be at least 1, got {limit}")
    kept = list(rows[:limit])
    if len(rows) <= limit:
        return kept, None
    return kept, encode_cursor(scope, keyset(kept[-1]))


def _reject_constant(name: str) -> NoReturn:
    raise ValueError(f"{name} is not JSON")


def _invalid(reason: str, cause: Exception | None = None) -> NoReturn:
    raise InvalidCursorError(f"The cursor is invalid: {reason}.") from cause
