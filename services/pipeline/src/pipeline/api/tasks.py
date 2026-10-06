"""The work people do on stored documents: the task queue, a manual parse's resolution with a
transcript, and a dismissal.

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
    summary="Resolve a task: a manual parse with the analyst's transcript",
    responses=problem_responses(401, 403, 404, 409, 422, 503),
)
def resolve_task(task_id: UUID, body: ResolveIn, admin: SourceWrite, wired: Wired) -> ResolutionOut:
    """Resolve an open manual-parse task with the document typed by hand: headings, numbered
    paragraphs and tables in document order, checked first (422 names each problem). The
    transcript is kept in the raw store, the task is resolved and audited as
    pipeline.task.resolve, and an ingest starts that parses the document from it as manual@1
    and, while knowledge is on, registers it in the rulebook; from then on the document is
    parsed from its transcript. 409 for a closed task (the same transcript again starts the
    ingest if it did not start); 422 for a resolution that does not fit the task (a manual parse
    without a transcript, a triage task, which its own step resolves); 503 when Temporal does
    not answer, in which case the task stays resolved and the same request starts the ingest
    again."""
    transcript = (
        None
        if body.transcript is None
        else read_transcript(body.transcript.model_dump(exclude_none=True))
    )
    resolution = wired.resolve_task.run(TaskId(task_id), transcript, _admin(admin, body))
    return ResolutionOut.of(resolution)


@router.post(
    "/tasks/{task_id}/dismiss",
    summary="Dismiss a task with a reason",
    responses=problem_responses(401, 403, 404, 409, 422, 503),
)
def dismiss_task(task_id: UUID, body: DismissIn, admin: SourceWrite, wired: Wired) -> TaskOut:
    """Close an open task without the work: the reason says why (a duplicate scan, not a
    regulatory document). A dismissed manual parse leaves its document failed and unregistered.
    Audited as pipeline.task.dismiss. 409 for a closed task."""
    return TaskOut.of(wired.dismiss_task.run(TaskId(task_id), _admin(admin, body)))
