"""Checks a rule candidate has to pass before anyone reads it.

Every check is deterministic and runs on the candidate and the parsed document alone. A failed
check does not discard the candidate: it becomes an issue on the review task, and any issue
sends the candidate to a person. The checks: every clause the candidate cites exists; every
quote is in its clause; every number the candidate asserts (an amount, a due day, a date) is
written in a cited clause in some spelling the regulator uses; dates are ordered; predicates
use attributes, operators and values the ontology allows; references normalise to something.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date

from domain_kernel.confidence import REVIEW_THRESHOLD
from domain_kernel.documents import ParsedDocument
from domain_kernel.errors import DomainError
from domain_kernel.knowledge import EntityType, normalise_name
from domain_kernel.ontology import Ontology
from domain_kernel.operators import Operator
from domain_kernel.predicates import Predicate
from pipeline.domain.candidate import CandidateFields
from pipeline.domain.numbers import (
    date_forms,
    normalise,
    number_forms,
    small_number_forms,
    text_has,
)


@dataclass(frozen=True, slots=True)
class Issue:
    code: str
    detail: str
    clause_ref: str | None = None


@dataclass(frozen=True, slots=True)
class ValidationReport:
    issues: tuple[Issue, ...]
    citation_count: int
    """Citations whose clause exists and whose quote is in it."""
    confidence: float

    @property
    def ok(self) -> bool:
        return not self.issues

    @property
    def needs_review(self) -> bool:
        return bool(self.issues) or self.confidence < REVIEW_THRESHOLD

    def codes(self) -> tuple[str, ...]:
        return tuple(sorted({issue.code for issue in self.issues}))


def validate(
    candidate: CandidateFields, doc: ParsedDocument, ontology: Ontology
) -> ValidationReport:
    clauses = {clause.clause_ref: clause.text for clause in doc.clauses}
    issues: list[Issue] = []
    verified = 0
    for citation in candidate.citations:
        text = clauses.get(citation.clause_ref)
        if text is None:
            issues.append(
                Issue("citation_missing_clause", citation.clause_ref, citation.clause_ref)
            )
        elif normalise(citation.quote) not in normalise(text):
            issues.append(
                Issue("citation_quote_not_found", citation.quote[:80], citation.clause_ref)
            )
        else:
            verified += 1
    for ref in sorted(candidate.cited_refs() - set(clauses)):
        if ref not in {c.clause_ref for c in candidate.citations}:
            issues.append(Issue("citation_missing_clause", ref, ref))
    cited_text = " ".join(clauses[ref] for ref in candidate.cited_refs() if ref in clauses)
    issues.extend(_numbers(candidate, clauses, cited_text))
    issues.extend(_dates(candidate, cited_text))
    issues.extend(_predicates(candidate, ontology))
    issues.extend(_references(candidate.references))
    return ValidationReport(tuple(issues), verified, candidate.confidence)


def _numbers(
    candidate: CandidateFields, clauses: Mapping[str, str], cited_text: str
) -> Iterable[Issue]:
    for amount in candidate.amounts:
        text = clauses.get(amount.clause_ref, "")
        if not text_has(text, number_forms(amount.value_inr)):
            yield Issue(
                "amount_not_in_clause", f"{amount.label}: {amount.value_inr}", amount.clause_ref
            )
    recurrence = candidate.recurrence
    if recurrence is not None:
        text = clauses.get(recurrence.clause_ref, "")
        if not text_has(text, small_number_forms(recurrence.due_day)):
            yield Issue("due_day_not_in_clause", str(recurrence.due_day), recurrence.clause_ref)
    obligation = candidate.obligation
    if obligation is not None and obligation.due_in_days is not None:
        text = clauses.get(obligation.clause_ref, "")
        if not text_has(text, small_number_forms(obligation.due_in_days)):
            yield Issue(
                "due_in_days_not_in_clause", str(obligation.due_in_days), obligation.clause_ref
            )


def _dates(candidate: CandidateFields, cited_text: str) -> Iterable[Issue]:
    for name, value in (
        ("effective_from", candidate.effective_from),
        ("effective_to", candidate.effective_to),
    ):
        if value is not None and not text_has(cited_text, date_forms(value)):
            yield Issue("date_not_in_cited_clauses", f"{name} {value.isoformat()}")
    if (
        candidate.effective_from is not None
        and candidate.effective_to is not None
        and candidate.effective_to < candidate.effective_from
    ):
        yield Issue("dates_out_of_order", f"{candidate.effective_from} > {candidate.effective_to}")


def _predicates(candidate: CandidateFields, ontology: Ontology) -> Iterable[Issue]:
    for item in candidate.applies_to:
        try:
            predicate = Predicate(item.attribute, Operator(item.operator), item.value)  # type: ignore[arg-type]
            ontology.check_predicate(predicate)
        except (DomainError, ValueError, KeyError) as exc:
            yield Issue(
                "predicate_invalid", f"{item.attribute} {item.operator}: {exc}", item.clause_ref
            )


def _references(references: Iterable[str]) -> Iterable[Issue]:
    for reference in references:
        if not normalise_name(EntityType.NOTIFICATION, reference):
            yield Issue("reference_empty", reference)


def as_of(value: date | None) -> str:
    return "" if value is None else value.isoformat()
