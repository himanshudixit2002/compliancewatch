"""Rule versions and their citations as the read API returns them.

A version is in force on a date when it has been published and the date falls in its half-open
effective period. A superseded version counts: it was published, and its ``effective_to`` is
cut to the day its replacement takes effect, so a question about an earlier date still sees it.
A withdrawn version never counts, and neither does one that was never published.

A clause is out of force on a date when a version that has been published (published, superseded
or withdrawn) cites it with a verified quote and none of those versions is in force then: the
text still reads as a rule, but the rule it states does not apply on that date.
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
from domain_kernel.ids import ClauseId, DocumentId, RuleId, RuleVersionId
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
    different approvers (ADR-006); ``submitted_at`` starts the current review round."""

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

    @property
    def effective(self) -> EffectivePeriod:
        return EffectivePeriod(self.effective_from, self.effective_to)


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


def in_force(record: RuleVersionRecord, as_of: date) -> bool:
    """Whether the version was published and ``as_of`` falls in ``[effective_from,
    effective_to)``."""
    return record.status in IN_FORCE_STATUSES and record.effective.contains(as_of)


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
