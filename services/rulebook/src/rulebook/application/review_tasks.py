"""Review tasks: the queue analysts work through, and the decisions that move a rule version.

- ``OpenSeedReviewTasks``: one task of kind ``seed`` for every draft that needs review and has
  no task waiting (open or claimed). Running it again opens nothing new: the partial unique
  index, and the memory store's equivalent, keep one waiting task per version, so even two
  concurrent requests open one.
- ``ListReviewTasks``: the queue by regulator, higher priority first, then oldest first, with a
  status and a regulator filter, a page at a time.
- ``ClaimReviewTask``: an analyst takes a task; the claimant claiming again changes nothing.
- ``ReadReviewTask``: the task with its version (content, the specification described, the
  citations and their verification, the documents they cite, the approvers of its current
  round) and the history: the version's decision audit and every task it has had.
- ``EditReviewDraft``: the claimant changes the draft's content and cites clauses, in one
  transaction. Citations go through ``add_citations``, the step ``PUT .../citations`` runs, so
  every quote is verified against its stored clause; the content is checked as the seed loader
  checks the calendar (``review_tasks.edited_record``). The edit is recorded in the decision
  audit as ``edited``, with what changed, and the seed command leaves an edited draft alone.
- ``DecideReviewTask``: approve, return or reject, in one transaction with the version's
  transition (``submit_for_review``, ``approve_version``, ``return_to_draft`` in the decision's
  unit of work).
  - approve: a draft is submitted first (with ``high_impact`` when the reviewer raises it; a
    tag, once set, stays), then approved. The approvers are counted from the decision audit
    alone, and the same person twice is ``DuplicateApproverError``. When the approval completes
    the round (one approver, two different ones for a high-impact version) the version is
    approved and the task decided; otherwise the task is open again, unclaimed, for a second
    reviewer. Approving never publishes: ``POST .../rule-versions/{id}/publish`` stays the
    step that does, as before.
  - return: a version under review or approved goes back to draft (its round's approvals stop
    counting); a draft stays a draft. The task is decided and a new open task asks for the
    version's next review.
  - reject: the task is decided and no new one opens; a version under review or approved goes
    back to draft, a draft stays a draft, and a version the publish routes moved on is left
    as it is. The next ``OpenSeedReviewTasks`` opens a new task for a rejected draft.
  A return or a rejection says why in its note.
- ``ReadReviewStats``: counts by status and regulator, the decisions made, the median time to
  decide and the age of the oldest task waiting.

Who acts is the caller's business (``api.deps``): the verified user of a token, or the body's
actor with the review token in header and dual mode.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import RuleVersionId, UserId
from domain_kernel.ontology import Ontology
from domain_kernel.status import RULE_VERSION_TRANSITIONS, RuleVersionStatus
from rulebook.application.alignment import Clock, default_clock
from rulebook.application.publication import (
    CitationInput,
    VersionState,
    add_citations,
    approve_version,
    return_to_draft,
    submit_for_review,
)
from rulebook.domain.documents import StoredDocument
from rulebook.domain.errors import (
    ReviewTaskClosedError,
    ReviewTaskNotFoundError,
    RuleVersionNotEditableError,
    UnknownRuleVersionError,
)
from rulebook.domain.publication import DecisionAction, RuleVersionDecision, required_approvals
from rulebook.domain.relations import EDITABLE_FROM_STATUSES
from rulebook.domain.repository import KnowledgeUnitOfWork, KnowledgeUnitOfWorkFactory
from rulebook.domain.review_tasks import (
    MAX_PAGE,
    DraftEdit,
    QueuedTask,
    ReviewDecision,
    ReviewTask,
    ReviewTaskStats,
    ReviewTaskStatus,
    TaskKey,
    TaskQuery,
    describe_specification,
    edited_record,
)
from rulebook.domain.rule_versions import CitationRecord, RuleVersionRecord

RETURNABLE = frozenset({RuleVersionStatus.IN_REVIEW, RuleVersionStatus.APPROVED})
"""The statuses a return or a rejection sends back to draft."""
ONE_MICROSECOND = timedelta(microseconds=1)


@dataclass(frozen=True, slots=True)
class TaskDetail:
    """A task with what a reviewer needs to decide it."""

    task: ReviewTask
    version: RuleVersionRecord
    specification_described: tuple[str, ...]
    citations: tuple[CitationRecord, ...]
    documents: tuple[StoredDocument, ...]
    """The documents the citations cite, in citation order."""
    approvers: tuple[UserId, ...]
    """Who approved the version's current review round; empty while it is a draft."""
    decisions: tuple[RuleVersionDecision, ...]
    """The version's decision audit, oldest first."""
    tasks: tuple[ReviewTask, ...]
    """Every task the version has had, oldest first, this one among them."""

    @property
    def required_approvals(self) -> int:
        return required_approvals(self.version.high_impact)


@dataclass(frozen=True, slots=True)
class SeedTasks:
    opened: tuple[ReviewTask, ...]


@dataclass(frozen=True, slots=True)
class TaskDecision:
    """What a decision did: the task as it stands now (decided, or open again for a second
    approver), the version after its transition, and the task a return opened."""

    task: ReviewTask
    version: VersionState
    next_task: ReviewTask | None = None


def _task(uow: KnowledgeUnitOfWork, task_id: UUID, *, lock: bool) -> ReviewTask:
    found = uow.review_tasks.lock(task_id) if lock else uow.review_tasks.get(task_id)
    if found is None:
        raise ReviewTaskNotFoundError(f"no review task has the id {task_id}")
    return found


def _version(uow: KnowledgeUnitOfWork, rule_version_id: RuleVersionId) -> RuleVersionRecord:
    record = uow.rule_versions.lock(rule_version_id)
    if record is None:
        raise UnknownRuleVersionError(str(rule_version_id))
    return record


def _approvers(uow: KnowledgeUnitOfWork, version: RuleVersionRecord) -> tuple[UserId, ...]:
    if version.submitted_at is None:
        return ()
    found = uow.rule_versions.approvers(version.rule_version_id, version.submitted_at)
    return tuple(sorted(found, key=str))


def task_detail(uow: KnowledgeUnitOfWork, task: ReviewTask) -> TaskDetail:
    version = uow.rule_versions.get(task.rule_version_id)
    if version is None:
        raise UnknownRuleVersionError(str(task.rule_version_id))
    citations = uow.citations.for_version(task.rule_version_id)
    documents: list[StoredDocument] = []
    for document_id in dict.fromkeys(citation.document_id for citation in citations):
        document = uow.documents.get(document_id)
        if document is not None:
            documents.append(document)
    return TaskDetail(
        task=task,
        version=version,
        specification_described=describe_specification(version.specification),
        citations=citations,
        documents=tuple(documents),
        approvers=_approvers(uow, version),
        decisions=uow.rule_versions.decisions(task.rule_version_id),
        tasks=uow.review_tasks.of_version(task.rule_version_id),
    )


class OpenSeedReviewTasks:
    def __init__(self, unit_of_work: KnowledgeUnitOfWorkFactory, clock: Clock = default_clock):
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run(self) -> SeedTasks:
        now = self._clock()
        opened: list[ReviewTask] = []
        with self._unit_of_work() as uow:
            for draft in uow.review_tasks.drafts_without_task():
                task = ReviewTask.seed(draft, at=now)
                if uow.review_tasks.add(task):
                    opened.append(task)
        return SeedTasks(tuple(opened))


class ListReviewTasks:
    def __init__(self, unit_of_work: KnowledgeUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(
        self,
        *,
        status: ReviewTaskStatus | None = None,
        regulator: str | None = None,
        after: TaskKey | None = None,
        limit: int = 50,
    ) -> Sequence[QueuedTask]:
        query = TaskQuery(
            status=status,
            regulator=regulator,
            after=after,
            limit=min(max(limit, 1), MAX_PAGE + 1),
        )
        with self._unit_of_work() as uow:
            return uow.review_tasks.page(query)


class ClaimReviewTask:
    def __init__(self, unit_of_work: KnowledgeUnitOfWorkFactory, clock: Clock = default_clock):
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run(self, task_id: UUID, *, by: UserId) -> ReviewTask:
        now = self._clock()
        with self._unit_of_work() as uow:
            task = _task(uow, task_id, lock=True)
            claimed = task.claim(by, now)
            if claimed != task:
                uow.review_tasks.save(claimed)
            return claimed


class ReadReviewTask:
    def __init__(self, unit_of_work: KnowledgeUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self, task_id: UUID) -> TaskDetail:
        with self._unit_of_work() as uow:
            return task_detail(uow, _task(uow, task_id, lock=False))


class EditReviewDraft:
    """The claimant's change to the draft: content (``edit``) and citations, at least one of
    them, all or nothing."""

    def __init__(
        self,
        unit_of_work: KnowledgeUnitOfWorkFactory,
        ontology: Callable[[], Ontology],
        clock: Clock = default_clock,
    ) -> None:
        """``ontology`` gives the ontology the content is checked against, read when the first
        edit needs it."""
        self._unit_of_work = unit_of_work
        self._ontology = ontology
        self._clock = clock

    def run(
        self,
        task_id: UUID,
        *,
        by: UserId,
        edit: DraftEdit | None = None,
        citations: Sequence[CitationInput] = (),
        note: str = "",
    ) -> TaskDetail:
        if (edit is None or not edit.changes) and not citations:
            raise InvariantViolationError("an edit changes the content or cites clauses")
        now = self._clock()
        with self._unit_of_work() as uow:
            task = _task(uow, task_id, lock=True)
            task.require_claimant(by)
            version = _version(uow, task.rule_version_id)
            if version.status not in EDITABLE_FROM_STATUSES:
                raise RuleVersionNotEditableError(
                    f"rule version {version.rule_version_id} is {version.status.value}: a version "
                    "under review or approved is returned to draft before it is edited"
                )
            changed: tuple[str, ...] = ()
            if edit is not None and edit.changes:
                edited, changed = edited_record(version, edit, self._ontology())
                if changed:
                    uow.rule_versions.save_draft(edited)
            added = 0
            if citations:
                added = add_citations(uow, version.rule_version_id, citations, now=now).added
            if changed or added:
                uow.rule_versions.record_decision(
                    RuleVersionDecision(
                        decision_id=uuid4(),
                        rule_version_id=version.rule_version_id,
                        action=DecisionAction.EDITED,
                        from_status=RuleVersionStatus.DRAFT,
                        to_status=RuleVersionStatus.DRAFT,
                        decided_at=now,
                        actor_id=by,
                        note=_edit_note(changed, added, note),
                    )
                )
            return task_detail(uow, task)


def _edit_note(changed: Sequence[str], added: int, note: str) -> str:
    """``changed title, specification; cited 2 clauses: <the analyst's note>``."""
    parts = []
    if changed:
        parts.append("changed " + ", ".join(changed))
    if added:
        parts.append(f"cited {added} clause" + ("" if added == 1 else "s"))
    text = "; ".join(parts)
    return f"{text}: {note}" if note else text


class DecideReviewTask:
    def __init__(self, unit_of_work: KnowledgeUnitOfWorkFactory, clock: Clock = default_clock):
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run(
        self,
        task_id: UUID,
        decision: ReviewDecision,
        *,
        by: UserId,
        note: str = "",
        high_impact: bool = False,
    ) -> TaskDecision:
        if high_impact and decision is not ReviewDecision.APPROVE:
            raise InvariantViolationError("high_impact is raised with an approval")
        if decision is not ReviewDecision.APPROVE and not note.strip():
            raise InvariantViolationError(f"a {decision.value} says why in its note")
        now = self._clock()
        with self._unit_of_work() as uow:
            task = _task(uow, task_id, lock=True)
            if not task.undecided:
                raise ReviewTaskClosedError(
                    f"review task {task_id} was decided ({task.decision}) and never changes"
                )
            version = _version(uow, task.rule_version_id)
            if decision is ReviewDecision.APPROVE:
                state, at = self._approve(uow, version, by=by, note=note, high_impact=high_impact)
                done = state.record.status is RuleVersionStatus.APPROVED
                after = task.decide(decision, by=by, at=at, note=note) if done else task.release()
                uow.review_tasks.save(after)
                return TaskDecision(after, state)
            state = self._send_back(uow, version, decision, by=by, note=note, now=now)
            after = task.decide(decision, by=by, at=now, note=note)
            uow.review_tasks.save(after)
            following = None
            if decision is ReviewDecision.RETURN:
                following = after.next_round(at=now)
                if not uow.review_tasks.add(following):  # pragma: no cover - decided just now
                    following = None
            return TaskDecision(after, state, following)

    def _approve(
        self,
        uow: KnowledgeUnitOfWork,
        version: RuleVersionRecord,
        *,
        by: UserId,
        note: str,
        high_impact: bool,
    ) -> tuple[VersionState, datetime]:
        """Submit a draft, raise the tag when asked, then approve: each step its own moment, so
        the audit reads in order."""
        moment = self._clock()
        if version.status is RuleVersionStatus.DRAFT:
            submit_for_review(
                uow,
                version.rule_version_id,
                actor_id=by,
                now=moment,
                high_impact=high_impact,
                note=note,
            )
            moment = max(self._clock(), moment + ONE_MICROSECOND)
        elif (
            high_impact
            and not version.high_impact
            and version.status is RuleVersionStatus.IN_REVIEW
        ):
            uow.rule_versions.save_lifecycle(replace(version, high_impact=True))
        state = approve_version(uow, version.rule_version_id, actor_id=by, now=moment, note=note)
        return state, moment

    @staticmethod
    def _send_back(
        uow: KnowledgeUnitOfWork,
        version: RuleVersionRecord,
        decision: ReviewDecision,
        *,
        by: UserId,
        note: str,
        now: datetime,
    ) -> VersionState:
        """A return or a rejection: a version under review or approved goes back to draft."""
        if version.status in RETURNABLE:
            return return_to_draft(uow, version.rule_version_id, actor_id=by, now=now, note=note)
        if version.status is not RuleVersionStatus.DRAFT and decision is ReviewDecision.RETURN:
            RULE_VERSION_TRANSITIONS.assert_transition(version.status, RuleVersionStatus.DRAFT)
        return VersionState(version, _approvers(uow, version))


class ReadReviewStats:
    def __init__(self, unit_of_work: KnowledgeUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self) -> ReviewTaskStats:
        with self._unit_of_work() as uow:
            return uow.review_tasks.stats()
