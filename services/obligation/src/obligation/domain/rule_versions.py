"""What the obligation service keeps of a rule version, and which obligations a version may still
have.

The rulebook owns rule versions. The obligation service caches the few facts about each that its
obligations show and its guard needs (``RuleVersionRef``, the ``rule_version_ref`` table): the
rule key, the status, the title, the effective dates, the seed status, who approved the round it
was published from and when it was published, its verified citations, and when the rulebook was
read. It is rule-level data, the same for every tenant.

Lifecycle facts only move forward, as in the rulebook: a published version becomes superseded or
withdrawn, and its ``effective_to`` is only ever set or moved earlier. ``RuleVersionRef.merge``
keeps the further of two views of one version, so an older read or a late event never moves a
cached version back; the other facts come from the later read.

A version governs a period when it is in force on the period's last day: a period that ends on or
before the version's ``effective_from`` belongs to an earlier version (``MaterialiseObligations``
skips it), and one that ends after its ``effective_to`` to the version that replaced it. A one-off
obligation belongs to the version in force on its due day. So:

- ``refusal(ref)`` says why no obligation of the version may be made at all: it was withdrawn,
  or it cites no verified clause (every obligation carries at least one);
- ``holds_period(ref, period)`` and ``holds_due(ref, due_on)`` say whether a period, or the due
  day of a one-off obligation, is still the version's; an undated one-off is the version's until
  it is superseded;
- ``taken_over(obligation, effective_from, tz)`` says whether a version that supersedes the
  obligation's own from ``effective_from`` takes the open obligation over: its period ends after
  that day, its due day (in ``tz``) is on or after it, or it has no date.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, tzinfo
from enum import StrEnum
from types import MappingProxyType
from typing import Self
from uuid import UUID

from domain_kernel._validation import require_aware, require_instance, require_text
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import BusinessId, DecisionId, RuleVersionId, TenantId, UserId
from domain_kernel.periods import EffectivePeriod
from domain_kernel.recurrence import Period
from domain_kernel.rules import RuleVersionSnapshot
from domain_kernel.status import RuleVersionStatus
from obligation.domain.model import Obligation

ENDED_RANK: Mapping[RuleVersionStatus, int] = MappingProxyType(
    {RuleVersionStatus.SUPERSEDED: 1, RuleVersionStatus.WITHDRAWN: 2}
)
"""How far past publication a status is; every other status ranks 0. Withdrawn ranks above
superseded: it refuses everything, superseded only what came after it."""


class Refusal(StrEnum):
    """Why the guard made no obligation of a version, or none for some of its periods."""

    RULE_WITHDRAWN = "rule_withdrawn"
    RULE_SUPERSEDED = "rule_superseded"
    """For the periods, or the due day, after the version stopped governing."""
    UNCITED = "uncited"
    """The version cites no verified clause, so its obligations could show no source."""


@dataclass(frozen=True, slots=True)
class Citation:
    """One verified quote of a clause, as the rulebook reports it."""

    citation_id: UUID
    clause_id: UUID
    document_id: UUID
    clause_ref: str
    quote: str
    match_score: float | None = None
    verified_at: datetime | None = None

    def __post_init__(self) -> None:
        require_text(self.clause_ref, "clause_ref")
        require_text(self.quote, "quote")
        if self.verified_at is not None:
            require_aware(self.verified_at, "verified_at")


@dataclass(frozen=True, slots=True)
class RuleVersionRef:
    """The cached facts of one rule version; ``fetched_at`` is when the rulebook was read."""

    rule_version_id: RuleVersionId
    rule_key: str
    status: RuleVersionStatus
    title: str
    effective_from: date
    effective_to: date | None
    seed_status: str
    approved_by: tuple[UserId, ...]
    published_at: datetime | None
    citations: tuple[Citation, ...]
    fetched_at: datetime

    def __post_init__(self) -> None:
        require_instance(self.rule_version_id, RuleVersionId, "rule_version_id")
        require_text(self.rule_key, "rule_key")
        require_instance(self.status, RuleVersionStatus, "status")
        require_text(self.title, "title")
        EffectivePeriod(self.effective_from, self.effective_to)
        require_text(self.seed_status, "seed_status")
        for approver in require_instance(self.approved_by, tuple, "approved_by"):
            require_instance(approver, UserId, "approved_by[]")
        if self.published_at is not None:
            require_aware(self.published_at, "published_at")
        for citation in require_instance(self.citations, tuple, "citations"):
            require_instance(citation, Citation, "citations[]")
        require_aware(self.fetched_at, "fetched_at")

    @property
    def effective(self) -> EffectivePeriod:
        return EffectivePeriod(self.effective_from, self.effective_to)

    def merge(self, other: Self) -> Self:
        """The further lifecycle of the two views and the other facts of the later read (the
        other one on a tie)."""
        if other.rule_version_id != self.rule_version_id:
            raise InvariantViolationError(
                f"cannot merge rule version {other.rule_version_id} into {self.rule_version_id}"
            )
        later = other if other.fetched_at >= self.fetched_at else self
        earlier = self if later is other else other
        return later.ended(earlier.status, earlier.effective_to)

    def ended(self, status: RuleVersionStatus, effective_to: date | None) -> Self:
        """This view once the version is known to be ``status`` and to end by
        ``effective_to``: the status that ranks further past publication, the earlier end."""
        kept = status if ENDED_RANK.get(status, 0) > ENDED_RANK.get(self.status, 0) else self.status
        ends = self.effective_to
        if effective_to is not None and (ends is None or effective_to < ends):
            ends = effective_to
        if (kept, ends) == (self.status, self.effective_to):
            return self
        # The rulebook never cuts a version to its own first day or earlier; EffectivePeriod
        # refuses such an end here too.
        return replace(self, status=kept, effective_to=ends)


@dataclass(frozen=True, slots=True)
class RuleVersionRead:
    """One read of a rule version at the rulebook: the kernel's snapshot, which obligations are
    made from, and the facts the cache keeps."""

    snapshot: RuleVersionSnapshot
    ref: RuleVersionRef

    def __post_init__(self) -> None:
        require_instance(self.snapshot, RuleVersionSnapshot, "snapshot")
        require_instance(self.ref, RuleVersionRef, "ref")
        if self.snapshot.rule_version_id != self.ref.rule_version_id:
            raise InvariantViolationError("the snapshot and the reference name other versions")


def refusal(ref: RuleVersionRef) -> Refusal | None:
    """Why no obligation of the version may be made, or None when some may."""
    if ref.status is RuleVersionStatus.WITHDRAWN:
        return Refusal.RULE_WITHDRAWN
    if not ref.citations:
        return Refusal.UNCITED
    return None


def holds_period(ref: RuleVersionRef, period: Period) -> bool:
    """Whether the version is still in force on the period's last day."""
    return ref.effective_to is None or period.end <= ref.effective_to


def holds_due(ref: RuleVersionRef, due_on: date | None) -> bool:
    """Whether a one-off obligation due on ``due_on`` (None: undated) is still the version's."""
    if due_on is None:
        return ref.status is not RuleVersionStatus.SUPERSEDED
    return ref.effective_to is None or due_on < ref.effective_to


def taken_over(obligation: Obligation, effective_from: date, tz: tzinfo) -> bool:
    """Whether a version in force from ``effective_from`` takes over the obligation of the one
    it supersedes: the period ends after that day, the one-off is due on it or later, or the
    obligation has no date."""
    if obligation.period is not None:
        return obligation.period.end > effective_from
    if obligation.due_at is None:
        return True
    return obligation.due_at.astimezone(tz).date() >= effective_from


@dataclass(frozen=True, slots=True)
class AppliedDecision:
    """The latest applicability decision the service acted on for one business and rule
    version: whether the rule applies, which decision said so and when it was made. The daily
    rolling window makes the new periods of those that apply."""

    tenant_id: TenantId
    business_id: BusinessId
    rule_version_id: RuleVersionId
    decision_id: DecisionId
    applies: bool
    decided_at: datetime

    def __post_init__(self) -> None:
        require_instance(self.tenant_id, TenantId, "tenant_id")
        require_instance(self.business_id, BusinessId, "business_id")
        require_instance(self.rule_version_id, RuleVersionId, "rule_version_id")
        require_instance(self.decision_id, DecisionId, "decision_id")
        require_instance(self.applies, bool, "applies")
        require_aware(self.decided_at, "decided_at")

    def supersedes(self, stored: "AppliedDecision | None") -> bool:
        """Whether this decision replaces ``stored``: there is none, or it was made no
        earlier."""
        return stored is None or self.decided_at >= stored.decided_at
