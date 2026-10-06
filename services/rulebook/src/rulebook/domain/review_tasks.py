"""Review tasks: a rule version, or a rule candidate to draft one from, waiting for an analyst's
decision, queued by regulator and priority.

A task asks for one decision: approve the version, return it for rework, or reject it. It is
opened (``open``), claimed by the analyst who works on it (``claimed``) and decided
(``decided``); a decided task never changes again, which the table's trigger enforces for every
writer. A version has at most one task that is not decided yet, and so has a candidate.

- ``claim``: an analyst takes an open task. The claimant claiming again changes nothing; a task
  someone else holds is refused (``ReviewTaskClaimedError``), and so is a decided one
  (``ReviewTaskClosedError``). Only the claimant edits the draft (``require_claimant``).
- ``drafted``: the claimant drafted a version from the task's candidate; the task keeps that
  version from then on.
- ``release``: the first of the two approvals a high-impact version needs leaves the task open
  again, unclaimed, for a second and different reviewer.
- ``decide``: approve, return or reject, once.

Two kinds of task share the queue:

- ``seed``: a draft the seed calendar wrote that still needs review. Seed tasks share one
  priority, so the queue keeps them in the order they were opened within a regulator.
- ``candidate``: a rule candidate the pipeline extracted (``rulebook.domain.intake``), at the
  candidate's priority and under its regulator. It has no version until the claimant drafts one
  from the candidate; until then it can be claimed and rejected, nothing else.

The content of a draft an analyst edits is checked in ``rulebook.domain.drafting``.
"""

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID, uuid4

from domain_kernel._validation import require_aware, require_instance, require_int, require_text
from domain_kernel.errors import DomainError, InvariantViolationError
from domain_kernel.ids import RuleVersionId, UserId
from domain_kernel.predicates import (
    AllOf,
    AnyOf,
    Not,
    Predicate,
    Specification,
    specification_from_mapping,
)
from domain_kernel.status import RuleVersionStatus
from rulebook.domain.errors import (
    ReviewTaskClaimedError,
    ReviewTaskClosedError,
    ReviewTaskNotClaimedError,
)
from rulebook.domain.intake import CandidateSummary
from rulebook.domain.rule_versions import RuleVersionRecord

SEED_PRIORITY: Final = 50
"""The priority of every seed task: the queue keeps them in the order they were opened."""
MAX_PRIORITY: Final = 1_000
MAX_NOTE: Final = 2_000
MAX_PAGE: Final = 200


class ReviewTaskKind(StrEnum):
    """What a task reviews. ``seed``: a draft the seed calendar wrote. ``candidate``: a rule
    candidate the pipeline extracted, and the version an analyst drafts from it."""

    SEED = "seed"
    CANDIDATE = "candidate"


class ReviewTaskStatus(StrEnum):
    OPEN = "open"
    CLAIMED = "claimed"
    DECIDED = "decided"


UNDECIDED: Final = frozenset({ReviewTaskStatus.OPEN, ReviewTaskStatus.CLAIMED})
"""The statuses of a task in the queue: waiting for a decision, claimed or not."""


class ReviewDecision(StrEnum):
    """What a reviewer decides. ``approve`` counts as an approval of the version's round;
    ``return`` sends the version back to draft for rework and opens the next task for it;
    ``reject`` closes the task and leaves the version a draft."""

    APPROVE = "approve"
    RETURN = "return"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class ReviewTask:
    """One decision asked about one rule version, or about one candidate and the version drafted
    from it. ``regulator`` is the rule's or the candidate's, kept on the task for the queue's
    order and filter. A seed task has its version from the start; a candidate task names its
    candidate, and its version once one is drafted."""

    task_id: UUID
    rule_version_id: RuleVersionId | None
    kind: ReviewTaskKind
    priority: int
    regulator: str
    opened_at: datetime
    status: ReviewTaskStatus = ReviewTaskStatus.OPEN
    claimed_by: UserId | None = None
    claimed_at: datetime | None = None
    decided_by: UserId | None = None
    decided_at: datetime | None = None
    decision: ReviewDecision | None = None
    note: str = ""
    candidate_id: UUID | None = None

    def __post_init__(self) -> None:
        require_instance(self.task_id, UUID, "task_id")
        if self.rule_version_id is not None:
            require_instance(self.rule_version_id, RuleVersionId, "rule_version_id")
        require_instance(self.kind, ReviewTaskKind, "kind")
        if self.kind is ReviewTaskKind.SEED and (
            self.rule_version_id is None or self.candidate_id is not None
        ):
            raise InvariantViolationError("a seed task reviews a version and names no candidate")
        if self.kind is ReviewTaskKind.CANDIDATE:
            require_instance(self.candidate_id, UUID, "candidate_id")
        priority = require_int(self.priority, "priority", minimum=0)
        if priority > MAX_PRIORITY:
            raise InvariantViolationError(f"priority must be at most {MAX_PRIORITY}")
        require_text(self.regulator, "regulator")
        require_aware(self.opened_at, "opened_at")
        require_instance(self.status, ReviewTaskStatus, "status")
        require_instance(self.note, str, "note")
        if (self.claimed_by is None) != (self.claimed_at is None):
            raise InvariantViolationError("a claim names who claimed the task and when")
        if self.claimed_at is not None:
            require_aware(self.claimed_at, "claimed_at")
        if self.status is ReviewTaskStatus.OPEN and self.claimed_by is not None:
            raise InvariantViolationError("an open task has no claimant")
        if self.status is ReviewTaskStatus.CLAIMED and self.claimed_by is None:
            raise InvariantViolationError("a claimed task names its claimant")
        decided = (self.decided_by, self.decided_at, self.decision)
        if self.status is ReviewTaskStatus.DECIDED:
            if any(part is None for part in decided):
                raise InvariantViolationError("a decided task names the decision, who and when")
            require_aware(self.decided_at, "decided_at")
            require_instance(self.decision, ReviewDecision, "decision")
        elif any(part is not None for part in decided):
            raise InvariantViolationError("a task that is not decided carries no decision")

    @classmethod
    def seed(
        cls, version: RuleVersionRecord, *, at: datetime, task_id: UUID | None = None
    ) -> "ReviewTask":
        """The task that asks for the review of a seed draft."""
        return cls(
            task_id=task_id or uuid4(),
            rule_version_id=version.rule_version_id,
            kind=ReviewTaskKind.SEED,
            priority=SEED_PRIORITY,
            regulator=version.regulator,
            opened_at=at,
        )

    @classmethod
    def for_candidate(
        cls,
        candidate_id: UUID,
        *,
        regulator: str,
        priority: int,
        at: datetime,
        task_id: UUID | None = None,
    ) -> "ReviewTask":
        """The task that asks an analyst to draft a version from a candidate and decide it, at
        the candidate's priority and under its regulator; it has no version yet."""
        return cls(
            task_id=task_id or uuid4(),
            rule_version_id=None,
            kind=ReviewTaskKind.CANDIDATE,
            priority=priority,
            regulator=regulator,
            opened_at=at,
            candidate_id=candidate_id,
        )

    @property
    def undecided(self) -> bool:
        return self.status in UNDECIDED

    @property
    def drafts_pending(self) -> bool:
        """Whether this is a candidate task with no version drafted yet."""
        return self.kind is ReviewTaskKind.CANDIDATE and self.rule_version_id is None

    def next_round(self, *, at: datetime, task_id: UUID | None = None) -> "ReviewTask":
        """A new open task for the same version (and candidate), as a return opens for the
        rework."""
        return ReviewTask(
            task_id=task_id or uuid4(),
            rule_version_id=self.rule_version_id,
            kind=self.kind,
            priority=self.priority,
            regulator=self.regulator,
            opened_at=at,
            candidate_id=self.candidate_id,
        )

    def drafted(self, rule_version_id: RuleVersionId) -> "ReviewTask":
        """The candidate task once its claimant drafted a version: the task keeps the version
        from then on."""
        self._require_undecided()
        if not self.drafts_pending:
            raise InvariantViolationError(
                f"review task {self.task_id} has a version already or names no candidate"
            )
        return replace(self, rule_version_id=rule_version_id)

    def claim(self, by: UserId, at: datetime) -> "ReviewTask":
        """The task claimed by ``by``; the same claimant again gets it unchanged."""
        self._require_undecided()
        if self.status is ReviewTaskStatus.CLAIMED:
            if self.claimed_by == by:
                return self
            raise ReviewTaskClaimedError(
                f"review task {self.task_id} is claimed by {self.claimed_by}: they decide it, or "
                "a reviewer returns it to the queue"
            )
        return replace(self, status=ReviewTaskStatus.CLAIMED, claimed_by=by, claimed_at=at)

    def require_claimant(self, by: UserId) -> None:
        """Only the analyst who claimed the task edits its draft."""
        self._require_undecided()
        if self.status is not ReviewTaskStatus.CLAIMED or self.claimed_by != by:
            holder = "nobody" if self.claimed_by is None else str(self.claimed_by)
            raise ReviewTaskNotClaimedError(
                f"review task {self.task_id} is claimed by {holder}, not {by}: claim it first"
            )

    def release(self) -> "ReviewTask":
        """Open again and unclaimed: the round needs another approver."""
        self._require_undecided()
        return replace(self, status=ReviewTaskStatus.OPEN, claimed_by=None, claimed_at=None)

    def decide(
        self, decision: ReviewDecision, *, by: UserId, at: datetime, note: str = ""
    ) -> "ReviewTask":
        self._require_undecided()
        return replace(
            self,
            status=ReviewTaskStatus.DECIDED,
            decision=decision,
            decided_by=by,
            decided_at=at,
            note=note,
        )

    def _require_undecided(self) -> None:
        if not self.undecided:
            raise ReviewTaskClosedError(
                f"review task {self.task_id} was decided ({self.decision}) and never changes"
            )


def queue_position(task: ReviewTask) -> tuple[str, int, datetime, UUID]:
    """Where a task stands in the queue: by regulator, higher priority first, then oldest first,
    then by id."""
    return (task.regulator, -task.priority, task.opened_at, task.task_id)


@dataclass(frozen=True, slots=True)
class TaskKey:
    """The task a page of the queue starts after."""

    regulator: str
    priority: int
    opened_at: datetime
    task_id: UUID

    @classmethod
    def of(cls, task: ReviewTask) -> "TaskKey":
        return cls(task.regulator, task.priority, task.opened_at, task.task_id)

    @property
    def position(self) -> tuple[str, int, datetime, UUID]:
        return (self.regulator, -self.priority, self.opened_at, self.task_id)


@dataclass(frozen=True, slots=True)
class TaskQuery:
    """Which tasks a page of the queue holds: of ``status``, ``regulator`` and ``kind`` when
    given, after ``after`` in queue order, at most ``limit``. The regulator is compared in
    lower case, as the queue keeps it."""

    status: ReviewTaskStatus | None = None
    regulator: str | None = None
    after: TaskKey | None = None
    limit: int = 50
    kind: ReviewTaskKind | None = None

    def __post_init__(self) -> None:
        limit = require_int(self.limit, "limit", minimum=1)
        if limit > MAX_PAGE + 1:
            raise InvariantViolationError(f"a page reads at most {MAX_PAGE + 1} tasks")
        if self.regulator is not None:
            object.__setattr__(self, "regulator", self.regulator.strip().lower())

    def admits(self, task: ReviewTask) -> bool:
        return (
            self.status in (None, task.status)
            and self.regulator in (None, task.regulator.lower())
            and self.kind in (None, task.kind)
            and (self.after is None or queue_position(task) > self.after.position)
        )


@dataclass(frozen=True, slots=True)
class QueuedTask:
    """A task in the queue with what a reviewer scans it by: the version's rule, number,
    title and status, whether it is high impact, and how many people approved its current
    round. A candidate task not drafted yet has no version: its title is the candidate's, its
    rule key the one suggested for it, and ``high_impact`` what the candidate suggests;
    ``candidate`` summarises the candidate of every candidate task."""

    task: ReviewTask
    rule_key: str | None
    version: int | None
    title: str
    version_status: RuleVersionStatus | None
    high_impact: bool
    approvals: int
    candidate: CandidateSummary | None = None


@dataclass(frozen=True, slots=True)
class RegulatorCounts:
    regulator: str
    open: int = 0
    claimed: int = 0
    decided: int = 0

    @property
    def undecided(self) -> int:
        return self.open + self.claimed


@dataclass(frozen=True, slots=True)
class CandidateCounts:
    """The candidates analysts decided: approved (``approved_without_edits`` of them drafted as
    the candidate proposed, with no edit recorded on their version) or rejected. The acceptance
    rate is the share approved without edits, ADR-006's measure of the extraction."""

    approved: int = 0
    approved_without_edits: int = 0
    rejected: int = 0

    @property
    def decided(self) -> int:
        return self.approved + self.rejected

    @property
    def acceptance_rate(self) -> float | None:
        """Approved without edits over decided; None while none is decided."""
        if not self.decided:
            return None
        return self.approved_without_edits / self.decided


NO_CANDIDATES: Final = CandidateCounts()


@dataclass(frozen=True, slots=True)
class ReviewTaskStats:
    """The queue in numbers: tasks per regulator and status, the decisions made, the median
    time from a task's opening to its decision, when the oldest task not decided yet was
    opened, and how the candidates analysts decided went."""

    by_regulator: tuple[RegulatorCounts, ...] = ()
    decisions: Mapping[ReviewDecision, int] = field(default_factory=dict)
    median_seconds_to_decide: float | None = None
    oldest_open_at: datetime | None = None
    candidates: CandidateCounts = NO_CANDIDATES

    def counts(self) -> dict[ReviewTaskStatus, int]:
        return {
            ReviewTaskStatus.OPEN: sum(row.open for row in self.by_regulator),
            ReviewTaskStatus.CLAIMED: sum(row.claimed for row in self.by_regulator),
            ReviewTaskStatus.DECIDED: sum(row.decided for row in self.by_regulator),
        }

    def decision_counts(self) -> dict[ReviewDecision, int]:
        return {decision: self.decisions.get(decision, 0) for decision in ReviewDecision}

    def open_by_regulator(self) -> dict[str, int]:
        """Tasks not decided yet, claimed or not, for every regulator that has had a task."""
        return {row.regulator: row.undecided for row in self.by_regulator}

    def oldest_open_age_seconds(self, now: datetime) -> float:
        """How long the oldest task not decided yet has waited at ``now``; zero when none."""
        if self.oldest_open_at is None:
            return 0.0
        return max((now - self.oldest_open_at).total_seconds(), 0.0)


def task_stats(
    tasks: Sequence[ReviewTask], candidates: CandidateCounts = NO_CANDIDATES
) -> ReviewTaskStats:
    """The stats of ``tasks``, as the Postgres store computes them in SQL, with the counts of
    the decided candidates."""
    rows: dict[str, dict[ReviewTaskStatus, int]] = {}
    decisions: dict[ReviewDecision, int] = {}
    waits: list[float] = []
    oldest: datetime | None = None
    for task in tasks:
        counts = rows.setdefault(task.regulator, dict.fromkeys(ReviewTaskStatus, 0))
        counts[task.status] += 1
        if task.decision is not None and task.decided_at is not None:
            decisions[task.decision] = decisions.get(task.decision, 0) + 1
            waits.append((task.decided_at - task.opened_at).total_seconds())
        elif oldest is None or task.opened_at < oldest:
            oldest = task.opened_at
    return ReviewTaskStats(
        by_regulator=tuple(
            RegulatorCounts(
                regulator,
                open=counts[ReviewTaskStatus.OPEN],
                claimed=counts[ReviewTaskStatus.CLAIMED],
                decided=counts[ReviewTaskStatus.DECIDED],
            )
            for regulator, counts in sorted(rows.items())
        ),
        decisions=decisions,
        median_seconds_to_decide=statistics.median(waits) if waits else None,
        oldest_open_at=oldest,
        candidates=candidates,
    )


def describe_specification(specification: Mapping[str, object]) -> tuple[str, ...]:
    """The stored predicate tree as lines a reviewer reads, two spaces deeper per level:
    ``all of:``, ``any of:`` and ``not:`` head their children, and each predicate is its own
    line (``filing_scheme = regular_monthly``, or ``free text: "..."``)."""
    try:
        tree = specification_from_mapping(specification)
    except DomainError as exc:
        return (f"unreadable specification: {exc}",)
    lines: list[str] = []

    def walk(node: Specification, depth: int) -> None:
        pad = "  " * depth
        match node:
            case Predicate():
                lines.append(pad + node.describe())
            case AllOf(items=items):
                lines.append(pad + ("all of:" if items else "all of: nothing (always applies)"))
                for item in items:
                    walk(item, depth + 1)
            case AnyOf(items=items):
                lines.append(pad + ("any of:" if items else "any of: nothing (never applies)"))
                for item in items:
                    walk(item, depth + 1)
            case Not(item=item):
                lines.append(pad + "not:")
                walk(item, depth + 1)

    walk(tree, 0)
    return tuple(lines)
