"""Publishing a rule version: the checks, in order, and what publication changes.

A version reaches ``published`` only from ``approved`` (``RULE_VERSION_TRANSITIONS``), with at
least one citation and every citation verified, and with one approver in the current review
round, two different ones when it is high impact (ADR-006). The database trigger on
``rule_version`` refuses the same things, so a writer that skips this module cannot publish
either.

The version being published (X) changes the versions its relations target (Y), ADR-017:

- ``supersedes``, ``corrects`` and ``withdraws`` replace Y. Y must be published, start before X
  and not be replaced by another published version already. Publication cuts Y's
  ``effective_to`` to X's ``effective_from`` at once, so the two never overlap. Y's status moves
  (to superseded, or withdrawn for ``withdraws``) and its event goes out when X takes effect: at
  publication when X's ``effective_from`` is today or earlier, otherwise in the daily sweep
  (``plan_due_transitions``). ``corrects`` is a replacement until a candidate can carry the
  corrected date.
- ``extends_deadline`` moves Y's due date: ``rule.deadline_changed`` goes out at publication with
  the candidate's new due date and, when Y recurs, its period. Y must be published or
  superseded.
- ``amends``, ``refers_to`` and ``exempts`` change nothing at publication.

Last, X must not overlap another version of its rule that is in force once the cuts are made.

X cannot be withdrawn directly while a version it replaces is still published
(``check_withdrawal``): that version was cut at X's publication and moves only when X takes
effect, so withdrawing X first would leave it cut for good.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from domain_kernel._validation import require_aware, require_instance
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import ClauseId, CorrelationId, EventId, RuleId, RuleVersionId, UserId
from domain_kernel.knowledge import RelationKind
from domain_kernel.predicates import specification_from_mapping
from domain_kernel.status import RULE_VERSION_TRANSITIONS, RuleVersionStatus
from rulebook.domain.errors import (
    ApprovalsMissingError,
    CitationsMissingError,
    DeadlineDetailMissingError,
    OverlappingVersionError,
    RelationTargetStateError,
    ReplacementDatesError,
    ReplacementsPendingError,
    TargetAlreadyReplacedError,
    UnknownRuleVersionError,
)
from rulebook.domain.events import (
    DeadlineChangeReason,
    RuleDeadlineChanged,
    RuleEvent,
    RulePublished,
    RuleSuperseded,
    RuleWithdrawn,
)
from rulebook.domain.graph import RelationRecord
from rulebook.domain.rule_versions import IN_FORCE_STATUSES, CitationRecord, RuleVersionRecord

DEFAULT_APPROVALS = 1
HIGH_IMPACT_APPROVALS = 2

REPLACING: Mapping[RelationKind, RuleVersionStatus] = {
    RelationKind.SUPERSEDES: RuleVersionStatus.SUPERSEDED,
    RelationKind.CORRECTS: RuleVersionStatus.SUPERSEDED,
    RelationKind.WITHDRAWS: RuleVersionStatus.WITHDRAWN,
}
"""Relations that replace their target, with the status the target ends in."""


def required_approvals(high_impact: bool) -> int:
    """ADR-006: one approver, two different ones for a high-impact version."""
    return HIGH_IMPACT_APPROVALS if high_impact else DEFAULT_APPROVALS


class DecisionAction(StrEnum):
    """What a row of the append-only ``rule_version_decision`` audit records. ``edited`` is an
    analyst's change to a draft through its review task (content or citations); the version
    stays a draft, and the note names what changed."""

    SUBMITTED = "submitted"
    RETURNED = "returned"
    APPROVED = "approved"
    PUBLISHED = "published"
    WITHDRAWN = "withdrawn"
    SUPERSEDED = "superseded"
    EDITED = "edited"


@dataclass(frozen=True, slots=True)
class RuleVersionDecision:
    """One step of a version's life: who took it, or which version caused it."""

    decision_id: UUID
    rule_version_id: RuleVersionId
    action: DecisionAction
    from_status: RuleVersionStatus
    to_status: RuleVersionStatus
    decided_at: datetime
    actor_id: UserId | None = None
    caused_by: RuleVersionId | None = None
    note: str = ""

    def __post_init__(self) -> None:
        require_instance(self.action, DecisionAction, "action")
        require_aware(self.decided_at, "decided_at")
        if self.actor_id is None and self.caused_by is None:
            raise InvariantViolationError("a decision names its actor or the version causing it")


@dataclass(frozen=True, slots=True)
class Replacement:
    """What publishing X does to one version it replaces: the cut now, the move when due."""

    target: RuleVersionRecord
    relation: RelationKind
    effective_to: date | None
    moves_to: RuleVersionStatus
    due: bool

    @property
    def updated(self) -> RuleVersionRecord:
        """The target after publication: cut, and moved when X is in effect."""
        status = self.moves_to if self.due else self.target.status
        return replace(self.target, effective_to=self.effective_to, status=status)


@dataclass(frozen=True, slots=True)
class DeadlineChange:
    target: RuleVersionRecord
    period_label: str | None
    new_due_on: date
    evidence_clause_id: ClauseId


@dataclass(frozen=True, slots=True)
class PublicationPlan:
    published: RuleVersionRecord
    replacements: tuple[Replacement, ...]
    deadline_changes: tuple[DeadlineChange, ...]
    approved_by: tuple[UserId, ...]
    attribute_keys: tuple[str, ...]
    supersedes: tuple[RuleVersionId, ...]
    """The targets of X's ``supersedes`` relations, the list ``rule.published`` carries."""

    def events(
        self, *, correlation_id: CorrelationId, occurred_at: datetime
    ) -> tuple[RuleEvent, ...]:
        """``rule.published``, then the replacements that are due and the deadline changes,
        each caused by it."""
        x = self.published
        published = RulePublished(
            occurred_at=occurred_at,
            correlation_id=correlation_id,
            rule_id=x.rule_id,
            rule_version_id=x.rule_version_id,
            version=x.version,
            regulator=x.regulator,
            title=x.title,
            summary=x.summary,
            effective_from=x.effective_from,
            effective_to=x.effective_to,
            supersedes=self.supersedes,
            approved_by=self.approved_by,
            high_impact=x.high_impact,
            attribute_keys=self.attribute_keys,
        )
        follow: list[RuleEvent] = [
            transition_event(
                replacement.target.rule_id,
                replacement.target.rule_version_id,
                replacement.moves_to,
                by=x.rule_version_id,
                effective_from=x.effective_from,
                correlation_id=correlation_id,
                causation_id=published.event_id,
                occurred_at=occurred_at,
            )
            for replacement in self.replacements
            if replacement.due
        ]
        follow.extend(
            RuleDeadlineChanged(
                occurred_at=occurred_at,
                correlation_id=correlation_id,
                causation_id=published.event_id,
                rule_id=change.target.rule_id,
                rule_version_id=change.target.rule_version_id,
                caused_by_rule_version_id=x.rule_version_id,
                period_label=change.period_label,
                new_due_on=change.new_due_on,
                reason=DeadlineChangeReason.DEADLINE_EXTENDED,
                evidence_clause_id=change.evidence_clause_id,
            )
            for change in self.deadline_changes
        )
        return (published, *follow)


def transition_event(
    rule_id: RuleId,
    rule_version_id: RuleVersionId,
    status: RuleVersionStatus,
    *,
    by: RuleVersionId | None,
    effective_from: date,
    correlation_id: CorrelationId,
    causation_id: EventId | None,
    occurred_at: datetime,
) -> RuleEvent:
    """``rule.superseded`` or ``rule.withdrawn`` for a version that moved to ``status``."""
    if status is RuleVersionStatus.SUPERSEDED:
        if by is None:
            raise InvariantViolationError("a superseded version names the version replacing it")
        return RuleSuperseded(
            occurred_at=occurred_at,
            correlation_id=correlation_id,
            causation_id=causation_id,
            rule_id=rule_id,
            rule_version_id=rule_version_id,
            superseded_by_rule_version_id=by,
            effective_from=effective_from,
        )
    if status is RuleVersionStatus.WITHDRAWN:
        return RuleWithdrawn(
            occurred_at=occurred_at,
            correlation_id=correlation_id,
            causation_id=causation_id,
            rule_id=rule_id,
            rule_version_id=rule_version_id,
            withdrawn_by_rule_version_id=by,
            effective_from=effective_from,
        )
    raise InvariantViolationError(f"no event for a version moving to {status.value}")


def attribute_keys(specification: Mapping[str, object]) -> tuple[str, ...]:
    """The ontology attributes the predicates reference, sorted. An empty mapping (a version
    with no predicates yet) references none; a malformed one raises."""
    if not specification:
        return ()
    return tuple(sorted(specification_from_mapping(specification).referenced_attributes()))


def plan_publication(
    version: RuleVersionRecord,
    *,
    relations: Sequence[RelationRecord],
    targets: Mapping[RuleVersionId, RuleVersionRecord],
    replaced_elsewhere: frozenset[RuleVersionId],
    siblings: Sequence[RuleVersionRecord],
    approvers: frozenset[UserId],
    citations: Sequence[CitationRecord],
    today: date,
    published_at: datetime,
) -> PublicationPlan:
    """Check that ``version`` may be published and work out what publishing it changes.

    ``relations`` are the version's own; ``targets`` the versions they point at;
    ``replaced_elsewhere`` the targets another published version replaces already; ``siblings``
    the other versions of its rule; ``approvers`` the distinct approvers of the current round.
    """
    RULE_VERSION_TRANSITIONS.assert_transition(version.status, RuleVersionStatus.PUBLISHED)
    _check_citations(version, citations)
    needed = required_approvals(version.high_impact)
    if len(approvers) < needed:
        raise ApprovalsMissingError(
            f"rule version {version.rule_version_id} has {len(approvers)} of the {needed} "
            "approvals it needs"
        )
    replacements: dict[RuleVersionId, Replacement] = {}
    changes: list[DeadlineChange] = []
    for relation in relations:
        target_id = relation.to_rule_version_id
        if target_id is None:
            continue
        if relation.relation in REPLACING:
            target = _target(targets, target_id)
            replacement = _replacement(version, relation, target, replaced_elsewhere, today)
            earlier = replacements.get(target_id)
            if earlier is not None and earlier.moves_to is not replacement.moves_to:
                raise RelationTargetStateError(
                    f"rule version {target_id} is both {earlier.moves_to.value} and "
                    f"{replacement.moves_to.value} by {version.rule_version_id}"
                )
            replacements.setdefault(target_id, replacement)
        elif relation.relation is RelationKind.EXTENDS_DEADLINE:
            changes.append(_deadline_change(relation, _target(targets, target_id)))
    _check_overlap(version, siblings, replacements)
    return PublicationPlan(
        published=replace(version, status=RuleVersionStatus.PUBLISHED, published_at=published_at),
        replacements=tuple(replacements.values()),
        deadline_changes=tuple(changes),
        approved_by=tuple(sorted(approvers, key=str)),
        attribute_keys=attribute_keys(version.specification),
        supersedes=tuple(
            dict.fromkeys(
                r.to_rule_version_id
                for r in relations
                if r.relation is RelationKind.SUPERSEDES and r.to_rule_version_id is not None
            )
        ),
    )


def _check_citations(version: RuleVersionRecord, citations: Sequence[CitationRecord]) -> None:
    if not citations:
        raise CitationsMissingError(f"rule version {version.rule_version_id} cites no clause")
    unverified = [c for c in citations if not c.verified]
    if unverified:
        raise CitationsMissingError(
            f"{len(unverified)} of the {len(citations)} citations of rule version "
            f"{version.rule_version_id} are not verified"
        )


def _target(
    targets: Mapping[RuleVersionId, RuleVersionRecord], target_id: RuleVersionId
) -> RuleVersionRecord:
    target = targets.get(target_id)
    if target is None:
        raise UnknownRuleVersionError(str(target_id))
    return target


def _replacement(
    version: RuleVersionRecord,
    relation: RelationRecord,
    target: RuleVersionRecord,
    replaced_elsewhere: frozenset[RuleVersionId],
    today: date,
) -> Replacement:
    kind = relation.relation.value
    if target.status is not RuleVersionStatus.PUBLISHED:
        raise RelationTargetStateError(
            f"{kind} needs a published target; rule version {target.rule_version_id} is "
            f"{target.status.value}"
        )
    if target.effective_from >= version.effective_from:
        raise ReplacementDatesError(
            f"rule version {version.rule_version_id} starts {version.effective_from}, not after "
            f"{target.rule_version_id}, which starts {target.effective_from}"
        )
    if target.rule_version_id in replaced_elsewhere:
        raise TargetAlreadyReplacedError(
            f"rule version {target.rule_version_id} is replaced by another published version"
        )
    cut = version.effective_from
    if target.effective_to is not None and target.effective_to < cut:
        cut = target.effective_to
    return Replacement(
        target=target,
        relation=relation.relation,
        effective_to=cut,
        moves_to=REPLACING[relation.relation],
        due=version.effective_from <= today,
    )


def _deadline_change(relation: RelationRecord, target: RuleVersionRecord) -> DeadlineChange:
    if target.status not in IN_FORCE_STATUSES:
        raise RelationTargetStateError(
            f"extends_deadline needs a published or superseded target; rule version "
            f"{target.rule_version_id} is {target.status.value}"
        )
    if relation.new_due_on is None:
        raise DeadlineDetailMissingError(
            f"relation {relation.relation_id} to {target.rule_version_id} has no new due date"
        )
    if target.recurrence is not None and relation.period_label is None:
        raise DeadlineDetailMissingError(
            f"rule version {target.rule_version_id} recurs, so relation {relation.relation_id} "
            "must name the period whose due date moves"
        )
    return DeadlineChange(
        target=target,
        period_label=relation.period_label,
        new_due_on=relation.new_due_on,
        evidence_clause_id=relation.evidence_clause_id,
    )


def _check_overlap(
    version: RuleVersionRecord,
    siblings: Sequence[RuleVersionRecord],
    replacements: Mapping[RuleVersionId, Replacement],
) -> None:
    for sibling in siblings:
        if sibling.rule_version_id == version.rule_version_id:
            continue
        replacement = replacements.get(sibling.rule_version_id)
        after = sibling if replacement is None else replacement.updated
        if after.status in IN_FORCE_STATUSES and after.effective.overlaps(version.effective):
            raise OverlappingVersionError(
                f"rule version {version.rule_version_id} ({version.effective_from} to "
                f"{version.effective_to or 'open'}) overlaps version {after.version} "
                f"({after.effective_from} to {after.effective_to or 'open'}); replace it with a "
                "supersedes relation or change the dates"
            )


def check_withdrawal(
    version: RuleVersionRecord,
    relations: Sequence[RelationRecord],
    targets: Mapping[RuleVersionId, RuleVersionRecord],
) -> None:
    """Refuse to withdraw ``version`` while a version it supersedes, corrects or withdraws is
    still published. ``relations`` are the version's own, ``targets`` the versions they point
    at."""
    pending = sorted(
        {
            str(relation.to_rule_version_id)
            for relation in relations
            if relation.relation in REPLACING
            and relation.to_rule_version_id is not None
            and relation.to_rule_version_id in targets
            and targets[relation.to_rule_version_id].status is RuleVersionStatus.PUBLISHED
        }
    )
    if pending:
        raise ReplacementsPendingError(
            f"rule version {version.rule_version_id} replaces {', '.join(pending)} from "
            f"{version.effective_from}, which has not moved yet; publish a version that corrects "
            "or supersedes it instead of withdrawing it"
        )


@dataclass(frozen=True, slots=True)
class PendingReplacement:
    """A published version Y that a published version X replaces, waiting for X's
    ``effective_from``."""

    relation: RelationKind
    target_id: RuleVersionId
    target_rule_id: RuleId
    replacing_id: RuleVersionId
    replacing_from: date

    @property
    def moves_to(self) -> RuleVersionStatus:
        return REPLACING[self.relation]


def plan_due_transitions(
    pending: Sequence[PendingReplacement], today: date
) -> tuple[PendingReplacement, ...]:
    """The replacements that take effect by ``today``: per target the earliest one (ties by
    replacing version id), ordered by date then target."""
    earliest: dict[RuleVersionId, PendingReplacement] = {}
    for candidate in pending:
        if candidate.replacing_from > today:
            continue
        current = earliest.get(candidate.target_id)
        if current is None or (candidate.replacing_from, str(candidate.replacing_id)) < (
            current.replacing_from,
            str(current.replacing_id),
        ):
            earliest[candidate.target_id] = candidate
    return tuple(
        sorted(earliest.values(), key=lambda due: (due.replacing_from, str(due.target_id)))
    )
