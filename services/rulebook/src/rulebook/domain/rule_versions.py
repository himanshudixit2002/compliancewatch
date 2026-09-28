"""Rule versions and their citations as the read API returns them.

A version is in force on a date when it has been published and the date falls in its half-open
effective period. A superseded version counts: it was published, and its ``effective_to`` is
cut to the day its replacement takes effect, so a question about an earlier date still sees it.
A withdrawn version never counts, and neither does one that was never published.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from domain_kernel.ids import ClauseId, DocumentId, RuleId, RuleVersionId
from domain_kernel.ontology import AttributeLevel
from domain_kernel.periods import EffectivePeriod
from domain_kernel.status import RuleVersionStatus
from rulebook.domain.seed import SeedStatus

IN_FORCE_STATUSES = frozenset({RuleVersionStatus.PUBLISHED, RuleVersionStatus.SUPERSEDED})
"""Statuses of a version that has been published: only these can be in force on a date."""


@dataclass(frozen=True, slots=True)
class RuleVersionRecord:
    """One rule version with its rule's key, regulator and level. Specification, template and
    recurrence are the kernel's mapping forms, as stored."""

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
