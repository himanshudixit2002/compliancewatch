"""A dry run: what a rule version, or a specification not stored anywhere, would decide for the
businesses of the directory, before anyone publishes it (the impact explorer's counts).

``DryRun.run(request)`` evaluates the specification the way a fan-out does, deterministically and
for the current financial year in India, against every business the business directory lists at
the level, of one tenant when the scope names one:

1. the specification: the version's, read from the rulebook in any status (a draft, a version
   under review or approved, as well as a published one), or the request's own with its level;
2. the directory entries in scope, counted first: more than ``max_businesses``
   (``CW_APPLICABILITY_DRY_RUN_MAX``) is refused before anything is read;
3. each business's profile snapshot from the profile service, evaluated in the process. A
   business the profile service no longer has is skipped.

The reads run with no transaction open: the directory's own short reads and the HTTP calls. It
stores no decision, opens no review item and publishes no event. The one thing it writes is its
audit entry, ``applicability.dry_run``, of no tenant (it answers the regulatory team, whatever
tenant the scope names), with the actor and what it found: the scope and the counts; ``before``
is empty, since nothing changed.

The report counts the businesses by result and, for each attribute that decided a result
(``domain.evaluation.deciding_attributes``), by result again, and keeps up to ``sample_size``
decisions, taken in directory order a result at a time (applies, not_applicable, unsure, then
round again), so every result found has its examples.
"""

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Final

from applicability_engine.domain.directory import DirectoryKey
from applicability_engine.domain.errors import DryRunTooLargeError, RuleVersionNotFoundError
from applicability_engine.domain.evaluation import deciding_attributes, evaluate
from applicability_engine.domain.ports import ProfileReader, RulebookReader
from applicability_engine.domain.repository import (
    BusinessDirectoryReader,
    FanOutUnitOfWorkFactory,
)
from domain_kernel.audit import AuditActor, AuditEntry
from domain_kernel.confidence import Confidence
from domain_kernel.errors import InvariantViolationError
from domain_kernel.events import utc_now
from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import BusinessId, RuleVersionId, TenantId
from domain_kernel.ontology import AttributeLevel, Ontology
from domain_kernel.predicates import (
    Applicability,
    PredicateResult,
    Specification,
    specification_to_mapping,
)
from domain_kernel.status import RuleVersionStatus

DRY_RUN_ACTION: Final = "applicability.dry_run"
VERSION_SUBJECT: Final = "rule_version"
SPECIFICATION_SUBJECT: Final = "specification"
DEFAULT_SAMPLE: Final = 10
MAX_SAMPLE: Final = 50
DEFAULT_MAX_BUSINESSES: Final = 2_000
PAGE: Final = 500
"""Directory entries one read returns."""
IST: Final = timezone(timedelta(hours=5, minutes=30))
"""Financial years are India's."""


@dataclass(frozen=True, slots=True)
class DryRunRequest:
    """A dry run of ``rule_version_id`` or of ``specification`` (with its ``level``), over the
    directory entries of the level, of ``tenant_id`` alone when named. ``actor`` is who the
    audit entry names."""

    actor: AuditActor
    rule_version_id: RuleVersionId | None = None
    specification: Specification | None = None
    level: AttributeLevel | None = None
    tenant_id: TenantId | None = None
    sample_size: int = DEFAULT_SAMPLE
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        if (self.rule_version_id is None) == (self.specification is None):
            raise InvariantViolationError("name a rule version or give a specification, not both")
        if self.specification is not None and self.level is None:
            raise InvariantViolationError("a specification needs the level it applies to")
        if not 0 <= self.sample_size <= MAX_SAMPLE:
            raise InvariantViolationError(f"sample_size must be 0 to {MAX_SAMPLE}")


@dataclass(frozen=True, slots=True)
class DryRunSample:
    """One business as the dry run decided it: the result with its confidence, the attributes
    that decided it, and every predicate's outcome."""

    tenant_id: TenantId
    business_id: BusinessId
    profile_version: int
    result: Applicability
    confidence: Confidence
    deciding: tuple[str, ...]
    evaluated: tuple[PredicateResult, ...]

    @property
    def needs_review(self) -> bool:
        return self.result is Applicability.UNSURE or self.confidence.needs_review()


@dataclass(frozen=True, slots=True)
class AttributeCounts:
    """The businesses whose result an attribute decided, by result."""

    attribute: str
    counts: Mapping[Applicability, int]


@dataclass(frozen=True, slots=True)
class DryRunReport:
    """What a dry run found. ``businesses_total`` is the directory entries in scope,
    ``evaluated`` the businesses decided and ``skipped`` those the profile service no longer
    has. ``rule_key`` and ``status`` are the version's when one was named."""

    level: AttributeLevel
    as_of_fy: FinancialYear
    businesses_total: int
    evaluated: int
    skipped: int
    counts: Mapping[Applicability, int]
    needs_review: int
    by_attribute: tuple[AttributeCounts, ...]
    samples: tuple[DryRunSample, ...]
    max_businesses: int
    ran_at: datetime
    rule_version_id: RuleVersionId | None = None
    rule_key: str | None = None
    status: RuleVersionStatus | None = None
    tenant_id: TenantId | None = None


@dataclass
class _Tally:
    sample_size: int
    evaluated: int = 0
    skipped: int = 0
    needs_review: int = 0
    counts: dict[Applicability, int] = field(
        default_factory=lambda: dict.fromkeys(Applicability, 0)
    )
    by_attribute: dict[str, dict[Applicability, int]] = field(default_factory=dict)
    samples: dict[Applicability, list[DryRunSample]] = field(
        default_factory=lambda: {result: [] for result in Applicability}
    )

    def add(self, sample: DryRunSample) -> None:
        self.evaluated += 1
        self.counts[sample.result] += 1
        self.needs_review += sample.needs_review
        for attribute in sample.deciding:
            counts = self.by_attribute.setdefault(attribute, dict.fromkeys(Applicability, 0))
            counts[sample.result] += 1
        kept = self.samples[sample.result]
        if len(kept) < self.sample_size:
            kept.append(sample)

    def chosen(self) -> tuple[DryRunSample, ...]:
        """Up to ``sample_size`` samples, a result at a time in the order of ``Applicability``."""
        queues = [list(self.samples[result]) for result in Applicability]
        chosen: list[DryRunSample] = []
        while len(chosen) < self.sample_size and any(queues):
            for queue in queues:
                if queue and len(chosen) < self.sample_size:
                    chosen.append(queue.pop(0))
        return tuple(chosen)


class DryRun:
    def __init__(
        self,
        directory: BusinessDirectoryReader,
        fanouts: FanOutUnitOfWorkFactory,
        profiles: ProfileReader,
        rulebook: RulebookReader,
        ontology: Ontology,
        *,
        max_businesses: int = DEFAULT_MAX_BUSINESSES,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if max_businesses < 1:
            raise ValueError("max_businesses must be at least 1")
        self._directory = directory
        self._fanouts = fanouts
        self._profiles = profiles
        self._rulebook = rulebook
        self._ontology = ontology
        self._max = max_businesses
        self._clock = clock

    def run(self, request: DryRunRequest) -> DryRunReport:
        specification, level, version = self._specification(request)
        listed = self._directory.count(level=level, tenant_id=request.tenant_id)
        if listed > self._max:
            raise DryRunTooLargeError(listed, self._max, level.value)
        now = self._clock()
        fy = FinancialYear.for_date(now.astimezone(IST).date())
        tally = _Tally(request.sample_size)
        read = 0
        after: DirectoryKey | None = None
        while True:
            entries = self._directory.entries(
                level=level, after=after, limit=PAGE, tenant_id=request.tenant_id
            )
            for entry in entries:
                read += 1
                if read > self._max:
                    raise DryRunTooLargeError(read, self._max, level.value)
                snapshot = self._profiles.snapshot(entry.tenant_id, entry.business_id, fy)
                if snapshot is None:
                    tally.skipped += 1
                    continue
                evaluation = evaluate(specification, snapshot.attributes, self._ontology)
                tally.add(
                    DryRunSample(
                        tenant_id=entry.tenant_id,
                        business_id=entry.business_id,
                        profile_version=snapshot.version,
                        result=evaluation.result,
                        confidence=evaluation.confidence,
                        deciding=deciding_attributes(specification, evaluation.evaluated),
                        evaluated=evaluation.evaluated,
                    )
                )
            if len(entries) < PAGE:
                break
            after = DirectoryKey.of(entries[-1])
        report = DryRunReport(
            level=level,
            as_of_fy=fy,
            businesses_total=read,
            evaluated=tally.evaluated,
            skipped=tally.skipped,
            counts=dict(tally.counts),
            needs_review=tally.needs_review,
            by_attribute=tuple(
                AttributeCounts(attribute, dict(counts))
                for attribute, counts in sorted(tally.by_attribute.items())
            ),
            samples=tally.chosen(),
            max_businesses=self._max,
            ran_at=now,
            rule_version_id=request.rule_version_id,
            rule_key=None if version is None else version[0],
            status=None if version is None else version[1],
            tenant_id=request.tenant_id,
        )
        with self._fanouts() as uow:
            uow.audit.write(_audit_entry(request, specification, report))
        return report

    def _specification(
        self, request: DryRunRequest
    ) -> tuple[Specification, AttributeLevel, tuple[str | None, RuleVersionStatus] | None]:
        """The specification to evaluate, its level, and the version's rule key and status."""
        if request.rule_version_id is None:
            if request.specification is None or request.level is None:  # pragma: no cover
                raise InvariantViolationError("a specification needs the level it applies to")
            return request.specification, request.level, None
        version = self._rulebook.rule_version(request.rule_version_id)
        if version is None:
            raise RuleVersionNotFoundError(str(request.rule_version_id))
        level = version.level or request.level
        if level is None:
            raise InvariantViolationError(
                f"the rulebook names no level for rule version {version.rule_version_id}; give "
                "the scope's level"
            )
        if request.level is not None and request.level is not level:
            raise InvariantViolationError(
                f"rule version {version.rule_version_id} applies to {level.value} nodes, not "
                f"{request.level.value}"
            )
        return version.specification, level, (version.rule_key, version.status)


def specification_digest(specification: Specification) -> str:
    """How the audit log names an inline specification: the first 32 hex digits of the SHA-256
    of its mapping as sorted JSON."""
    mapping = specification_to_mapping(specification)
    text = json.dumps(mapping, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode()).hexdigest()[:32]


def _audit_entry(
    request: DryRunRequest, specification: Specification, report: DryRunReport
) -> AuditEntry:
    """The dry run's audit entry, of no tenant: the actor, the scope and the counts."""
    if request.rule_version_id is not None:
        subject_type, subject_id = VERSION_SUBJECT, str(request.rule_version_id)
    else:
        subject_type, subject_id = SPECIFICATION_SUBJECT, specification_digest(specification)
    return AuditEntry(
        action=DRY_RUN_ACTION,
        tenant_id=None,
        subject_type=subject_type,
        subject_id=subject_id,
        actor=request.actor,
        before=None,
        after={
            "level": report.level.value,
            "tenant_id": None if report.tenant_id is None else str(report.tenant_id),
            "as_of_fy": report.as_of_fy.label,
            "businesses_total": report.businesses_total,
            "evaluated": report.evaluated,
            "skipped": report.skipped,
            "counts": {result.value: count for result, count in report.counts.items()},
            "needs_review": report.needs_review,
        },
        occurred_at=report.ran_at,
        correlation_id=request.correlation_id,
    )
