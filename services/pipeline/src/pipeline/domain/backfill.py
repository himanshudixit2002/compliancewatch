"""A backfill plan: rows of history to crawl, one source each, in order.

A row names its source, the window its crawls list (``since`` below the watermark, ``until``, the
references ``refs`` it takes; ``crawl.ListingWindow``), the most documents one crawl ingests
(``limit``) and the most the row stores in all (``max_documents``; none: as many as are new). The
backfill runs each row's crawls one after the other (``CrawlSourceWorkflow`` with the trigger
``backfill``), and starts another round while the last one left new documents for a later crawl
and stored something (``next_limit``), so a row ends once nothing is new, once nothing more could
be stored, at its ``max_documents``, or after ``max_rounds``. A backfill never moves a source's
watermark back (``crawl.settled_watermark``).
"""

from dataclasses import dataclass
from datetime import date
from typing import Final

from domain_kernel._validation import require_instance, require_int
from domain_kernel.errors import InvariantViolationError
from pipeline.domain.crawl import MAX_NEW_PER_CRAWL, ListingWindow
from pipeline.domain.sources import require_source_key

MAX_CRAWL_LIMIT: Final = 500
"""The most documents one crawl of a backfill ingests (``CrawlRequest.limit``)."""
DEFAULT_MAX_ROUNDS: Final = 20
MAX_NOTE_CHARS: Final = 500


@dataclass(frozen=True, slots=True)
class BackfillRow:
    """One row of a plan: the source, its listing window, the most documents per crawl, the most
    in all, and why the row is there (``note``)."""

    source_key: str
    since: date
    until: date | None = None
    refs: tuple[str, ...] = ()
    limit: int = MAX_NEW_PER_CRAWL
    max_documents: int | None = None
    note: str = ""

    def __post_init__(self) -> None:
        require_source_key(self.source_key)
        require_instance(self.since, date, "since")
        require_int(self.limit, "limit", minimum=1)
        if self.limit > MAX_CRAWL_LIMIT:
            raise InvariantViolationError(f"limit must be at most {MAX_CRAWL_LIMIT}")
        if self.max_documents is not None:
            require_int(self.max_documents, "max_documents", minimum=1)
        if len(require_instance(self.note, str, "note")) > MAX_NOTE_CHARS:
            raise InvariantViolationError(f"note must be at most {MAX_NOTE_CHARS} characters")
        ListingWindow(self.since, self.until, self.refs)  # checks until and the refs

    @property
    def window(self) -> ListingWindow:
        return ListingWindow(self.since, self.until, self.refs)

    def describe(self) -> str:
        """The row in a line: ``cbic_notifications since 2020-01-01 until 2020-12-31, 3 refs``."""
        parts = [f"{self.source_key} since {self.since.isoformat()}"]
        if self.until is not None:
            parts.append(f"until {self.until.isoformat()}")
        if self.refs:
            parts.append(f"{len(self.refs)} ref{'' if len(self.refs) == 1 else 's'}")
        if self.max_documents is not None:
            parts.append(f"at most {self.max_documents} documents")
        return ", ".join(parts)


def next_limit(
    row: BackfillRow, *, rounds: int, stored: int, deferred: int, progressed: bool, max_rounds: int
) -> int | None:
    """The limit of the row's next crawl, or None when the row is done: nothing new was left
    (``deferred``), the last crawl kept nothing (``progressed``: it stored no document and found
    none stored before), the row stored its ``max_documents``, or it ran ``max_rounds``."""
    if deferred == 0 or not progressed or rounds >= max_rounds:
        return None
    if row.max_documents is None:
        return row.limit
    left = row.max_documents - stored
    return None if left <= 0 else min(row.limit, left)


def first_limit(row: BackfillRow) -> int:
    """The limit of the row's first crawl."""
    return row.limit if row.max_documents is None else min(row.limit, row.max_documents)
