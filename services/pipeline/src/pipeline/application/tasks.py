"""The work people do on stored documents: the task queue, a manual parse's resolution, a
triage's resolution and a dismissal.

- ``ListTasks``: tasks of a status and a kind (or any), oldest first, each with its document.
- ``ResolveTask`` of a manual parse: the analyst's transcript (``domain.transcripts``, checked
  before anything is stored) is kept in the raw store, as its canonical JSON under its digest,
  with no transaction open; then, in one transaction, the task is resolved by the actor with what
  the resolution did, and its ``audit.event`` row (``pipeline.task.resolve``, of no tenant) is
  written. With the transaction closed the ingest of the stored document starts with the
  transcript (``pipeline-manual-parse-<task>``), which parses it as ``manual@1``, classifies it
  and, unless the classification sets it aside or holds it for a triage, registers it while
  knowledge is on. When the start fails the task stays resolved and the same request starts it
  again; a resolved task takes no other transcript.
- ``ResolveTask`` of a triage: the analyst's decision (``domain.classification.TriageDecision``:
  relevant with a type, or irrelevant) is stored on the task's resolution and becomes the
  document's classification, ``certain``, by the ``triage`` classifier; in one transaction with
  the document's status, its ``document.classified`` and the audit row. The raw document's own
  ``doc_type`` (the uploader's) is never changed. A relevant document then continues through the
  ingest of the stored document (``pipeline-triage-<task>``), which finds the decision, registers
  the document as the type it names while knowledge is on, and extracts its rule candidate while
  the extraction is on; an irrelevant one is set aside and nothing starts. The same decision
  again replays, also when it arrives while the first is being written (it finds the task
  resolved once it holds the row lock): nothing is written twice, and the ingest is the first's,
  started only if it did not start. Another decision is refused.
- ``DismissTask``: the task dismissed with the actor's reason, audited as
  ``pipeline.task.dismiss``; a manual parse's document stays ``failed`` and unregistered, a
  triage's ``triage``.
"""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from domain_kernel.audit import AuditActor, AuditActorKind, AuditEntry
from domain_kernel.documents import DocumentRef, DocumentType, RawDocument
from domain_kernel.events import utc_now
from pipeline.application.sources import AdminAction, require_reason
from pipeline.domain.classification import Classification, TriageDecision
from pipeline.domain.errors import (
    DocumentNotFoundError,
    TaskClosedError,
    TaskNotFoundError,
    TaskResolutionError,
)
from pipeline.domain.events import DocumentClassified
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


def triage_workflow_id(task_id: TaskId) -> str:
    """``pipeline-triage-<task>``: the ingest a relevant triage's resolution starts."""
    return f"pipeline-triage-{task_id.value.hex}"


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
    """The resolved task, and the ingest it starts: started now, or found running or done
    (``started`` False). An irrelevant triage starts none: ``workflow_id`` is empty."""

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

    def run(
        self,
        task_id: TaskId,
        transcript: Transcript | None,
        admin: AdminAction,
        *,
        triage: TriageDecision | None = None,
    ) -> Resolution:
        reason = require_reason(admin.reason)
        with self._units() as unit:
            task = unit.tasks.get(task_id)
            if task is None:
                raise TaskNotFoundError(f"no task has the id {task_id}")
            view = _view(unit, task)
        if task.kind is TaskKind.TRIAGE:
            if transcript is not None:
                raise TaskResolutionError("a triage is resolved with a decision, not a transcript")
            if triage is None:
                raise TaskResolutionError(
                    "a triage is resolved with the analyst's decision: relevant with the "
                    "document's type, or irrelevant"
                )
            return self._triage(view, triage, admin, reason)
        if triage is not None:
            raise TaskResolutionError(
                "a manual parse is resolved with the analyst's transcript, not a triage"
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
                return self._ingest(view, manual_parse_workflow_id(task_id))
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
        return self._ingest(TaskView(resolved, view.document), manual_parse_workflow_id(task_id))

    def _triage(
        self, view: TaskView, decision: TriageDecision, admin: AdminAction, reason: str
    ) -> Resolution:
        """Store the decision on the task, make it the document's classification with its
        status and document.classified, audit it, then continue a relevant document.

        The same decision on a task resolved with it replays, whether the task was resolved
        before (the ingest did not start, or the caller retried) or while this request waited
        for its row lock (two requests at once): nothing is written, and the ingest is the one
        the first request started, started now only if it had not. Another decision on a
        closed task is refused."""
        recorded = decision.resolution()
        if view.task.is_open:
            view = self._decide(view, decision, recorded, admin, reason)
        task = view.task
        if task.status is TaskStatus.RESOLVED and _decided(task, recorded):
            return self._continue(view)
        raise TaskClosedError(f"task {task.id} is {task.status.value}; it does not change")

    def _decide(
        self,
        view: TaskView,
        decision: TriageDecision,
        recorded: dict[str, object],
        admin: AdminAction,
        reason: str,
    ) -> TaskView:
        """Resolve the open task with the decision, in one transaction with the document's
        classification, status, document.classified and audit row. A task another request
        closed first is returned as it is now, and nothing is written."""
        task = view.task
        now = self._clock()
        record = view.document
        with self._units() as unit:
            current = unit.tasks.get(task.id, for_update=True)
            if current is None:
                raise TaskNotFoundError(f"no task has the id {task.id}")
            if not current.is_open:
                return TaskView(current, unit.documents.get(record.document_id) or record)
            stored = unit.classifications.get(record.document_id)
            read_as = stored.doc_type if stored is not None else self._type_of(unit, record)
            classification = Classification.triaged(
                record.document_id,
                relevance=decision.relevance,
                doc_type=decision.doc_type or read_as,
                by=_person(admin.actor),
                task_id=task.id,
                at=now,
                reason=reason,
            )
            resolved = current.resolve(
                _person(admin.actor),
                now,
                {**recorded, "route": classification.route.value},
                reason,
            )
            unit.tasks.save(resolved)
            if stored is None:
                unit.classifications.add(classification)
            else:
                unit.classifications.save(classification)
            unit.documents.set_status(record.document_id, classification.route.status)
            unit.events.publish(
                DocumentClassified.of(
                    classification,
                    source_id=source_id_of(record.source_key),
                    source_key=record.source_key,
                )
            )
            unit.audit.write(
                AuditEntry(
                    action=RESOLVE_ACTION,
                    tenant_id=None,
                    subject_type=TASK_SUBJECT,
                    subject_id=str(task.id),
                    actor=admin.actor,
                    reason=reason,
                    before=_audited(current),
                    after=_audited(resolved),
                    occurred_at=now,
                    correlation_id=admin.correlation_id,
                )
            )
            document = unit.documents.get(record.document_id) or record
        log.info(
            "pipeline.task_triaged",
            task_id=str(task.id),
            relevance=decision.relevance.value,
            doc_type=classification.doc_type.value,
            route=classification.route.value,
        )
        return TaskView(resolved, document)

    def _type_of(self, unit: UnitOfWork, record: RawDocumentRecord) -> DocumentType:
        """The type the document is read as without a classification: its uploader's, else its
        source's."""
        if record.doc_type is not None:
            return record.doc_type
        source = unit.sources.get(record.source_key)
        if source is None:
            raise DocumentNotFoundError(f"document {record.document_id} names no stored source")
        return self._types.describe(source.adapter_type, source.parameters).doc_type

    def _continue(self, view: TaskView) -> Resolution:
        """A relevant triage's ingest; none for an irrelevant one."""
        if (view.task.resolution or {}).get("relevance") != "relevant":
            return Resolution(view, "", False)
        return self._ingest(view, triage_workflow_id(view.task.id))

    def _ingest(self, view: TaskView, workflow_id: str) -> Resolution:
        record = view.document
        resolution = view.task.resolution or {}
        with self._units() as unit:
            source = unit.sources.get(record.source_key)
        regulator = (
            ""
            if source is None
            else (self._types.describe(source.adapter_type, source.parameters).regulator)
        )
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


def _decided(task: PipelineTask, recorded: dict[str, object]) -> bool:
    """Whether the resolved task holds this decision."""
    resolution = task.resolution or {}
    return all(resolution.get(key) == value for key, value in recorded.items())


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
