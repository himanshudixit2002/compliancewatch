"""Work a person does on a stored document (the ``pipeline_task`` table).

- ``manual_parse``: no parser of the chain could read the document (a scan with no text layer,
  a file no parser opens). The ingest opens the task, sets the document ``failed`` and registers
  nothing. An analyst resolves it with a transcript (``domain.transcripts``), from which the
  document is parsed as ``manual@1`` and registered, or dismisses it with a reason.
- ``triage``: a document the classify step cannot place, because its text names another type
  than its source publishes (``domain.classification``). The classify step opens the task and
  holds the document, unregistered; an analyst resolves it with a decision (relevant with a
  type, or irrelevant) or dismisses it with a reason.

A document has at most one open task of a kind (a partial unique index), so the ingest's retry
and a second ingest of the same bytes find the task that is open. A task opens with why
(``reason``); a person may claim it (``claimed_by``); it ends ``resolved``, by whoever resolved
it, with what the resolution did (``resolution``) and their note, or ``dismissed`` with their
reason (``note``). ``resolved_by`` is empty for a task the pipeline closed itself (a document a
later ingest parsed). A closed task does not change again.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Final, Self
from uuid import UUID

from domain_kernel._validation import freeze_mapping, require_aware, require_instance
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import DocumentId, EntityId
from pipeline.domain.errors import TaskClosedError
from pipeline.domain.sources import require_source_key

MAX_REASON_CHARS: Final = 2_000
MAX_NOTE_CHARS: Final = 2_000


class TaskKind(StrEnum):
    MANUAL_PARSE = "manual_parse"
    TRIAGE = "triage"


class TaskStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


@dataclass(frozen=True, slots=True)
class TaskId(EntityId):
    """One pipeline task."""


def _require_length(value: object, name: str, maximum: int) -> str:
    text = require_instance(value, str, name)
    if len(text) > maximum:
        raise InvariantViolationError(f"{name} must be at most {maximum} characters")
    return text


@dataclass(frozen=True, slots=True)
class PipelineTask:
    id: TaskId
    kind: TaskKind
    document_id: DocumentId
    source_key: str
    opened_at: datetime
    status: TaskStatus = TaskStatus.OPEN
    reason: str = ""
    claimed_by: UUID | None = None
    resolved_by: UUID | None = None
    resolved_at: datetime | None = None
    resolution: Mapping[str, object] | None = None
    note: str = ""

    def __post_init__(self) -> None:
        require_instance(self.id, TaskId, "id")
        require_instance(self.kind, TaskKind, "kind")
        require_instance(self.document_id, DocumentId, "document_id")
        require_source_key(self.source_key)
        require_aware(self.opened_at, "opened_at")
        require_instance(self.status, TaskStatus, "status")
        _require_length(self.reason, "reason", MAX_REASON_CHARS)
        _require_length(self.note, "note", MAX_NOTE_CHARS)
        for name in ("claimed_by", "resolved_by"):
            value = getattr(self, name)
            if value is not None:
                require_instance(value, UUID, name)
        if (self.status is TaskStatus.OPEN) != (self.resolved_at is None):
            raise InvariantViolationError("a task is open exactly while it has no resolved_at")
        if self.resolved_at is not None:
            require_aware(self.resolved_at, "resolved_at")
            if self.resolved_at < self.opened_at:
                raise InvariantViolationError("resolved_at must not be before opened_at")
        if self.status is TaskStatus.OPEN and self.resolved_by is not None:
            raise InvariantViolationError("an open task has no resolved_by")
        if self.resolution is not None:
            if self.status is not TaskStatus.RESOLVED:
                raise InvariantViolationError("only a resolved task has a resolution")
            object.__setattr__(self, "resolution", freeze_mapping(self.resolution, "resolution"))

    @classmethod
    def opened(
        cls,
        kind: TaskKind,
        document_id: DocumentId,
        source_key: str,
        *,
        at: datetime,
        reason: str = "",
        task_id: TaskId | None = None,
    ) -> Self:
        return cls(
            id=task_id or TaskId.new(),
            kind=kind,
            document_id=document_id,
            source_key=source_key,
            opened_at=at,
            reason=reason.strip()[:MAX_REASON_CHARS],
        )

    @property
    def is_open(self) -> bool:
        return self.status is TaskStatus.OPEN

    def _closing(self) -> None:
        if not self.is_open:
            raise TaskClosedError(f"task {self.id} is {self.status.value}; it does not change")

    def resolve(
        self, by: UUID | None, at: datetime, resolution: Mapping[str, object], note: str = ""
    ) -> Self:
        """The task resolved by ``by`` (None: by the pipeline) with what the resolution did."""
        self._closing()
        return replace(
            self,
            status=TaskStatus.RESOLVED,
            resolved_by=by,
            resolved_at=max(at, self.opened_at),
            resolution=resolution,
            note=note.strip()[:MAX_NOTE_CHARS],
        )

    def dismiss(self, by: UUID | None, at: datetime, note: str) -> Self:
        """The task dismissed by ``by``, with why."""
        self._closing()
        return replace(
            self,
            status=TaskStatus.DISMISSED,
            resolved_by=by,
            resolved_at=max(at, self.opened_at),
            note=note.strip()[:MAX_NOTE_CHARS],
        )
