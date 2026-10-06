"""The work people do on stored documents: the task queue, a manual parse's resolution with a
transcript, a triage's resolution with a decision, and a dismissal.

The routes belong to the regulatory team (composition class admin), with the guards of the source
manager (``pipeline.api.deps``): the list needs a regulatory role a token names, the resolution
and the dismissal an admin, or the shared write token in ``header`` and ``dual`` mode. Each write
names its actor and a reason, and writes its ``audit.event`` row (``pipeline.task.resolve`` or
``.dismiss``, of no tenant) in the transaction of the change.
"""

from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Query

from domain_kernel.access import Principal
from pipeline.api.deps import SourceRead, SourceWrite, Wired, admin_actor
from pipeline.api.schemas import (
    AdminWriteIn,
    DismissIn,
    ResolutionOut,
    ResolveIn,
    TaskCursor,
    TaskOut,
)
from pipeline.application.sources import AdminAction
from pipeline.domain.tasks import TaskId, TaskKind, TaskStatus
from pipeline.domain.transcripts import read_transcript
from py_common.audit import current_correlation_id
from py_common.pagination import Page, Pagination, page_of
from py_common.problems import problem_responses

router = APIRouter(prefix="/v1/pipeline", tags=["pipeline"])

TASKS_SCOPE: Final = "pipeline.tasks"


def _admin(principal: Principal, body: AdminWriteIn) -> AdminAction:
    return AdminAction(
        actor=admin_actor(principal, body.actor_id),
        reason=body.reason,
        correlation_id=current_correlation_id(),
    )


@router.get(
    "/tasks",
    summary="List the pipeline's tasks, oldest first",
    dependencies=[SourceRead],
    responses=problem_responses(401, 403, 422),
)
def list_tasks(
    page: Pagination,
    wired: Wired,
    status: Annotated[TaskStatus | None, Query(description="Only tasks of this status")] = None,
    kind: Annotated[TaskKind | None, Query(description="Only tasks of this kind")] = None,
) -> Page[TaskOut]:
    """The tasks of a status and a kind (both optional), a page at a time, oldest first (then
    by id), each with its document: open manual parses are documents no parser reads, waiting
    for an analyst's transcript."""
    scope = f"{TASKS_SCOPE}.{status or 'any'}.{kind or 'any'}"
    after = page.after(scope, TaskCursor)
    views = wired.list_tasks.run(
        status=status,
        kind=kind,
        after=None if after is None else after.key(),
        limit=page.limit + 1,
    )
    kept, cursor = page_of(views, page.limit, scope, TaskCursor.of)
    return Page[TaskOut](items=[TaskOut.of(view) for view in kept], next_cursor=cursor)


@router.post(
    "/tasks/{task_id}/resolve",
    summary="Resolve a task: a manual parse with a transcript, a triage with a decision",
    responses=problem_responses(401, 403, 404, 409, 422, 503),
)
def resolve_task(task_id: UUID, body: ResolveIn, admin: SourceWrite, wired: Wired) -> ResolutionOut:
    """Resolve an open task.

    A manual parse takes the document typed by hand (``transcript``): headings, numbered
    paragraphs and tables in document order, checked first (422 names each problem). The
    transcript is kept in the raw store, the task is resolved and audited as
    pipeline.task.resolve, and an ingest starts that parses the document from it as manual@1,
    classifies it and, unless the classification sets it aside or holds it for a triage,
    registers it in the rulebook while knowledge is on; from then on the document is parsed
    from its transcript.

    A triage takes the analyst's decision (``triage``): relevant with the document's type, or
    irrelevant. It is stored on the task's resolution and becomes the document's classification
    (certain, by triage), with its status and a document.classified, audited as
    pipeline.task.resolve; the stored document's own type is never changed. A relevant document
    continues through an ingest (pipeline-triage-<task>) that registers it as that type while
    knowledge is on and, for a notification, circular or act amendment, extracts its rule
    candidate while the extraction is on; an irrelevant one is set aside and nothing starts.

    409 for a closed task (the same transcript or decision again starts the ingest if it did not
    start); 422 for a resolution that does not fit the task (a manual parse without a
    transcript, a triage without a decision, or either with the other's); 503 when Temporal does
    not answer, in which case the task stays resolved and the same request starts the ingest
    again."""
    transcript = (
        None
        if body.transcript is None
        else read_transcript(body.transcript.model_dump(exclude_none=True))
    )
    resolution = wired.resolve_task.run(
        TaskId(task_id),
        transcript,
        _admin(admin, body),
        triage=None if body.triage is None else body.triage.decision(),
    )
    return ResolutionOut.of(resolution)


@router.post(
    "/tasks/{task_id}/dismiss",
    summary="Dismiss a task with a reason",
    responses=problem_responses(401, 403, 404, 409, 422, 503),
)
def dismiss_task(task_id: UUID, body: DismissIn, admin: SourceWrite, wired: Wired) -> TaskOut:
    """Close an open task without the work: the reason says why (a duplicate scan, not a
    regulatory document). A dismissed manual parse leaves its document failed and unregistered,
    a dismissed triage leaves it held for triage and unregistered. Audited as
    pipeline.task.dismiss. 409 for a closed task."""
    return TaskOut.of(wired.dismiss_task.run(TaskId(task_id), _admin(admin, body)))
