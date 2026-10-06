"""Review tasks: the queue of rule versions waiting for an analyst's decision, and the decisions.

Reads need a regulatory role a token names (``ReviewRead``; open without a token in header and
dual mode, as the other review queues). An analyst claims a task and edits its draft
(``AnalystWork``); an analyst, a reviewer or an admin decides it and opens the seed tasks
(``AnalystWrite``). Without a bearer, in header and dual mode, the review token opens the writes
and the body names the actor; a signed-in user is the actor whatever the body says, so the two
approvals of a high-impact version come from two people. ``POST .../draft``, which drafts a
version from a candidate, comes with the pipeline's candidates and is not served yet.
"""

from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Query

from domain_kernel.events import utc_now
from py_common.pagination import Page, Pagination, page_of
from py_common.problems import problem_responses
from rulebook.api.deps import (
    AnalystAccess,
    AnalystWork,
    AnalystWrite,
    ReviewRead,
    Wired,
    actor_of,
)
from rulebook.api.review_task_schemas import (
    ClaimIn,
    DecideIn,
    DraftEditIn,
    QueuedTaskOut,
    ReviewStatsOut,
    ReviewTaskDetailOut,
    ReviewTaskOut,
    SeedTasksOut,
    TaskCursor,
    TaskDecisionOut,
)
from rulebook.domain.review_tasks import ReviewTaskStatus

router = APIRouter(tags=["review"])

TASKS_SCOPE: Final = "rulebook.review-tasks"


@router.get(
    "/review/tasks",
    summary="The review queue: by regulator, higher priority first, then oldest first",
    dependencies=[ReviewRead],
    responses=problem_responses(401, 403, 422),
)
def list_review_tasks(
    page: Pagination,
    wired: Wired,
    status: Annotated[
        ReviewTaskStatus | None, Query(description="Only tasks of this status")
    ] = None,
    regulator: Annotated[
        str | None, Query(min_length=1, max_length=40, description="Only this regulator's")
    ] = None,
) -> Page[QueuedTaskOut]:
    """Each task with its version's rule, number, title and status, whether it is high impact
    and how many people approved its current round. A task open again after the first of two
    approvals waits for a second, different reviewer."""
    scope = f"{TASKS_SCOPE}.{status or 'any'}.{regulator or 'any'}"
    after = page.after(scope, TaskCursor)
    found = wired.list_review_tasks.run(
        status=status,
        regulator=regulator,
        after=None if after is None else after.key(),
        limit=page.limit + 1,
    )
    kept, cursor = page_of(found, page.limit, scope, TaskCursor.of)
    return Page[QueuedTaskOut](
        items=[QueuedTaskOut.from_queued(queued) for queued in kept], next_cursor=cursor
    )


@router.post(
    "/review/tasks/seed",
    summary="Open a review task for every seed draft that has none waiting",
    dependencies=[AnalystAccess],
    responses=problem_responses(401, 403, 503),
)
def open_seed_tasks(wired: Wired) -> SeedTasksOut:
    """One task of kind seed per draft that needs review and has no task open or claimed.
    Idempotent: a second request opens nothing new. A draft whose task was rejected gets a new
    one here."""
    opened = wired.open_seed_tasks.run().opened
    return SeedTasksOut(opened=len(opened), task_ids=[task.task_id for task in opened])


@router.get(
    "/review/tasks/{task_id}",
    summary="A review task with its version, citations, documents and history",
    dependencies=[ReviewRead],
    responses=problem_responses(401, 403, 404),
)
def read_review_task(task_id: UUID, wired: Wired) -> ReviewTaskDetailOut:
    """The version's content with its specification described, every citation with its
    verification, the documents they cite, the approvers of its current round, its decision
    audit and every task it has had."""
    return ReviewTaskDetailOut.from_detail(wired.read_review_task.run(task_id))


@router.post(
    "/review/tasks/{task_id}/claim",
    summary="Claim a review task; the claimant claiming again changes nothing",
    responses=problem_responses(401, 403, 404, 409, 422, 503),
)
def claim_review_task(
    task_id: UUID, body: ClaimIn, analyst: AnalystWork, wired: Wired
) -> ReviewTaskOut:
    """409 rulebook-review-task-claimed when someone else holds it, 409
    rulebook-review-task-closed when it was decided."""
    task = wired.claim_review_task.run(task_id, by=actor_of(analyst, body.actor_id))
    return ReviewTaskOut.from_task(task)


@router.patch(
    "/review/tasks/{task_id}/draft",
    summary="Edit the draft of a claimed task: its content and citations, every quote verified",
    responses=problem_responses(401, 403, 404, 409, 422, 503),
)
def edit_review_draft(
    task_id: UUID, body: DraftEditIn, analyst: AnalystWork, wired: Wired
) -> ReviewTaskDetailOut:
    """Only the analyst who claimed the task (409 rulebook-review-task-not-claimed), only while
    the version is a draft (409 rulebook-rule-version-not-editable). Content is checked against
    the ontology as the seed calendar is, and citations go through the citation step: a quote
    not in its clause is 422 rulebook-citation-not-verified and nothing is stored. The edit is
    recorded in the version's decision audit as edited."""
    detail = wired.edit_review_draft.run(
        task_id,
        by=actor_of(analyst, body.actor_id),
        edit=body.to_edit(),
        citations=body.to_citations(),
        note=body.note,
    )
    return ReviewTaskDetailOut.from_detail(detail)


@router.post(
    "/review/tasks/{task_id}/decide",
    summary="Approve, return or reject; the version's transition commits with the decision",
    responses=problem_responses(401, 403, 404, 409, 422, 503),
)
def decide_review_task(
    task_id: UUID, body: DecideIn, reviewer: AnalystWrite, wired: Wired
) -> TaskDecisionOut:
    """approve submits a draft and approves it: the approval that completes the round (one
    approver, two different ones when high impact) approves the version and decides the task,
    an earlier one leaves the task open for another reviewer, and the same person twice is 409
    rulebook-duplicate-approver. Approving never publishes; POST .../rule-versions/{id}/publish
    does. return sends the version back to draft and opens the next task for it; reject closes
    the task and leaves the version a draft. Both need a note."""
    decision = wired.decide_review_task.run(
        task_id,
        body.decision,
        by=actor_of(reviewer, body.actor_id),
        note=body.note,
        high_impact=body.high_impact,
    )
    return TaskDecisionOut.from_decision(decision)


@router.get(
    "/review/stats",
    summary="The review queue in numbers: counts, decisions, time to decide and queue age",
    dependencies=[ReviewRead],
    responses=problem_responses(401, 403),
)
def review_stats(wired: Wired) -> ReviewStatsOut:
    return ReviewStatsOut.from_stats(wired.read_review_stats.run(), utc_now())
