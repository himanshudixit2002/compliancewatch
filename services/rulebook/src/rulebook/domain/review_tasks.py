"""Review tasks: a rule version waiting for an analyst's decision, queued by regulator and
priority.

A task asks for one decision about one rule version: approve it, return it for rework, or reject
it. It is opened (``open``), claimed by the analyst who works on it (``claimed``) and decided
(``decided``); a decided task never changes again, which the table's trigger enforces for every
writer. A version has at most one task that is not decided yet.

- ``claim``: an analyst takes an open task. The claimant claiming again changes nothing; a task
  someone else holds is refused (``ReviewTaskClaimedError``), and so is a decided one
  (``ReviewTaskClosedError``). Only the claimant edits the draft (``require_claimant``).
- ``release``: the first of the two approvals a high-impact version needs leaves the task open
  again, unclaimed, for a second and different reviewer.
- ``decide``: approve, return or reject, once.

Every draft the seed calendar wrote that still needs review gets a task of kind ``seed``; tasks
for the candidates the pipeline extracts come later with their own kind. Seed tasks share one
priority, so the queue keeps them in the order they were opened within a regulator.

The draft an analyst edits through a task is checked as the seed loader checks the calendar
(``edited_record``): structured predicates must fit the ontology, a free-text predicate may name
an attribute the ontology lacks only while the version carries an open question (``todo``), and
a duty that does not recur needs the template's ``due_in_days``.
"""

import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Final
from uuid import UUID, uuid4

from domain_kernel._validation import (
    require_aware,
    require_date,
    require_instance,
    require_int,
    require_text,
)
from domain_kernel.errors import DomainError, InvariantViolationError
from domain_kernel.ids import RuleVersionId, UserId
from domain_kernel.ontology import Ontology
from domain_kernel.predicates import (
    AllOf,
    AnyOf,
    Not,
    Predicate,
    PredicateKind,
    Specification,
    specification_from_mapping,
    specification_to_mapping,
)
from domain_kernel.recurrence import Recurrence
from domain_kernel.rules import ObligationTemplate
from domain_kernel.status import RuleVersionStatus
from rulebook.domain.errors import (
    ReviewTaskClaimedError,
    ReviewTaskClosedError,
    ReviewTaskNotClaimedError,
)
from rulebook.domain.rule_versions import RuleVersionRecord

SEED_PRIORITY: Final = 50
"""The priority of every seed task: the queue keeps them in the order they were opened."""
MAX_PRIORITY: Final = 1_000
MAX_NOTE: Final = 2_000
MAX_TITLE: Final = 300
MAX_SUMMARY: Final = 4_000
MAX_TODO: Final = 20
MAX_QUESTION: Final = 500
MAX_PAGE: Final = 200


class ReviewTaskKind(StrEnum):
    """What a task reviews. ``seed``: a draft the seed calendar wrote. The pipeline's candidates
    get a kind of their own when their intake is built."""

    SEED = "seed"


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
    """One decision asked about one rule version. ``regulator`` is the rule's, kept on the task
    for the queue's order and filter."""

    task_id: UUID
    rule_version_id: RuleVersionId
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

    def __post_init__(self) -> None:
        require_instance(self.task_id, UUID, "task_id")
        require_instance(self.rule_version_id, RuleVersionId, "rule_version_id")
        require_instance(self.kind, ReviewTaskKind, "kind")
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

    @property
    def undecided(self) -> bool:
        return self.status in UNDECIDED

    def next_round(self, *, at: datetime, task_id: UUID | None = None) -> "ReviewTask":
        """A new open task for the same version, as a return opens for the rework."""
        return ReviewTask(
            task_id=task_id or uuid4(),
            rule_version_id=self.rule_version_id,
            kind=self.kind,
            priority=self.priority,
            regulator=self.regulator,
            opened_at=at,
        )

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
    """Which tasks a page of the queue holds: of ``status`` and ``regulator`` when given, after
    ``after`` in queue order, at most ``limit``."""

    status: ReviewTaskStatus | None = None
    regulator: str | None = None
    after: TaskKey | None = None
    limit: int = 50

    def __post_init__(self) -> None:
        limit = require_int(self.limit, "limit", minimum=1)
        if limit > MAX_PAGE + 1:
            raise InvariantViolationError(f"a page reads at most {MAX_PAGE + 1} tasks")

    def admits(self, task: ReviewTask) -> bool:
        return (
            self.status in (None, task.status)
            and self.regulator in (None, task.regulator)
            and (self.after is None or queue_position(task) > self.after.position)
        )


@dataclass(frozen=True, slots=True)
class QueuedTask:
    """A task in the queue with what a reviewer scans it by: the version's rule, number,
    title and status, whether it is high impact, and how many people approved its current
    round."""

    task: ReviewTask
    rule_key: str
    version: int
    title: str
    version_status: RuleVersionStatus
    high_impact: bool
    approvals: int


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
class ReviewTaskStats:
    """The queue in numbers: tasks per regulator and status, the decisions made, the median
    time from a task's opening to its decision, and when the oldest task not decided yet was
    opened."""

    by_regulator: tuple[RegulatorCounts, ...] = ()
    decisions: Mapping[ReviewDecision, int] = field(default_factory=dict)
    median_seconds_to_decide: float | None = None
    oldest_open_at: datetime | None = None

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


def task_stats(tasks: Sequence[ReviewTask]) -> ReviewTaskStats:
    """The stats of ``tasks``, as the Postgres store computes them in SQL."""
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


EDITABLE_FIELDS: Final = (
    "title",
    "summary",
    "specification",
    "obligation_template",
    "recurrence",
    "effective_from",
    "effective_to",
    "todo",
)
"""The content of a draft an analyst edits through its task. The rule's key, regulator and
level, the seed source and the lifecycle columns are not edited here."""
NULLABLE_FIELDS: Final = frozenset({"recurrence", "effective_to"})


@dataclass(frozen=True, slots=True)
class DraftEdit:
    """What an analyst changes in a draft: the fields named in ``changes``, each with its new
    value as sent (the mapping forms for the specification, the template and the recurrence;
    None clears the recurrence or the end date)."""

    changes: Mapping[str, object]

    def __post_init__(self) -> None:
        unknown = sorted(set(self.changes) - set(EDITABLE_FIELDS))
        if unknown:
            raise InvariantViolationError(f"a draft edit cannot change {', '.join(unknown)}")
        refused = sorted(
            name
            for name, value in self.changes.items()
            if value is None and name not in NULLABLE_FIELDS
        )
        if refused:
            raise InvariantViolationError(f"{', '.join(refused)} cannot be null")


def edited_record(
    record: RuleVersionRecord, edit: DraftEdit, ontology: Ontology
) -> tuple[RuleVersionRecord, tuple[str, ...]]:
    """The draft after ``edit`` and the fields whose value changed. Each value is checked and
    stored in the kernel's canonical form; every problem found is reported at once."""
    problems: list[str] = []
    values: dict[str, Any] = {}
    for name, raw in edit.changes.items():
        try:
            values[name] = _CHECKS[name](raw)
        except (DomainError, TypeError, ValueError) as exc:
            problems.append(f"{name}: {exc}")
    if problems:
        raise InvariantViolationError("; ".join(problems))
    after = replace(record, **values)
    problems = _content_problems(after, ontology)
    if problems:
        raise InvariantViolationError("; ".join(problems))
    changed = tuple(
        name for name in EDITABLE_FIELDS if getattr(after, name) != getattr(record, name)
    )
    return after, changed


def _title(raw: object) -> str:
    title = require_text(raw, "title")
    if len(title) > MAX_TITLE:
        raise InvariantViolationError(f"at most {MAX_TITLE} characters")
    return title


def _summary(raw: object) -> str:
    summary = require_instance(raw, str, "summary").strip()
    if len(summary) > MAX_SUMMARY:
        raise InvariantViolationError(f"at most {MAX_SUMMARY} characters")
    return summary


def _specification(raw: object) -> Mapping[str, object]:
    return specification_to_mapping(specification_from_mapping(raw))


def _template(raw: object) -> Mapping[str, object]:
    return ObligationTemplate.from_mapping(raw).to_mapping()


def _recurrence(raw: object) -> Mapping[str, object] | None:
    return None if raw is None else Recurrence.from_mapping(raw).to_mapping()


def _effective_to(raw: object) -> date | None:
    return None if raw is None else require_date(raw, "effective_to")


def _todo(raw: object) -> tuple[str, ...]:
    if isinstance(raw, str) or not isinstance(raw, Sequence):
        raise InvariantViolationError("todo must be a list of questions")
    if len(raw) > MAX_TODO:
        raise InvariantViolationError(f"at most {MAX_TODO} questions")
    questions = tuple(require_text(item, "todo[]") for item in raw)
    if any(len(question) > MAX_QUESTION for question in questions):
        raise InvariantViolationError(f"a question has at most {MAX_QUESTION} characters")
    return questions


_CHECKS: Mapping[str, Callable[[object], object]] = {
    "title": _title,
    "summary": _summary,
    "specification": _specification,
    "obligation_template": _template,
    "recurrence": _recurrence,
    "effective_from": lambda raw: require_date(raw, "effective_from"),
    "effective_to": _effective_to,
    "todo": _todo,
}


def _content_problems(record: RuleVersionRecord, ontology: Ontology) -> list[str]:
    """What the seed loader would refuse in the edited draft."""
    problems: list[str] = []
    if record.effective_to is not None and record.effective_to <= record.effective_from:
        problems.append("effective_to must be after effective_from")
    try:
        template = ObligationTemplate.from_mapping(record.obligation_template)
        specification = specification_from_mapping(record.specification)
    except DomainError as exc:
        return [*problems, f"the stored content does not parse: {exc}"]
    if record.recurrence is None and template.due_in_days is None:
        problems.append("a duty that does not recur needs obligation_template.due_in_days")
    for predicate in specification.predicates():
        if predicate.kind is PredicateKind.FREE_TEXT:
            if predicate.attribute not in ontology and not record.todo:
                problems.append(
                    f"free-text predicate on unknown attribute {predicate.attribute!r} needs an "
                    "open question in todo"
                )
            continue
        try:
            ontology.check_predicate(predicate)
        except DomainError as exc:
            problems.append(f"{predicate.describe()}: {exc}")
    return problems
