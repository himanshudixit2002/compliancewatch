"""A document's rule extraction as the pipeline keeps it (the ``rule_extraction`` table).

The rule extraction asks the model, through the llm-gateway with the registered prompt
``extraction.rule_candidate@1``, for one candidate per document, and asks once more when the
answer is not a candidate (``domain.candidate``: not JSON, not the schema's shape, or outside the
schema's limits). What it got is stored once per document and prompt version, with its
``rule.candidate.created`` in the same transaction: ``extracted`` with the candidate's fields
and the validators' issues, or ``unparseable`` with no fields and the reason, for an analyst to
draft by hand. The candidate's id is derived from the document and the prompt version, so a
second extraction of the same document by the same prompt names the same candidate.

``suggest_rule_key`` names the rule a candidate may belong to the way the seed calendar names
rules, the form and its cadence (``gstr3b_monthly``): a suggestion for the analyst, never a
lookup in the rulebook.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Final

from domain_kernel._validation import (
    freeze_mapping,
    require_aware,
    require_finite,
    require_instance,
    require_int,
    require_text,
)
from domain_kernel.documents import DocumentType, clause_id_for
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import CandidateId, ClauseId, DocumentId, SourceId, derive_id
from domain_kernel.knowledge import EntityType
from pipeline.domain.candidate import CandidateFields, candidate_from_mapping
from pipeline.domain.classification import extracts_rules
from pipeline.domain.events import RuleCandidateCreated
from pipeline.domain.grammar import find_mentions
from pipeline.domain.issues import Issue
from pipeline.domain.sources import require_source_key

MAX_ANSWER_CHARS: Final = 20_000
"""How much of the model's last answer is kept, for an analyst reading why it was not a
candidate."""
PROMPT_VERSION_PATTERN: Final = r"^[a-z][a-z0-9_.-]*@[0-9]+$"
RULE_KEY_PATTERN: Final = r"^[a-z][a-z0-9_]{0,62}$"
FILING_SCHEMES: Final = {"regular_monthly": "monthly", "regular_qrmp": "quarterly"}
"""The cadence a filing scheme the candidate applies to gives its returns; a composition
taxpayer's returns differ by form, so that scheme names none."""
FILING_FREQUENCIES: Final = frozenset({"monthly", "quarterly"})

_PROMPT_VERSION = re.compile(PROMPT_VERSION_PATTERN)
_RULE_KEY = re.compile(RULE_KEY_PATTERN)


class ExtractionOutcome(StrEnum):
    EXTRACTED = "extracted"
    UNPARSEABLE = "unparseable"


def candidate_id_for(document_id: DocumentId, prompt_version: str) -> CandidateId:
    """The candidate a document's extraction by ``prompt_version`` makes; the same every time."""
    return derive_id(CandidateId, "rule-candidate", str(document_id), prompt_version)


def suggest_rule_key(fields: CandidateFields) -> str | None:
    """``<form>_<cadence>`` as the seed calendar names rules (``gstr3b_monthly``): the first GST
    form the candidate's obligation, title, summary or quotes name, and the cadence of its
    recurrence, else of the filing scheme or return frequency it applies to. None when it names
    no form or no cadence."""
    form = _first_form(_texts(fields))
    cadence = _cadence(fields)
    if form is None or cadence is None:
        return None
    key = f"{re.sub(r'[^a-z0-9]', '', form.lower())}_{cadence}"
    return key if _RULE_KEY.fullmatch(key) else None


def _texts(fields: CandidateFields) -> Iterable[str]:
    if fields.obligation is not None:
        yield fields.obligation.title
        yield from fields.obligation.steps
    yield fields.title
    yield fields.summary
    for citation in fields.citations:
        yield citation.quote


def _first_form(texts: Iterable[str]) -> str | None:
    for text in texts:
        for match in find_mentions(text):
            if match.entity_type is EntityType.FORM and match.proposed_name:
                return match.proposed_name
    return None


def _cadence(fields: CandidateFields) -> str | None:
    if fields.recurrence is not None:
        return fields.recurrence.frequency
    for predicate in fields.applies_to:
        if predicate.operator != "eq" or not isinstance(predicate.value, str):
            continue
        if predicate.attribute == "filing_scheme" and predicate.value in FILING_SCHEMES:
            return FILING_SCHEMES[predicate.value]
        if (
            predicate.attribute == "return_filing_frequency"
            and predicate.value in FILING_FREQUENCIES
        ):
            return predicate.value
    return None


@dataclass(frozen=True, slots=True)
class RuleExtraction:
    """One document's extraction by one prompt version. ``fields`` is the candidate in the
    extraction schema's shape (``CandidateFields.to_mapping``), None for an ``unparseable``
    answer; ``issues`` are the validators' (or why the answer was not a candidate); ``answer``
    is the model's last answer as given, cut at ``MAX_ANSWER_CHARS``; ``attempts`` counts the
    asks (two when the first answer was not a candidate)."""

    document_id: DocumentId
    prompt_version: str
    candidate_id: CandidateId
    outcome: ExtractionOutcome
    model: str
    attempts: int
    source_key: str
    doc_type: DocumentType
    regulator: str
    issues: tuple[Issue, ...]
    citation_count: int
    confidence: float
    needs_review: bool
    answer: str
    ontology_version: str
    extracted_at: datetime
    fields: Mapping[str, object] | None = field(default=None, hash=False)

    def __post_init__(self) -> None:
        require_instance(self.document_id, DocumentId, "document_id")
        version = require_text(self.prompt_version, "prompt_version")
        if not _PROMPT_VERSION.fullmatch(version):
            raise InvariantViolationError(f"prompt_version must look like 'a.b@1', not {version!r}")
        require_instance(self.candidate_id, CandidateId, "candidate_id")
        if self.candidate_id != candidate_id_for(self.document_id, version):
            raise InvariantViolationError("the candidate id is derived from document and prompt")
        require_instance(self.outcome, ExtractionOutcome, "outcome")
        require_text(self.model, "model")
        require_int(self.attempts, "attempts", minimum=1)
        require_source_key(self.source_key)
        require_instance(self.doc_type, DocumentType, "doc_type")
        if not extracts_rules(self.doc_type):
            raise InvariantViolationError(f"no rule is extracted from a {self.doc_type.value}")
        require_text(self.regulator, "regulator")
        for issue in require_instance(self.issues, tuple, "issues"):
            require_instance(issue, Issue, "issue")
        require_int(self.citation_count, "citation_count", minimum=0)
        confidence = require_finite(self.confidence, "confidence")
        if not 0 <= confidence <= 1:
            raise InvariantViolationError(f"confidence must be within [0, 1], got {confidence}")
        require_instance(self.needs_review, bool, "needs_review")
        if len(require_instance(self.answer, str, "answer")) > MAX_ANSWER_CHARS:
            raise InvariantViolationError(f"answer is kept to {MAX_ANSWER_CHARS} characters")
        require_text(self.ontology_version, "ontology_version")
        require_aware(self.extracted_at, "extracted_at")
        if (self.outcome is ExtractionOutcome.EXTRACTED) != (self.fields is not None):
            raise InvariantViolationError("an extracted candidate has fields; an unparseable none")
        if self.fields is not None:
            object.__setattr__(self, "fields", freeze_mapping(self.fields, "fields"))
        if self.outcome is ExtractionOutcome.UNPARSEABLE and not self.needs_review:
            raise InvariantViolationError("an unparseable answer needs review")

    def candidate(self) -> CandidateFields | None:
        """The fields read back as ``CandidateFields``; None for an unparseable answer."""
        return None if self.fields is None else candidate_from_mapping(self.fields)

    def clause_ids(self) -> tuple[ClauseId, ...]:
        """The ids of the clauses the candidate cites or leans on, in clause-ref order."""
        candidate = self.candidate()
        if candidate is None:
            return ()
        refs = sorted(candidate.cited_refs())
        return tuple(clause_id_for(self.document_id, ref) for ref in refs)

    def suggested_rule_key(self) -> str | None:
        candidate = self.candidate()
        return None if candidate is None else suggest_rule_key(candidate)

    def event(self, source_id: SourceId) -> RuleCandidateCreated:
        """Its ``rule.candidate.created``, written with it."""
        return RuleCandidateCreated(
            source_id=source_id,
            document_id=self.document_id,
            candidate_id=self.candidate_id,
            regulator=self.regulator,
            model=self.model,
            prompt_version=self.prompt_version,
            confidence=self.confidence,
            citation_count=self.citation_count,
            needs_review=self.needs_review,
            source_key=self.source_key,
            doc_type=self.doc_type,
            outcome=self.outcome.value,
            candidate=None if self.fields is None else dict(self.fields),
            issues=self.issues,
            suggested_rule_key=self.suggested_rule_key(),
            clause_ids=self.clause_ids(),
            ontology_version=self.ontology_version,
        )
