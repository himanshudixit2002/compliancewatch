"""Scores for one extraction case and their aggregates.

A case is accepted when every labelled field matches and the validators raise nothing: that is
the "approved without edits" of the guide's extraction-acceptance metric, measured against a
label instead of a reviewer. Field accuracy, reference and predicate F1, citation validity and
the deterministic detector's accuracy are reported alongside so a drop has a cause.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from pipeline.application.detector import detect
from pipeline.application.extractor import ExtractionOutcome
from pipeline.domain.candidate import CandidateFields, candidate_from_mapping
from pipeline.label import GoldenCase

SCALAR_FIELDS = ("doc_kind", "change_kind", "effective_from", "effective_to")


@dataclass(frozen=True, slots=True)
class CaseScore:
    case_id: str
    label_status: str
    parsed: bool
    field_matches: dict[str, bool] = field(default_factory=dict)
    references_f1: float = 0.0
    predicates_f1: float = 0.0
    amounts_f1: float = 0.0
    obligation_match: bool = False
    recurrence_match: bool = False
    citation_validity: float = 0.0
    validator_issues: tuple[str, ...] = ()
    detector_doc_kind_ok: bool = False
    detector_change_kind_ok: bool = False
    model: str = ""

    @property
    def accepted(self) -> bool:
        return (
            self.parsed
            and all(self.field_matches.values())
            and self.references_f1 == 1.0
            and self.predicates_f1 == 1.0
            and self.amounts_f1 == 1.0
            and self.obligation_match
            and self.recurrence_match
            and not self.validator_issues
        )


@dataclass(frozen=True, slots=True)
class Aggregate:
    cases: int
    extraction_acceptance: float
    field_accuracy: float
    references_f1: float
    predicates_f1: float
    citation_validity: float
    validator_pass_rate: float
    detector_accuracy: float
    parse_rate: float


def score(case: GoldenCase, outcome: ExtractionOutcome) -> CaseScore:
    assert case.expected is not None
    expected = candidate_from_mapping(case.expected)
    detection = detect(case.document, own_ref=str(case.source.get("number", "")))
    detector_doc = detection.doc_type.value == expected.doc_kind
    detector_change = detection.change_kind.value == expected.change_kind
    got = outcome.fields
    if got is None:
        return CaseScore(
            case.case_id,
            case.label_status,
            parsed=False,
            validator_issues=outcome.report.codes(),
            detector_doc_kind_ok=detector_doc,
            detector_change_kind_ok=detector_change,
            model=outcome.model,
        )
    total = len(outcome.report.issues) + outcome.report.citation_count
    return CaseScore(
        case.case_id,
        case.label_status,
        parsed=True,
        field_matches={
            name: getattr(got, name) == getattr(expected, name) for name in SCALAR_FIELDS
        },
        references_f1=_set_f1(_normalised_refs(got), _normalised_refs(expected)),
        predicates_f1=_set_f1(_predicates(got), _predicates(expected)),
        amounts_f1=_set_f1(_amounts(got), _amounts(expected)),
        obligation_match=_obligation(got) == _obligation(expected),
        recurrence_match=_recurrence(got) == _recurrence(expected),
        citation_validity=outcome.report.citation_count / len(got.citations)
        if got.citations
        else 0.0,
        validator_issues=outcome.report.codes() if total else (),
        detector_doc_kind_ok=detector_doc,
        detector_change_kind_ok=detector_change,
        model=outcome.model,
    )


def aggregate(scores: Sequence[CaseScore]) -> Aggregate:
    count = len(scores)
    if count == 0:
        return Aggregate(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    fields = [match for s in scores for match in s.field_matches.values()]
    return Aggregate(
        cases=count,
        extraction_acceptance=_share(s.accepted for s in scores),
        field_accuracy=_share(fields) if fields else 0.0,
        references_f1=sum(s.references_f1 for s in scores) / count,
        predicates_f1=sum(s.predicates_f1 for s in scores) / count,
        citation_validity=sum(s.citation_validity for s in scores) / count,
        validator_pass_rate=_share(not s.validator_issues and s.parsed for s in scores),
        detector_accuracy=_share(
            ok for s in scores for ok in (s.detector_doc_kind_ok, s.detector_change_kind_ok)
        ),
        parse_rate=_share(s.parsed for s in scores),
    )


def _share(values: Iterable[bool]) -> float:
    items = list(values)
    return sum(1 for v in items if v) / len(items) if items else 0.0


def _set_f1(got: set[object], expected: set[object]) -> float:
    if not got and not expected:
        return 1.0
    hits = len(got & expected)
    if hits == 0:
        return 0.0
    precision, recall = hits / len(got), hits / len(expected)
    return 2 * precision * recall / (precision + recall)


def _normalised_refs(fields: CandidateFields) -> set[object]:
    from domain_kernel.knowledge import EntityType, normalise_name

    return {normalise_name(EntityType.NOTIFICATION, r) for r in fields.references}


def _predicates(fields: CandidateFields) -> set[object]:
    return {(p.attribute, p.operator, _hashable(p.value)) for p in fields.applies_to}


def _amounts(fields: CandidateFields) -> set[object]:
    return {a.value_inr for a in fields.amounts}


def _obligation(fields: CandidateFields) -> object:
    o = fields.obligation
    return None if o is None else (o.title.casefold(), o.due_in_days, o.evidence_type)


def _recurrence(fields: CandidateFields) -> object:
    r = fields.recurrence
    return None if r is None else (r.frequency, r.due_day, r.due_month_offset)


def _hashable(value: object) -> object:
    if isinstance(value, list | tuple):
        return tuple(sorted(str(v) for v in value))
    return value
