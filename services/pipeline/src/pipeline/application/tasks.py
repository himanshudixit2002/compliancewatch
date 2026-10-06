"""The work people do on stored documents: the task queue, a manual parse's resolution and a
dismissal.

- ``ListTasks``: tasks of a status and a kind (or any), oldest first, each with its document.
- ``ResolveTask``: a manual parse resolved with the analyst's transcript (``domain.transcripts``,
  checked before anything is stored). The transcript is kept in the raw store, as its canonical
  JSON under its digest, with no transaction open; then, in one transaction, the task is
  resolved by the actor with what the resolution did, and its ``audit.event`` row
  (``pipeline.task.resolve``, of no tenant) is written. With the transaction closed the ingest of
  the stored document starts with the transcript (``pipeline-manual-parse-<task>``), which parses
  it as ``manual@1`` and, while knowledge is on, registers it. When the start fails the task
  stays resolved and the same request starts it again; a resolved task takes no other
  transcript. A triage task is resolved by the triage step, which is not built yet.
- ``DismissTask``: the task dismissed with the actor's reason, audited as
  ``pipeline.task.dismiss``; the document stays ``failed`` and unregistered.
"""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from domain_kernel.audit import AuditActor, AuditActorKind, AuditEntry
from domain_kernel.documents import DocumentRef, RawDocument
from domain_kernel.events import utc_now
from pipeline.application.sources import AdminAction, require_reason
from pipeline.domain.errors import (
    DocumentNotFoundError,
    TaskClosedError,
    TaskNotFoundError,
    TaskResolutionError,
)
from pipeline.domain.ports import AdapterTypes, IngestStart, IngestStarter, RawStore
from pipeline.domain.raw_documents import RawDocumentRecord
from pipeline.domain.repository import TaskKey, UnitOfWork, UnitOfWorkFactory
from pipeline.domain.sources import source_id_of
from pipeline.domain.tasks import PipelineTask, TaskId, TaskKind, TaskStatus
from pipeline.domain.transcripts import TRANSCRIPT_MEDIA_TYPE, TRANSCRIPT_PARSER, Transcript
from py_common.logging import get_logger

log = get_logger(__name__)

TASK_SUBJECT: Final = "pipeline_task"
RESOLVE_ACTION: Final = "pipeline.task.resolve"
DISMISS_ACTION: Final = "pipeline.task.dismiss"


def manual_parse_workflow_id(task_id: TaskId) -> str:
    """``pipeline-manual-parse-<task>``: the ingest a task's resolution starts."""
    return f"pipeline-manual-parse-{task_id.value.hex}"


def _person(actor: AuditActor) -> UUID | None:
    return UUID(actor.id) if actor.kind is AuditActorKind.USER else None


def _audited(task: PipelineTask) -> dict[str, object]:
    return {
        "kind": task.kind.value,
        "status": task.status.value,
        "document_id": str(task.document_id),
        "resolution": None if task.resolution is None else dict(task.resolution),
        "note": task.note,
    }


@dataclass(frozen=True, slots=True)
class TaskView:
    """A task with the document it is about."""

    task: PipelineTask
    document: RawDocumentRecord


def _view(unit: UnitOfWork, task: PipelineTask) -> TaskView:
    document = unit.documents.get(task.document_id)
    if document is None:
        raise DocumentNotFoundError(f"task {task.id} names no stored document")
    return TaskView(task, document)


class ListTasks:
    def __init__(self, units: UnitOfWorkFactory) -> None:
        self._units = units

    def run(
        self,
        *,
        status: TaskStatus | None,
        kind: TaskKind | None,
        after: TaskKey | None,
        limit: int,
    ) -> list[TaskView]:
        with self._units() as unit:
            tasks = unit.tasks.page(status=status, kind=kind, after=after, limit=limit)
            return [_view(unit, task) for task in tasks]


@dataclass(frozen=True, slots=True)
class Resolution:
    """The resolved task, and the ingest that parses its transcript: started now, or found
    running or done (``started`` False)."""

    task: TaskView
    workflow_id: str
    started: bool


class ResolveTask:
    def __init__(
        self,
        units: UnitOfWorkFactory,
        raw_store: RawStore,
        starter: IngestStarter,
        types: AdapterTypes,
        *,
        knowledge: bool,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._units = units
        self._raw = raw_store
        self._starter = starter
        self._types = types
        self._knowledge = knowledge
        self._clock = clock

    def run(self, task_id: TaskId, transcript: Transcript | None, admin: AdminAction) -> Resolution:
        reason = require_reason(admin.reason)
        with self._units() as unit:
            task = unit.tasks.get(task_id)
            if task is None:
                raise TaskNotFoundError(f"no task has the id {task_id}")
            view = _view(unit, task)
        if task.kind is not TaskKind.MANUAL_PARSE:
            raise TaskResolutionError(
                f"a {task.kind.value} task is resolved by its own step, not with a transcript"
            )
        if transcript is None:
            raise TaskResolutionError("a manual parse is resolved with the analyst's transcript")
        encoded = transcript.encoded()
        digest = hashlib.sha256(encoded).hexdigest()
        if not task.is_open:
            if (
                task.status is TaskStatus.RESOLVED
                and (task.resolution or {}).get("transcript_sha256") == digest
            ):
                # The same resolution again: its ingest did not start, or the caller retried.
                return self._ingest(view)
            raise TaskClosedError(f"task {task_id} is {task.status.value}; it does not change")
        source_id = source_id_of(view.document.source_key)
        key = self._raw.put(
            RawDocument.from_bytes(
                DocumentRef(source_id, f"transcript:{task_id}"),
                encoded,
                TRANSCRIPT_MEDIA_TYPE,
                self._clock(),
            )
        )
        now = self._clock()
        with self._units() as unit:
            current = unit.tasks.get(task_id, for_update=True)
            if current is None:
                raise TaskNotFoundError(f"no task has the id {task_id}")
            resolved = current.resolve(
                _person(admin.actor),
                now,
                {
                    "transcript_key": key,
                    "transcript_sha256": digest,
                    "parser_version": TRANSCRIPT_PARSER,
                    "clauses": len(transcript.clauses()),
                },
                reason,
            )
            unit.tasks.save(resolved)
            unit.audit.write(
                AuditEntry(
                    action=RESOLVE_ACTION,
                    tenant_id=None,
                    subject_type=TASK_SUBJECT,
                    subject_id=str(task_id),
                    actor=admin.actor,
                    reason=reason,
                    before=_audited(current),
                    after=_audited(resolved),
                    occurred_at=now,
                    correlation_id=admin.correlation_id,
                )
            )
        log.info("pipeline.task_resolved", task_id=str(task_id), transcript_key=key)
        return self._ingest(TaskView(resolved, view.document))

    def _ingest(self, view: TaskView) -> Resolution:
        record = view.document
        resolution = view.task.resolution or {}
        with self._units() as unit:
            source = unit.sources.get(record.source_key)
        regulator = (
            ""
            if source is None
            else (self._types.describe(source.adapter_type, source.parameters).regulator)
        )
        workflow_id = manual_parse_workflow_id(view.task.id)
        started = self._starter.start(
            IngestStart(
                workflow_id=workflow_id,
                record=record,
                source_id=source_id_of(record.source_key),
                regulator=regulator,
                raw_uri=self._raw.uri(record.storage_key),
                duplicate=True,
                transcript_key=str(resolution.get("transcript_key", "")),
                knowledge=self._knowledge and bool(regulator),
            )
        )
        return Resolution(view, workflow_id, started)


class DismissTask:
    def __init__(
        self, units: UnitOfWorkFactory, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._units = units
        self._clock = clock

    def run(self, task_id: TaskId, admin: AdminAction) -> TaskView:
        reason = require_reason(admin.reason)
        now = self._clock()
        with self._units() as unit:
            task = unit.tasks.get(task_id, for_update=True)
            if task is None:
                raise TaskNotFoundError(f"no task has the id {task_id}")
            dismissed = task.dismiss(_person(admin.actor), now, reason)
            unit.tasks.save(dismissed)
            unit.audit.write(
                AuditEntry(
                    action=DISMISS_ACTION,
                    tenant_id=None,
                    subject_type=TASK_SUBJECT,
                    subject_id=str(task_id),
                    actor=admin.actor,
                    reason=reason,
                    before=_audited(task),
                    after=_audited(dismissed),
                    occurred_at=now,
                    correlation_id=admin.correlation_id,
                )
            )
            view = _view(unit, dismissed)
        log.info("pipeline.task_dismissed", task_id=str(task_id))
        return view
