"""Helpers every adapter needs: dates in the regulators' formats and the fetch of a document."""

import re
from datetime import date, datetime

from domain_kernel.documents import DocumentRef, RawDocument
from pipeline.infrastructure.http import PoliteClient

_DMY = re.compile(r"^\s*(\d{1,2})[-/](\d{1,2})[-/](\d{4})\s*$")


def parse_dmy(text: str) -> date | None:
    """``dd-mm-yyyy`` or ``dd/mm/yyyy``; None when the text is not a date."""
    match = _DMY.match(text)
    if match is None:
        return None
    day, month, year = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_iso_date(text: str | None) -> date | None:
    """The date part of an ISO timestamp such as ``2026-05-07T05:30:00+05:30``."""
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def on_or_after(published: date | None, since: datetime) -> bool:
    """Unknown dates pass: a document without a date is listed rather than lost."""
    return published is None or published >= since.date()


def fetch_bytes(
    client: PoliteClient, ref: DocumentRef, *, media_type: str | None = None
) -> RawDocument:
    """GET the document and wrap the bytes; the media type comes from the response unless given."""
    response = client.get(ref.url)
    response.raise_for_status()
    kind = media_type or response.headers.get("content-type") or "application/octet-stream"
    return RawDocument.from_bytes(ref, response.content, kind.split(";")[0].strip())
