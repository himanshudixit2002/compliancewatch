"""Review tasks: the queue of rule versions, and of rule candidates to draft versions from,
waiting for an analyst's decision, and the decisions.

Reads need a regulatory role a token names (``ReviewRead``; open without a token in header and
dual mode, as the other review queues). An analyst claims a task, drafts a version from a
candidate task's candidate and edits the draft (``AnalystWork``); an analyst, a reviewer or an
admin decides it and opens the seed tasks (``AnalystWrite``). Without a bearer, in header and
dual mode, the review token opens the writes and the body names the actor; a signed-in user is
the actor whatever the body says, so the two approvals of a high-impact version come from two
people.
"""

import hashlib
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
    DraftFromCandidateIn,
    QueuedTaskOut,
    ReviewStatsOut,
    ReviewTaskDetailOut,
    ReviewTaskOut,
    SeedTasksOut,
    TaskCursor,
    TaskDecisionOut,
)
from rulebook.domain.review_tasks import ReviewTaskKind, ReviewTaskStatus

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
        str | None,
        Query(min_length=1, max_length=40, description="Only this regulator's, in any case"),
    ] = None,
    kind: Annotated[ReviewTaskKind | None, Query(description="Only tasks of this kind")] = None,
) -> Page[QueuedTaskOut]:
    """Each task with its version's rule, number, title and status, whether it is high impact
    and how many people approved its current round. A task open again after the first of two
    approvals waits for a second, different reviewer. A candidate task not drafted yet shows its
    candidate's title, suggested rule key and suggested impact; ``candidate`` summarises the
    candidate of every candidate task."""
    regulator = None if regulator is None else regulator.strip().lower()
    scope = f"{TASKS_SCOPE}.{status or 'any'}.{_regulator_scope(regulator)}"
    if kind is not None:
        scope = f"{scope}.{kind.value}"
    after = page.after(scope, TaskCursor)
    found = wired.list_review_tasks.run(
        status=status,
        regulator=regulator,
        after=None if after is None else after.key(),
        limit=page.limit + 1,
        kind=kind,
    )
    kept, cursor = page_of(found, page.limit, scope, TaskCursor.of)
    return Page[QueuedTaskOut](
        items=[QueuedTaskOut.from_queued(queued) for queued in kept], next_cursor=cursor
    )


def _regulator_scope(regulator: str | None) -> str:
    """The regulator filter in a cursor's scope, as a short digest so any name fits a cursor."""
    if regulator is None:
        return "any"
    return hashlib.sha256(regulator.encode("utf-8")).hexdigest()[:16]


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
    audit and every task it has had. A candidate task also carries its candidate: the
    extraction as stored, its document (the stored file is at the pipeline's ``GET
    /v1/pipeline/documents/{document_id}/raw``), the draft it proposes and what does not map,
    why it looks high impact, and whether a rule has its suggested key; until it is drafted the
    task has no version."""
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


@router.post(
    "/review/tasks/{task_id}/draft",
    summary="Draft a version from a candidate task's candidate, cited and with its relations",
    responses=problem_responses(401, 403, 404, 409, 422, 503),
)
def draft_from_candidate(
    task_id: UUID, body: DraftFromCandidateIn, analyst: AnalystWork, wired: Wired
) -> ReviewTaskDetailOut:
    """Only the analyst who claimed the task (409 rulebook-review-task-not-claimed), once per
    candidate (409 rulebook-candidate-already-drafted). The version is the next of the rule
    ``rule_key`` names, or the first of a new rule when ``new_rule`` gives its regulator and
    level (404 rulebook-rule-key-unknown without it; 409 rulebook-rule-key-taken with it for a
    key a rule has). It is a draft that names the candidate and starts high impact when the
    candidate suggests it. Its content is the candidate's with ``edits`` applied, checked as the
    seed calendar is: what is missing, does not map or fails the checks is 422
    rulebook-draft-incomplete, every problem in the detail, and nothing is stored. The citations
    (the candidate's quotes, or ``citations``) are verified against their clauses (422
    rulebook-citation-not-verified), and each relation candidate listed, of the candidate's
    document, is approved onto the draft. What the analyst changed from the candidate is an
    edited row of the decision audit."""
    detail = wired.draft_from_candidate.run(
        task_id,
        by=actor_of(analyst, body.actor_id),
        rule_key=body.rule_key,
        new_rule=None if body.new_rule is None else body.new_rule.to_new_rule(),
        edit=None if body.edits is None else body.edits.to_edit(),
        citations=body.to_citations(),
        relations=[choice.to_choice() for choice in body.relation_candidates],
        note=body.note,
    )
    return ReviewTaskDetailOut.from_detail(detail)


@router.patch(
    "/review/tasks/{task_id}/draft",
    summary="Edit the draft of a claimed task: its content and citations, every quote verified",
    responses=problem_responses(401, 403, 404, 409, 422, 503),
)
def edit_review_draft(
    task_id: UUID, body: DraftEditIn, analyst: AnalystWork, wired: Wired
) -> ReviewTaskDetailOut:
    """Only the analyst who claimed the task (409 rulebook-review-task-not-claimed), only while
    the version is a draft (409 rulebook-rule-version-not-editable), and for a candidate task
    once a version is drafted (409 rulebook-candidate-not-drafted). Content is checked against
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
    the task and leaves the version a draft. Both need a note. A candidate task's approval of
    the round approves its candidate; its rejection names a reason, rejects the candidate before
    or after drafting and writes rule.rejected; before drafting it can only be rejected (409
    rulebook-candidate-not-drafted). A draft whose candidate is rejected is closed: it stays a
    draft, is never cited, submitted, approved or published (409 rulebook-rule-version-closed)
    and is no longer its rule's latest version, and the relation candidates approved onto it are
    open again, their rule relations deleted, for another draft to take."""
    decision = wired.decide_review_task.run(
        task_id,
        body.decision,
        by=actor_of(reviewer, body.actor_id),
        note=body.note,
        high_impact=body.high_impact,
        reason=body.reason,
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
