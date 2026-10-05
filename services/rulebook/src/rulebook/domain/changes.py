"""The changes feed: one item per published change, read back from the decision log.

A change is what a rule event announced, and ``rule_version_decision``, the append-only audit of
every step a version takes, records each of them:

- ``published``: a version was published (its ``published`` decision);
- ``superseded``: a version moved to superseded, at its replacement's publication or in the
  daily sweep (its ``superseded`` decision, which names the replacing version);
- ``withdrawn``: a version was withdrawn, by an analyst or by a published version that withdraws
  it (its ``withdrawn`` decision);
- ``deadline_changed``: a published version moved the due date of another, once per
  ``extends_deadline`` relation from it to a version (its ``published`` decision, with the
  candidate's period and new due date).

The submissions, returns and approvals of the review flow are not changes: nothing reached a
business through them. Each change is about one version (``rule_version_id``): the one
published, superseded or withdrawn, or the one whose due date moved; ``caused_by`` names the
version whose publication caused it, when one did. The feed lists the changes newest first
(``changed_at``, then ``change_id``, both descending). A change's id is its decision's id, and a
deadline change's derives from the publication's decision and the relation
(``deadline_change_id``), so every read gives a change the same id and a page cursor stays valid.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from domain_kernel._validation import require_aware, require_instance
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import ClauseId, RuleVersionId, UserId
from domain_kernel.knowledge import RelationKind
from rulebook.domain.graph import RelationRecord
from rulebook.domain.publication import DecisionAction
from rulebook.domain.rule_versions import CitationRecord, RuleVersionRecord

MAX_CHANGES: Final = 100
"""The longest page of the feed."""
CHANGE_RELATIONS: Final = (
    RelationKind.SUPERSEDES,
    RelationKind.CORRECTS,
    RelationKind.WITHDRAWS,
    RelationKind.EXTENDS_DEADLINE,
)
"""The relations to another version a change reports: those publication acts on."""


class RuleChangeKind(StrEnum):
    PUBLISHED = "published"
    SUPERSEDED = "superseded"
    WITHDRAWN = "withdrawn"
    DEADLINE_CHANGED = "deadline_changed"


CHANGE_ACTIONS: Final = {
    DecisionAction.PUBLISHED: RuleChangeKind.PUBLISHED,
    DecisionAction.SUPERSEDED: RuleChangeKind.SUPERSEDED,
    DecisionAction.WITHDRAWN: RuleChangeKind.WITHDRAWN,
}
"""The decisions that are changes, each as its kind; a deadline change comes from a published
decision too."""


def deadline_change_id(decision_id: UUID, relation_id: UUID) -> UUID:
    """The id of the deadline change a publication makes through one relation: the first 32
    hex digits of the SHA-256 of ``<decision id>:<relation id>``, which the Postgres store
    computes the same way."""
    digest = hashlib.sha256(f"{decision_id}:{relation_id}".encode()).hexdigest()
    return UUID(digest[:32])


@dataclass(frozen=True, slots=True)
class ChangeKey:
    """Where a page of the feed ends: the last change on it."""

    changed_at: datetime
    change_id: UUID

    def __post_init__(self) -> None:
        require_aware(self.changed_at, "changed_at")
        require_instance(self.change_id, UUID, "change_id")


@dataclass(frozen=True, slots=True)
class ChangeEntry:
    """One change as the decision log records it. ``period_label``, ``new_due_on`` and
    ``evidence_clause_id`` belong to a deadline change: the period whose due date moved (None
    for a version that does not recur), the new due date and the clause that says so."""

    change_id: UUID
    kind: RuleChangeKind
    changed_at: datetime
    rule_version_id: RuleVersionId
    caused_by: RuleVersionId | None = None
    period_label: str | None = None
    new_due_on: date | None = None
    evidence_clause_id: ClauseId | None = None

    def __post_init__(self) -> None:
        require_instance(self.kind, RuleChangeKind, "kind")
        require_aware(self.changed_at, "changed_at")
        require_instance(self.rule_version_id, RuleVersionId, "rule_version_id")
        if self.kind is RuleChangeKind.DEADLINE_CHANGED and self.caused_by is None:
            raise InvariantViolationError("a deadline change names the version that made it")

    @property
    def key(self) -> ChangeKey:
        return ChangeKey(self.changed_at, self.change_id)


@dataclass(frozen=True, slots=True)
class ChangeQuery:
    """A page of the feed: changes at or after ``since``, of versions whose rule ``regulator``
    issues, after ``after``, at most ``limit``."""

    limit: int
    since: datetime | None = None
    regulator: str | None = None
    after: ChangeKey | None = None

    def __post_init__(self) -> None:
        if self.limit < 1:
            raise InvariantViolationError("limit must be at least 1")
        if self.since is not None:
            require_aware(self.since, "since")


@dataclass(frozen=True, slots=True)
class Change:
    """A change with what a reader shows of its version: the version itself, the approvers of
    the round it was published from (empty when it never was), its verified citations, and its
    relations to the versions publication acts on (``CHANGE_RELATIONS``)."""

    entry: ChangeEntry
    version: RuleVersionRecord
    approved_by: tuple[UserId, ...] = ()
    citations: tuple[CitationRecord, ...] = ()
    relations: tuple[RelationRecord, ...] = ()


def change_relations(relations: Sequence[RelationRecord]) -> tuple[RelationRecord, ...]:
    """The relations a change reports: to another version, of the kinds publication acts on."""
    return tuple(
        relation
        for relation in relations
        if relation.relation in CHANGE_RELATIONS and relation.to_rule_version_id is not None
    )


def newest_first(entries: Sequence[ChangeEntry]) -> list[ChangeEntry]:
    """``entries`` in the feed's order: changed_at, then change id, both descending."""
    return sorted(entries, key=lambda entry: (entry.changed_at, entry.change_id), reverse=True)
