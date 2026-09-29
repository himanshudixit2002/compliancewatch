"""Data-quality checks over the rulebook's versions, citations and relations.

The constraints and triggers of the rulebook schema stop most bad rows at write time. These
checks look for what they cannot see one row at a time, and repeat one that they can, as
defence in depth:

- ``in_force_without_verified_citation``: a published or superseded version with no citation,
  or with a citation that is not verified. ADR-006 asks for every citation of a version to be
  verified before the version is published.
- ``overlapping_in_force_periods``: two published or superseded versions of one rule whose
  half-open effective periods ``[from, to)`` overlap, so a date has two answers.
- ``supersession_cycle``: a cycle in the graph of ``supersedes`` and ``corrects`` edges between
  rule versions, found with the same search that refuses a cycle at approval time.
- ``unknown_predicate_attribute``: a version, other than a withdrawn one, whose specification
  names an attribute the ontology does not define, or cannot be read at all. The seed loader's
  rule applies: a free-text predicate may name an attribute the ontology lacks while the version
  carries an open analyst question (its ``todo`` list), so the question is on record until the
  analyst adds the attribute to the ontology or rewrites the predicate. A structured predicate
  never may, since the ontology decides it.
- ``effective_dates_disordered``: an ``effective_to`` on or before ``effective_from``, which
  ``ck_rule_version_effective`` also refuses.

The checks are pure: they take plain facts read from storage and return the violations, so the
same code runs on a local seed, in the nightly job and in unit tests.
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from domain_kernel.errors import DomainError
from domain_kernel.ids import RuleVersionId
from domain_kernel.knowledge import RelationKind
from domain_kernel.ontology import Ontology
from domain_kernel.predicates import PredicateKind, specification_from_mapping
from domain_kernel.status import RuleVersionStatus
from rulebook.domain.relations import find_supersedes_cycle

IN_FORCE_STATUSES = frozenset({RuleVersionStatus.PUBLISHED, RuleVersionStatus.SUPERSEDED})
"""Versions that decide obligations for some dates: the current one and the ones it replaced."""

CYCLE_RELATIONS = frozenset({RelationKind.SUPERSEDES, RelationKind.CORRECTS})
"""The edges that replace one version by another; a cycle among them has no latest version."""


class QualityCheck(StrEnum):
    IN_FORCE_WITHOUT_VERIFIED_CITATION = "in_force_without_verified_citation"
    OVERLAPPING_IN_FORCE_PERIODS = "overlapping_in_force_periods"
    SUPERSESSION_CYCLE = "supersession_cycle"
    UNKNOWN_PREDICATE_ATTRIBUTE = "unknown_predicate_attribute"
    EFFECTIVE_DATES_DISORDERED = "effective_dates_disordered"


@dataclass(frozen=True, slots=True)
class VersionFacts:
    """What the checks need to know about one rule version."""

    rule_version_id: RuleVersionId
    rule_key: str
    version: int
    status: RuleVersionStatus
    effective_from: date
    effective_to: date | None
    specification: Mapping[str, object]
    citations: int = 0
    verified_citations: int = 0
    open_questions: int = 0

    @property
    def label(self) -> str:
        return f"{self.rule_key}@{self.version}"

    @property
    def in_force(self) -> bool:
        return self.status in IN_FORCE_STATUSES

    @property
    def period(self) -> str:
        end = "open" if self.effective_to is None else self.effective_to.isoformat()
        return f"[{self.effective_from.isoformat()}, {end})"


@dataclass(frozen=True, slots=True)
class RelationFacts:
    """One edge from a rule version to another rule version."""

    from_rule_version_id: RuleVersionId
    relation: RelationKind
    to_rule_version_id: RuleVersionId


@dataclass(frozen=True, slots=True)
class QualityFacts:
    versions: tuple[VersionFacts, ...] = ()
    relations: tuple[RelationFacts, ...] = ()


@dataclass(frozen=True, slots=True)
class Violation:
    check: QualityCheck
    subject: str
    detail: str


@dataclass(frozen=True, slots=True)
class QualityReport:
    versions_checked: int
    relations_checked: int
    violations: tuple[Violation, ...] = field(default=())

    @property
    def ok(self) -> bool:
        return not self.violations

    def of(self, check: QualityCheck) -> tuple[Violation, ...]:
        return tuple(violation for violation in self.violations if violation.check is check)


def in_force_without_verified_citation(facts: QualityFacts) -> list[Violation]:
    found: list[Violation] = []
    for version in facts.versions:
        if not version.in_force:
            continue
        if version.citations == 0:
            detail = f"{version.status.value} with no citation"
        elif version.verified_citations < version.citations:
            unverified = version.citations - version.verified_citations
            detail = (
                f"{version.status.value} with {unverified} of {version.citations} citations "
                "not verified"
            )
        else:
            continue
        found.append(
            Violation(QualityCheck.IN_FORCE_WITHOUT_VERIFIED_CITATION, version.label, detail)
        )
    return found


def overlapping_in_force_periods(facts: QualityFacts) -> list[Violation]:
    by_rule: dict[str, list[VersionFacts]] = {}
    for version in facts.versions:
        if version.in_force:
            by_rule.setdefault(version.rule_key, []).append(version)
    found: list[Violation] = []
    for rule_key in sorted(by_rule):
        versions = sorted(by_rule[rule_key], key=lambda v: (v.effective_from, v.version))
        for index, earlier in enumerate(versions):
            for later in versions[index + 1 :]:
                if _overlap(earlier, later):
                    found.append(
                        Violation(
                            QualityCheck.OVERLAPPING_IN_FORCE_PERIODS,
                            f"{earlier.label} and {later.label}",
                            f"{earlier.period} overlaps {later.period}",
                        )
                    )
    return found


def supersession_cycle(facts: QualityFacts) -> list[Violation]:
    edges: dict[RuleVersionId, set[RuleVersionId]] = {}
    for relation in facts.relations:
        if relation.relation in CYCLE_RELATIONS:
            edges.setdefault(relation.from_rule_version_id, set()).add(relation.to_rule_version_id)
    graph = {source: frozenset(targets) for source, targets in edges.items()}
    labels = {version.rule_version_id: version.label for version in facts.versions}
    seen: set[frozenset[RuleVersionId]] = set()
    found: list[Violation] = []
    for source in sorted(graph, key=str):
        for target in sorted(graph[source], key=str):
            path = find_supersedes_cycle(graph, source, target)
            if path is None or frozenset(path) in seen:
                continue
            seen.add(frozenset(path))
            cycle = (*path, path[0])
            found.append(
                Violation(
                    QualityCheck.SUPERSESSION_CYCLE,
                    " -> ".join(labels.get(node, str(node)) for node in cycle),
                    f"{len(path)} versions replace each other in a cycle",
                )
            )
    return found


def unknown_predicate_attribute(facts: QualityFacts, ontology: Ontology) -> list[Violation]:
    found: list[Violation] = []
    for version in facts.versions:
        if version.status is RuleVersionStatus.WITHDRAWN:
            continue
        try:
            predicates = tuple(specification_from_mapping(version.specification).predicates())
        except DomainError as exc:
            found.append(
                Violation(
                    QualityCheck.UNKNOWN_PREDICATE_ATTRIBUTE,
                    version.label,
                    f"specification cannot be read: {exc}",
                )
            )
            continue
        unknown = sorted(
            {
                predicate.attribute
                for predicate in predicates
                if predicate.attribute not in ontology
                and not (predicate.kind is PredicateKind.FREE_TEXT and version.open_questions)
            }
        )
        if unknown:
            found.append(
                Violation(
                    QualityCheck.UNKNOWN_PREDICATE_ATTRIBUTE,
                    version.label,
                    f"not in ontology {ontology.version}: {', '.join(unknown)}",
                )
            )
    return found


def effective_dates_disordered(facts: QualityFacts) -> list[Violation]:
    return [
        Violation(
            QualityCheck.EFFECTIVE_DATES_DISORDERED,
            version.label,
            f"effective_to {version.effective_to.isoformat()} is not after "
            f"effective_from {version.effective_from.isoformat()}",
        )
        for version in facts.versions
        if version.effective_to is not None and version.effective_to <= version.effective_from
    ]


def run_checks(facts: QualityFacts, ontology: Ontology) -> QualityReport:
    """Every check over the facts, in the order of ``QualityCheck``."""
    checks: Mapping[QualityCheck, Callable[[QualityFacts], Iterable[Violation]]] = {
        QualityCheck.IN_FORCE_WITHOUT_VERIFIED_CITATION: in_force_without_verified_citation,
        QualityCheck.OVERLAPPING_IN_FORCE_PERIODS: overlapping_in_force_periods,
        QualityCheck.SUPERSESSION_CYCLE: supersession_cycle,
        QualityCheck.UNKNOWN_PREDICATE_ATTRIBUTE: lambda f: unknown_predicate_attribute(
            f, ontology
        ),
        QualityCheck.EFFECTIVE_DATES_DISORDERED: effective_dates_disordered,
    }
    violations = tuple(violation for check in QualityCheck for violation in checks[check](facts))
    return QualityReport(len(facts.versions), len(facts.relations), violations)


def _overlap(first: VersionFacts, second: VersionFacts) -> bool:
    """Half-open periods ``[from, to)`` overlap when each starts before the other ends."""
    first_before_second_ends = (
        second.effective_to is None or first.effective_from < second.effective_to
    )
    second_before_first_ends = (
        first.effective_to is None or second.effective_from < first.effective_to
    )
    return first_before_second_ends and second_before_first_ends
