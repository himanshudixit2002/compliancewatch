"""One crawl of one source (the ``crawl_run`` table): when it ran, what it found, how it ended.

A run starts ``running`` and finishes ``completed``, or ``failed`` with the error. Its counts
are what the listing returned (``listed``), the documents stored for the first time
(``stored``), the ones fetched again with bytes already stored (``duplicates``) and the ones that
could not be fetched or stored (``failed``).
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Final, Self

from domain_kernel._validation import require_aware, require_instance, require_int
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import EntityId
from pipeline.domain.sources import MAX_ERROR_CHARS, require_source_key

COUNTS: Final = ("listed", "stored", "duplicates", "failed")


@dataclass(frozen=True, slots=True)
class CrawlRunId(EntityId):
    """One crawl of one source."""


class CrawlStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class CrawlCounts:
    listed: int = 0
    stored: int = 0
    duplicates: int = 0
    failed: int = 0

    def __post_init__(self) -> None:
        for name in COUNTS:
            require_int(getattr(self, name), name, minimum=0)

    @property
    def fetched(self) -> int:
        """Documents whose bytes were fetched: the new ones and the duplicates."""
        return self.stored + self.duplicates


@dataclass(frozen=True, slots=True)
class CrawlRun:
    id: CrawlRunId
    source_key: str
    started_at: datetime
    status: CrawlStatus = CrawlStatus.RUNNING
    finished_at: datetime | None = None
    counts: CrawlCounts = field(default_factory=CrawlCounts)
    error: str = ""

    def __post_init__(self) -> None:
        require_instance(self.id, CrawlRunId, "id")
        require_source_key(self.source_key)
        require_aware(self.started_at, "started_at")
        require_instance(self.status, CrawlStatus, "status")
        if (self.status is CrawlStatus.RUNNING) != (self.finished_at is None):
            raise InvariantViolationError("a run has finished_at exactly when it is not running")
        if self.finished_at is not None:
            require_aware(self.finished_at, "finished_at")
            if self.finished_at < self.started_at:
                raise InvariantViolationError("finished_at must not be before started_at")
        require_instance(self.counts, CrawlCounts, "counts")
        error = require_instance(self.error, str, "error")
        if len(error) > MAX_ERROR_CHARS:
            raise InvariantViolationError(f"error must be at most {MAX_ERROR_CHARS} chars")
        if (self.status is CrawlStatus.FAILED) != bool(error.strip()):
            raise InvariantViolationError("a run has an error exactly when it failed")

    @classmethod
    def start(cls, source_key: str, now: datetime) -> Self:
        return cls(id=CrawlRunId.new(), source_key=source_key, started_at=now)

    def finish(self, now: datetime, counts: CrawlCounts, *, error: str = "") -> Self:
        """The run ended: completed, or failed with ``error`` (cut to ``MAX_ERROR_CHARS``)."""
        if self.status is not CrawlStatus.RUNNING:
            raise InvariantViolationError(f"crawl run {self.id} has already {self.status.value}")
        cut = error.strip()[:MAX_ERROR_CHARS]
        return type(self)(
            id=self.id,
            source_key=self.source_key,
            started_at=self.started_at,
            status=CrawlStatus.FAILED if cut else CrawlStatus.COMPLETED,
            finished_at=now,
            counts=counts,
            error=cut,
        )
