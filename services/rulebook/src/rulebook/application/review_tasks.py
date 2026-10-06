"""Review tasks: the queue analysts work through, and the decisions that move a rule version.

- ``OpenSeedReviewTasks``: one task of kind ``seed`` for every seed draft that needs review and
  has no task waiting (open or claimed). Running it again opens nothing new: the partial unique
  index, and the memory store's equivalent, keep one waiting task per version, so even two
  concurrent requests open one. A draft made from a rule candidate never gets a seed task: its
  candidate's task reviews it.
- ``ListReviewTasks``: the queue by regulator, higher priority first, then oldest first, with a
  status, a regulator and a kind filter, a page at a time.
- ``ClaimReviewTask``: an analyst takes a task; the claimant claiming again changes nothing.
- ``ReadReviewTask``: the task with its version (content, the specification described, the
  citations and their verification, the documents they cite, the approvers of its current
  round) and the history: the version's decision audit and every task it has had. A candidate
  task also carries its candidate: the stored extraction, its document, the draft it proposes
  and what does not map, and why it looks high impact.
- ``DraftFromCandidate``: the claimant of a candidate task drafts a version from the candidate,
  in one transaction: the rule when it is new (an unused key, with its regulator and level),
  then the next version of the rule as a draft that names the candidate and starts high impact
  when the candidate looks it. Its content is the candidate's (``intake.draft_content``) with
  the analyst's edits, checked as an edit is (``intake.drafted_content``), so what does not map
  or fails the checks is ``DraftIncompleteError`` with every problem. Its citations are the
  candidate's own quotes, or the ones the analyst sends, through ``add_citations``, which
  verifies each against its stored clause. The relation candidates the analyst picks, from the
  candidate's document, are approved onto the draft (``approve_relation``). What the analyst
  changed from the candidate is one ``edited`` row of the decision audit; a candidate taken as
  it was records none. The candidate becomes ``drafted`` and the task keeps the version. A
  candidate is drafted once (``CandidateAlreadyDraftedError``).
- ``EditReviewDraft``: the claimant changes the draft's content and cites clauses, in one
  transaction. Citations go through ``add_citations``, the step ``PUT .../citations`` runs, so
  every quote is verified against its stored clause; the content is checked as the seed loader
  checks the calendar (``drafting.edited_record``). The edit is recorded in the decision audit
  as ``edited``, with what changed, and the seed command leaves an edited draft alone. A
  candidate task not drafted yet has no draft to edit (``CandidateNotDraftedError``).
- ``DecideReviewTask``: approve, return or reject, in one transaction with the version's
  transition (``submit_for_review``, ``approve_version``, ``return_to_draft`` in the decision's
  unit of work).
  - approve: a draft is submitted first (with ``high_impact`` when the reviewer raises it; a
    tag, once set, stays), then approved. The approvers are counted from the decision audit
    alone, and the same person twice is ``DuplicateApproverError``. When the approval completes
    the round (one approver, two different ones for a high-impact version) the version is
    approved and the task decided, and a candidate task's candidate is approved; otherwise the
    task is open again, unclaimed, for a second reviewer. Approving never publishes:
    ``POST .../rule-versions/{id}/publish`` stays the step that does, as before.
  - return: a version under review or approved goes back to draft (its round's approvals stop
    counting); a draft stays a draft. The task is decided and a new open task asks for the
    version's next review (a candidate task's names the candidate too).
  - reject: the task is decided and no new one opens; a version under review or approved goes
    back to draft, a draft stays a draft, and a version the publish routes moved on is left
    as it is. The next ``OpenSeedReviewTasks`` opens a new task for a rejected seed draft. A
    candidate task's rejection names its reason and rejects the candidate, before drafting or
    after, and ``rule.rejected`` goes out through the outbox in the same transaction. After
    drafting, the relation candidates approved onto the draft are open again with a note saying
    why, and their ``rule_relation`` rows are deleted (``relations.reopen_relations``), so a
    corrected draft can take them.
  A candidate task not drafted yet can only be rejected (``CandidateNotDraftedError``). A
  return or a rejection says why in its note.
- ``ReadReviewStats``: counts by status and regulator, the decisions made, the median time to
  decide, the age of the oldest task waiting, and how the decided candidates went.

Who acts is the caller's business (``api.deps``): the verified user of a token, or the body's
actor with the review token in header and dual mode.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from domain_kernel.documents import clause_id_for
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import CorrelationId, EventId, RuleId, RuleVersionId, UserId
from domain_kernel.ontology import AttributeLevel, Ontology
from domain_kernel.status import RULE_VERSION_TRANSITIONS, RuleVersionStatus
from rulebook.application.alignment import Clock, default_clock
from rulebook.application.publication import (
    MAX_CITATIONS,
    CitationInput,
    VersionState,
    add_citations,
    approve_version,
    return_to_draft,
    submit_for_review,
)
from rulebook.application.relations import approve_relation, reopen_relations
from rulebook.domain.documents import StoredDocument
from rulebook.domain.drafting import DraftEdit, described_paths, edited_record
from rulebook.domain.errors import (
    CandidateAlreadyDraftedError,
    CandidateNotDraftedError,
    DraftIncompleteError,
    ReviewTaskClosedError,
    ReviewTaskNotFoundError,
    RuleCandidateNotFoundError,
    RuleKeyTakenError,
    RuleKeyUnknownError,
    RuleVersionNotEditableError,
    UnknownRuleVersionError,
)
from rulebook.domain.events import RuleRejected
from rulebook.domain.intake import (
    MAX_RULE_KEY,
    RULE_KEY,
    DraftContent,
    DraftedContent,
    RuleCandidate,
    RuleRejectReason,
    draft_content,
    drafted_content,
)
from rulebook.domain.publication import DecisionAction, RuleVersionDecision, required_approvals
from rulebook.domain.relations import EDITABLE_FROM_STATUSES
from rulebook.domain.repository import KnowledgeUnitOfWork, KnowledgeUnitOfWorkFactory
from rulebook.domain.review_tasks import (
    MAX_PAGE,
    QueuedTask,
    ReviewDecision,
    ReviewTask,
    ReviewTaskKind,
    ReviewTaskStats,
    ReviewTaskStatus,
    TaskKey,
    TaskQuery,
    describe_specification,
)
from rulebook.domain.rule_versions import CitationRecord, RuleVersionRecord
from rulebook.domain.seed import SeedStatus

RETURNABLE = frozenset({RuleVersionStatus.IN_REVIEW, RuleVersionStatus.APPROVED})
"""The statuses a return or a rejection sends back to draft."""
ONE_MICROSECOND = timedelta(microseconds=1)
MAX_RELATIONS = 50
"""Relation candidates approved onto one draft at most."""


@dataclass(frozen=True, slots=True)
class CandidateDetail:
    """A candidate task's candidate as a reviewer reads it: the stored candidate, its document
    (for the link to the stored file), the draft it proposes with what does not map, why it
    looks high impact, and whether a rule has the suggested key."""

    candidate: RuleCandidate
    document: StoredDocument | None
    proposed: DraftContent
    high_impact_reasons: tuple[str, ...]
    suggested_rule_known: bool


@dataclass(frozen=True, slots=True)
class TaskDetail:
    """A task with what a reviewer needs to decide it. A candidate task not drafted yet has no
    version: no content, citations, documents, approvers or decisions."""

    task: ReviewTask
    version: RuleVersionRecord | None
    specification_described: tuple[str, ...]
    citations: tuple[CitationRecord, ...]
    documents: tuple[StoredDocument, ...]
    """The documents the citations cite, in citation order."""
    approvers: tuple[UserId, ...]
    """Who approved the version's current review round; empty while it is a draft."""
    decisions: tuple[RuleVersionDecision, ...]
    """The version's decision audit, oldest first."""
    tasks: tuple[ReviewTask, ...]
    """Every task the version (or the candidate, before drafting) has had, oldest first, this
    one among them."""
    candidate: CandidateDetail | None = None

    @property
    def required_approvals(self) -> int:
        """One approver, two different ones for a high-impact version; before drafting, as the
        candidate suggests."""
        if self.version is not None:
            return required_approvals(self.version.high_impact)
        suggested = self.candidate is not None and self.candidate.candidate.high_impact_suggested
        return required_approvals(suggested)


@dataclass(frozen=True, slots=True)
class SeedTasks:
    opened: tuple[ReviewTask, ...]


@dataclass(frozen=True, slots=True)
class TaskDecision:
    """What a decision did: the task as it stands now (decided, or open again for a second
    approver), the version after its transition (None for a candidate rejected before it was
    drafted), the task a return opened, a candidate task's candidate, the events written, and
    the relation candidates a rejection after drafting opened again."""

    task: ReviewTask
    version: VersionState | None
    next_task: ReviewTask | None = None
    candidate: RuleCandidate | None = None
    events: tuple[RuleRejected, ...] = ()
    reopened_relations: tuple[UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class NewRule:
    """The rule a draft from a candidate starts, when its key is new: the regulator (the
    candidate's, in lower case) and the level it applies at."""

    regulator: str
    level: AttributeLevel


@dataclass(frozen=True, slots=True)
class RelationChoice:
    """A relation candidate of the candidate's document to approve onto the new draft, with the
    rule version it targets when the relation needs one."""

    candidate_id: UUID
    target_rule_version_id: RuleVersionId | None = None


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


def _not_drafted(task: ReviewTask) -> CandidateNotDraftedError:
    return CandidateNotDraftedError(
        f"review task {task.task_id} has no version yet: draft one from its candidate first "
        "(POST .../review/tasks/{task_id}/draft), or reject the candidate"
    )


def _drafted_version(uow: KnowledgeUnitOfWork, task: ReviewTask) -> RuleVersionRecord:
    """The task's version, locked; a candidate task not drafted yet has none."""
    if task.rule_version_id is None:
        raise _not_drafted(task)
    return _version(uow, task.rule_version_id)


def _candidate(uow: KnowledgeUnitOfWork, candidate_id: UUID, *, lock: bool) -> RuleCandidate:
    found = (
        uow.rule_candidates.lock(candidate_id) if lock else uow.rule_candidates.get(candidate_id)
    )
    if found is None:
        raise RuleCandidateNotFoundError(f"no rule candidate has the id {candidate_id}")
    return found


def _approvers(uow: KnowledgeUnitOfWork, version: RuleVersionRecord) -> tuple[UserId, ...]:
    if version.submitted_at is None:
        return ()
    found = uow.rule_versions.approvers(version.rule_version_id, version.submitted_at)
    return tuple(sorted(found, key=str))


def candidate_detail(uow: KnowledgeUnitOfWork, candidate: RuleCandidate) -> CandidateDetail:
    key = candidate.suggested_rule_key
    return CandidateDetail(
        candidate=candidate,
        document=uow.documents.get(candidate.document_id),
        proposed=draft_content(candidate.fields),
        high_impact_reasons=candidate.high_impact_reasons,
        suggested_rule_known=key is not None and uow.rules.rule_id(key) is not None,
    )


def task_detail(uow: KnowledgeUnitOfWork, task: ReviewTask) -> TaskDetail:
    candidate = (
        None
        if task.candidate_id is None
        else candidate_detail(uow, _candidate(uow, task.candidate_id, lock=False))
    )
    if task.rule_version_id is None:
        assert task.candidate_id is not None, "a task without a version names its candidate"
        return TaskDetail(
            task=task,
            version=None,
            specification_described=(),
            citations=(),
            documents=(),
            approvers=(),
            decisions=(),
            tasks=uow.review_tasks.of_candidate(task.candidate_id),
            candidate=candidate,
        )
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
        candidate=candidate,
    )


class OpenSeedReviewTasks:
    def __init__(self, unit_of_work: KnowledgeUnitOfWorkFactory, clock: Clock = default_clock):
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run(self) -> SeedTasks:
        """The drafts are opened a microsecond apart in rule key order, so the queue lists one
        request's tasks by rule key rather than by their random ids."""
        now = self._clock()
        opened: list[ReviewTask] = []
        with self._unit_of_work() as uow:
            for index, draft in enumerate(uow.review_tasks.drafts_without_task()):
                task = ReviewTask.seed(draft, at=now + index * ONE_MICROSECOND)
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
        kind: ReviewTaskKind | None = None,
    ) -> Sequence[QueuedTask]:
        query = TaskQuery(
            status=status,
            regulator=regulator,
            after=after,
            limit=min(max(limit, 1), MAX_PAGE + 1),
            kind=kind,
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


class DraftFromCandidate:
    """The claimant drafts a version from the task's candidate: the rule when new, the version,
    its citations and the relations picked, all or nothing."""

    def __init__(
        self,
        unit_of_work: KnowledgeUnitOfWorkFactory,
        ontology: Callable[[], Ontology],
        clock: Clock = default_clock,
    ) -> None:
        """``ontology`` gives the ontology the content is checked against, read when the first
        draft needs it."""
        self._unit_of_work = unit_of_work
        self._ontology = ontology
        self._clock = clock

    def run(
        self,
        task_id: UUID,
        *,
        by: UserId,
        rule_key: str,
        new_rule: NewRule | None = None,
        edit: DraftEdit | None = None,
        citations: Sequence[CitationInput] | None = None,
        relations: Sequence[RelationChoice] = (),
        note: str = "",
    ) -> TaskDetail:
        """``citations`` None cites the candidate's own quotes; a list cites exactly those (an
        empty one, none for now)."""
        key = rule_key.strip()
        if len(key) > MAX_RULE_KEY or not RULE_KEY.fullmatch(key):
            raise InvariantViolationError(
                f"rule_key {rule_key!r} must be lowercase snake_case of at most "
                f"{MAX_RULE_KEY} characters"
            )
        if citations is not None and len(citations) > MAX_CITATIONS:
            raise InvariantViolationError(f"cite at most {MAX_CITATIONS} clauses at a time")
        if len(relations) > MAX_RELATIONS:
            raise InvariantViolationError(f"approve at most {MAX_RELATIONS} relations at a time")
        if len({choice.candidate_id for choice in relations}) != len(relations):
            raise InvariantViolationError("a relation candidate is picked once")
        now = self._clock()
        with self._unit_of_work() as uow:
            task = _task(uow, task_id, lock=True)
            task.require_claimant(by)
            if task.kind is not ReviewTaskKind.CANDIDATE or task.candidate_id is None:
                raise InvariantViolationError(
                    f"review task {task_id} is a {task.kind.value} task: a version is drafted "
                    "from a candidate task's candidate"
                )
            candidate = _candidate(uow, task.candidate_id, lock=True)
            if not task.drafts_pending:
                raise CandidateAlreadyDraftedError(
                    f"rule candidate {candidate.candidate_id} was drafted into version "
                    f"{task.rule_version_id}: edit it with PATCH .../draft"
                )
            proposed = draft_content(candidate.fields)
            content = self._content(proposed, edit, citations)
            cited = self._citations(candidate, proposed, citations)
            record = self._record(uow, candidate, key, new_rule, content)
            uow.rule_versions.add_rule_and_version(record, new_rule=new_rule is not None)
            if cited:
                add_citations(uow, record.rule_version_id, cited, now=now)
            for choice in relations:
                relation = uow.candidates.lock(choice.candidate_id)
                if relation is not None and relation.document_id != candidate.document_id:
                    raise InvariantViolationError(
                        f"relation candidate {choice.candidate_id} is about another document "
                        f"than rule candidate {candidate.candidate_id}"
                    )
                approve_relation(
                    uow,
                    choice.candidate_id,
                    record.rule_version_id,
                    choice.target_rule_version_id,
                    decided_by=str(by),
                    now=now,
                    note=f"approved onto the draft of rule candidate {candidate.candidate_id}",
                )
            changed = list(content.changed)
            if citations is not None and _quotes(cited) != _quotes(
                self._citations(candidate, proposed, None)
            ):
                changed.append("citations")
            if changed:
                uow.rule_versions.record_decision(
                    RuleVersionDecision(
                        decision_id=uuid4(),
                        rule_version_id=record.rule_version_id,
                        action=DecisionAction.EDITED,
                        from_status=RuleVersionStatus.DRAFT,
                        to_status=RuleVersionStatus.DRAFT,
                        decided_at=now,
                        actor_id=by,
                        note=_draft_note(candidate, changed, note),
                    )
                )
            uow.rule_candidates.save(candidate.drafted(record.rule_version_id))
            drafted = task.drafted(record.rule_version_id)
            uow.review_tasks.save(drafted)
            return task_detail(uow, drafted)

    def _content(
        self,
        proposed: DraftContent,
        edit: DraftEdit | None,
        citations: Sequence[CitationInput] | None,
    ) -> DraftedContent:
        """The checked content, with every problem of the content and of the candidate's own
        citations (when they are the ones to cite) reported at once."""
        problems: list[str] = []
        if citations is None and proposed.citation_problems:
            problems = [
                *(f"citations: {problem}" for problem in proposed.citation_problems),
                "citations: send the citations to cite instead",
            ]
        try:
            content = drafted_content(proposed, edit, self._ontology())
        except DraftIncompleteError as exc:
            raise DraftIncompleteError([*exc.problems, *problems]) from exc
        if problems:
            raise DraftIncompleteError(problems)
        return content

    @staticmethod
    def _citations(
        candidate: RuleCandidate,
        proposed: DraftContent,
        sent: Sequence[CitationInput] | None,
    ) -> list[CitationInput]:
        """The citations to store: the ones sent, else the candidate's quotes with the ids the
        kernel derives for their clauses in the candidate's document."""
        if sent is not None:
            return list(sent)
        return [
            CitationInput(clause_id_for(candidate.document_id, quote.clause_ref), quote.quote)
            for quote in proposed.citations
        ]

    @staticmethod
    def _record(
        uow: KnowledgeUnitOfWork,
        candidate: RuleCandidate,
        rule_key: str,
        new_rule: NewRule | None,
        content: DraftedContent,
    ) -> RuleVersionRecord:
        """The draft to insert: the next version of the rule with ``rule_key`` (numbered past
        every version it has, a closed draft's too), or the first of a new one."""
        head = uow.rule_versions.lock_rule(rule_key)
        if head is None:
            if new_rule is None:
                raise RuleKeyUnknownError(rule_key)
            rule_id, regulator, level = (
                RuleId.new(),
                new_rule.regulator.strip().lower(),
                new_rule.level,
            )
            number = 1
        else:
            if new_rule is not None:
                raise RuleKeyTakenError(rule_key)
            rule_id, regulator, level = head.rule_id, head.regulator, head.level
            number = head.next_version
        if regulator.lower() != candidate.regulator:
            raise InvariantViolationError(
                f"rule {rule_key} is {regulator}'s and the candidate {candidate.regulator}'s: "
                "a candidate's draft belongs to a rule of its own regulator"
            )
        document = uow.documents.get(candidate.document_id)
        return RuleVersionRecord(
            rule_version_id=RuleVersionId.new(),
            rule_id=rule_id,
            rule_key=rule_key,
            regulator=regulator,
            level=level,
            version=number,
            status=RuleVersionStatus.DRAFT,
            title=content.title,
            summary=content.summary,
            specification=content.specification,
            obligation_template=content.obligation_template,
            recurrence=content.recurrence,
            effective_from=content.effective_from,
            effective_to=content.effective_to,
            source=_source_of(candidate, document),
            seed_status=SeedStatus.NEEDS_REVIEW,
            todo=content.todo,
            high_impact=candidate.high_impact_suggested,
            candidate_id=candidate.candidate_id,
        )


def _source_of(candidate: RuleCandidate, document: StoredDocument | None) -> dict[str, object]:
    """Where a draft from a candidate comes from, in the seed calendar's source shape, with the
    candidate it was drafted from."""
    reference = "" if document is None else document.external_ref
    return {
        "instrument": "" if document is None else document.title,
        "reference": reference,
        "note": (
            f"drafted from rule candidate {candidate.candidate_id} "
            f"({candidate.prompt_version}, {candidate.model})"
        ),
        "url": "" if document is None else document.url,
        "document_id": str(candidate.document_id),
        "candidate_id": str(candidate.candidate_id),
    }


def _quotes(citations: Sequence[CitationInput]) -> frozenset[tuple[str, str]]:
    return frozenset((str(citation.clause_id), citation.quote) for citation in citations)


def _draft_note(candidate: RuleCandidate, changed: Sequence[str], note: str) -> str:
    """``drafted from rule candidate <id>, changed title, citations: <the analyst's note>``."""
    text = (
        f"drafted from rule candidate {candidate.candidate_id}, changed {described_paths(changed)}"
    )
    return f"{text}: {note}" if note else text


def _reopen_note(candidate: RuleCandidate, rule_version_id: RuleVersionId, by: UserId) -> str:
    """Why a relation candidate approved onto a candidate's draft is open again."""
    reason = "" if candidate.reject_reason is None else f" ({candidate.reject_reason.value})"
    return (
        f"reopened: rule candidate {candidate.candidate_id} was rejected{reason} by {by}, so "
        f"its draft {rule_version_id} no longer carries this relation; approve it onto another "
        "draft"
    )


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
            version = _drafted_version(uow, task)
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
        reason: RuleRejectReason | None = None,
    ) -> TaskDecision:
        if high_impact and decision is not ReviewDecision.APPROVE:
            raise InvariantViolationError("high_impact is raised with an approval")
        if decision is not ReviewDecision.APPROVE and not note.strip():
            raise InvariantViolationError(f"a {decision.value} says why in its note")
        if reason is not None and decision is not ReviewDecision.REJECT:
            raise InvariantViolationError("a reason is given with a rejection")
        now = self._clock()
        with self._unit_of_work() as uow:
            task = _task(uow, task_id, lock=True)
            if not task.undecided:
                raise ReviewTaskClosedError(
                    f"review task {task_id} was decided ({task.decision}) and never changes"
                )
            candidate = None
            if task.candidate_id is not None:
                candidate = _candidate(uow, task.candidate_id, lock=True)
                if decision is ReviewDecision.REJECT and reason is None:
                    raise InvariantViolationError(
                        "a candidate's rejection names its reason: "
                        + ", ".join(reason.value for reason in RuleRejectReason)
                    )
            elif reason is not None:
                raise InvariantViolationError("only a candidate task's rejection takes a reason")
            if candidate is not None and task.rule_version_id is None:
                if decision is not ReviewDecision.REJECT:
                    raise _not_drafted(task)
                return self._reject_candidate(uow, task, candidate, None, by, now, note, reason)
            version = _drafted_version(uow, task)
            if decision is ReviewDecision.APPROVE:
                state, at = self._approve(uow, version, by=by, note=note, high_impact=high_impact)
                done = state.record.status is RuleVersionStatus.APPROVED
                after = task.decide(decision, by=by, at=at, note=note) if done else task.release()
                uow.review_tasks.save(after)
                if done and candidate is not None:
                    candidate = candidate.approved(by=by, at=at)
                    uow.rule_candidates.save(candidate)
                return TaskDecision(after, state, candidate=candidate)
            state = self._send_back(uow, version, decision, by=by, note=note, now=now)
            if decision is ReviewDecision.REJECT and candidate is not None:
                return self._reject_candidate(uow, task, candidate, state, by, now, note, reason)
            after = task.decide(decision, by=by, at=now, note=note)
            uow.review_tasks.save(after)
            following = None
            if decision is ReviewDecision.RETURN:
                following = after.next_round(at=now)
                if not uow.review_tasks.add(following):  # pragma: no cover - decided just now
                    following = None
            return TaskDecision(after, state, following, candidate=candidate)

    @staticmethod
    def _reject_candidate(
        uow: KnowledgeUnitOfWork,
        task: ReviewTask,
        candidate: RuleCandidate,
        state: VersionState | None,
        by: UserId,
        now: datetime,
        note: str,
        reason: RuleRejectReason | None,
    ) -> TaskDecision:
        """The task decided, the candidate rejected and ``rule.rejected`` in the outbox, in the
        decision's transaction. A version drafted from the candidate stays a draft, and the
        relation candidates approved onto it are open again (``relations.reopen_relations``),
        their ``rule_relation`` rows deleted, so they can reach another draft."""
        assert reason is not None, "a candidate's rejection names its reason"
        after = task.decide(ReviewDecision.REJECT, by=by, at=now, note=note)
        uow.review_tasks.save(after)
        rejected = candidate.rejected(reason, by=by, at=now)
        uow.rule_candidates.save(rejected)
        reopened: tuple[UUID, ...] = ()
        if state is not None and state.record.status is RuleVersionStatus.DRAFT:
            reopened = reopen_relations(
                uow,
                state.record.rule_version_id,
                note=_reopen_note(rejected, state.record.rule_version_id, by),
            )
        event = RuleRejected(
            occurred_at=now,
            correlation_id=CorrelationId.new(),
            causation_id=EventId(candidate.event_id),
            candidate_id=candidate.candidate_id,
            document_id=candidate.document_id,
            regulator=candidate.regulator,
            reason=reason,
            prompt_version=candidate.prompt_version,
            model=candidate.model,
            rule_version_id=candidate.rule_version_id,
        )
        uow.events.publish(event)
        return TaskDecision(
            after, state, candidate=rejected, events=(event,), reopened_relations=reopened
        )

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
