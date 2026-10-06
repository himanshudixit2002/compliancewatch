"""Rule versions and their citations as the read API returns them.

A version is in force on a date when it has been published and the date falls in its half-open
effective period. A superseded version counts: it was published, and its ``effective_to`` is
cut to the day its replacement takes effect, so a question about an earlier date still sees it.
A withdrawn version never counts, and neither does one that was never published.

A clause is out of force on a date when a version that has been published (published, superseded
or withdrawn) cites it with a verified quote and none of those versions is in force then: the
text still reads as a rule, but the rule it states does not apply on that date.

A version ended on or after a date when it was published, was not withdrawn, and its
``effective_to`` (exclusive) is that day or later (``ended_since``). A superseded version still
governs the periods whose last day it was in force on, and their returns may fall due long after
it ended, so a reader that decides who owes them asks for the versions superseded since a day. A
withdrawn version never counts: withdrawing closes its obligations, so it governs nothing.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from domain_kernel.citations import (
    QUOTE_MATCH_THRESHOLD,
    evidence_tokens_missing,
    quote_match_ratio,
)
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import ClauseId, DocumentId, RuleId, RuleVersionId, UserId
from domain_kernel.ontology import AttributeLevel
from domain_kernel.periods import EffectivePeriod
from domain_kernel.status import RuleVersionStatus
from rulebook.domain.seed import SeedStatus

IN_FORCE_STATUSES = frozenset({RuleVersionStatus.PUBLISHED, RuleVersionStatus.SUPERSEDED})
"""Statuses of a version that has been published: only these can be in force on a date."""
CITING_STATUSES = IN_FORCE_STATUSES | {RuleVersionStatus.WITHDRAWN}
"""Statuses of a version that was published at some time: its verified citations tie a clause to
a rule, whether or not that rule is in force."""


@dataclass(frozen=True, slots=True)
class RuleVersionRecord:
    """One rule version with its rule's key, regulator and level. Specification, template and
    recurrence are the kernel's mapping forms, as stored. ``high_impact`` asks for two
    different approvers (ADR-006); ``submitted_at`` starts the current review round;
    ``candidate_id`` names the rule candidate an analyst drafted the version from, None for the
    seed calendar's versions."""

    rule_version_id: RuleVersionId
    rule_id: RuleId
    rule_key: str
    regulator: str
    level: AttributeLevel
    version: int
    status: RuleVersionStatus
    title: str
    summary: str
    specification: Mapping[str, object]
    obligation_template: Mapping[str, object]
    recurrence: Mapping[str, object] | None
    effective_from: date
    effective_to: date | None
    source: Mapping[str, object]
    seed_status: SeedStatus
    todo: tuple[str, ...]
    published_at: datetime | None = None
    high_impact: bool = False
    submitted_at: datetime | None = None
    candidate_id: UUID | None = None

    @property
    def effective(self) -> EffectivePeriod:
        return EffectivePeriod(self.effective_from, self.effective_to)


@dataclass(frozen=True, slots=True)
class RuleHead:
    """A rule as its next version needs it: the rule's id, key, regulator and level, and the
    highest number its versions have, every version counted (a closed draft keeps its number),
    so the next one takes ``next_version``."""

    rule_id: RuleId
    rule_key: str
    regulator: str
    level: AttributeLevel
    last_version: int

    @property
    def next_version(self) -> int:
        return self.last_version + 1


@dataclass(frozen=True, slots=True)
class CitationRecord:
    """A rule version's quote of a clause, with the clause's ref and document."""

    citation_id: UUID
    rule_version_id: RuleVersionId
    clause_id: ClauseId
    document_id: DocumentId
    clause_ref: str
    quote: str
    verified: bool
    match_score: float | None = None
    verified_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RuleVersionDetail:
    """One version with its citations and, once it has been published, the distinct approvers
    of the review round it was published from, by user id. Empty for a version that was never
    published: its current round may still change. ``closed`` says it is a draft whose rule
    candidate was rejected (``intake.version_closed``): it stays a draft and never moves on."""

    record: RuleVersionRecord
    citations: tuple[CitationRecord, ...]
    approved_by: tuple[UserId, ...] = ()
    closed: bool = False


@dataclass(frozen=True, slots=True)
class ListedVersion:
    """A version of a rule as its listing shows it, and whether it is closed."""

    record: RuleVersionRecord
    closed: bool = False


@dataclass(frozen=True, slots=True)
class VersionPage:
    """What narrows and pages a listing of versions: only those of ``status`` (published or
    superseded, the statuses a listing holds), of ``rule_key`` and of ``regulator``; at most
    ``limit``, by rule key then version, after the rule key ``after`` or, with
    ``after_version``, after that version of it (a listing of ended versions can hold several
    versions of one rule)."""

    rule_key: str | None = None
    regulator: str | None = None
    status: RuleVersionStatus | None = None
    limit: int = 100
    after: str | None = None
    after_version: int | None = None

    def __post_init__(self) -> None:
        if self.status is not None and self.status not in IN_FORCE_STATUSES:
            raise InvariantViolationError(
                f"status must be published or superseded, got {self.status.value}"
            )
        if self.after_version is not None and self.after is None:
            raise InvariantViolationError("after_version continues after a rule key: name after")

    def admits(self, record: RuleVersionRecord) -> bool:
        """Whether ``record`` has the status, rule key and regulator asked and follows
        ``after``."""
        return (
            self.status in (None, record.status)
            and self.rule_key in (None, record.rule_key)
            and self.regulator in (None, record.regulator)
            and self.follows(record)
        )

    def follows(self, record: RuleVersionRecord) -> bool:
        """Whether ``record`` comes after the page's cursor: a later rule key, or a later version
        of the rule key ``after`` when ``after_version`` names one."""
        if self.after is None:
            return True
        if record.rule_key != self.after:
            return record.rule_key > self.after
        return self.after_version is not None and record.version > self.after_version


def in_force(record: RuleVersionRecord, as_of: date) -> bool:
    """Whether the version was published and ``as_of`` falls in ``[effective_from,
    effective_to)``."""
    return record.status in IN_FORCE_STATUSES and record.effective.contains(as_of)


def ended_since(record: RuleVersionRecord, since: date) -> bool:
    """Whether the version was published, never withdrawn, and its ``effective_to`` is on or
    after ``since``: the versions superseded since that day, and the published ones a
    replacement has cut to end then or later. An open-ended version has not ended."""
    return (
        record.status in IN_FORCE_STATUSES
        and record.effective_to is not None
        and record.effective_to >= since
    )


def out_of_force(citing: Iterable[RuleVersionRecord], as_of: date | None) -> bool:
    """Whether a clause cited with a verified quote by ``citing`` is out of force on ``as_of``: at
    least one of them was published at some time and none of those is in force then. False
    without a date, or when no such version cites the clause."""
    published = [record for record in citing if record.status in CITING_STATUSES]
    return (
        as_of is not None
        and bool(published)
        and not any(in_force(record, as_of) for record in published)
    )


@dataclass(frozen=True, slots=True)
class QuoteCheck:
    """How a quote matched its clause: the fuzzy score and the facts it carries that the clause
    does not. Verified means a score of at least 0.85 and no missing fact (ADR-006)."""

    score: float
    missing: tuple[str, ...]

    @property
    def verified(self) -> bool:
        return self.score >= QUOTE_MATCH_THRESHOLD and not self.missing


def check_quote(quote: str, clause_text: str) -> QuoteCheck:
    return QuoteCheck(
        quote_match_ratio(quote, clause_text), evidence_tokens_missing(quote, clause_text)
    )
