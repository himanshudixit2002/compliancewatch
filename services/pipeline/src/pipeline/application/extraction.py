"""The rule extraction in the workflow: one candidate per classified document, through the
llm-gateway, stored once with its ``rule.candidate.created``.

Two activities, so a failed write never asks the model again:

1. ``ExtractRules`` (``pipeline.extract_rules``) reads the document as the rulebook keeps it
   (``RulebookReader.parsed_document``: every citation then points at a stored clause) and asks
   the model with the registered prompt ``extraction.rule_candidate@1`` through the
   ``RuleExtractionStage``: once, and once more, at a small temperature the gateway's cache
   does not answer, when the answer is not a candidate (not JSON, not the schema's shape, or
   outside the schema's limits, ``domain.candidate.conformance_problems``). It writes nothing
   and returns the answer as data. An extraction stored before for the document and the prompt
   version is returned as it is, and no model is asked. A budget the gateway says is used up
   (``ModelBudgetExhaustedError``) fails the attempt at once, with the ``Retry-After`` in the
   failure's details, for the workflow to wait out (``workflows.extract_rules``).
2. ``StoreExtraction`` (``pipeline.store_extraction``) stores the extraction, keyed by the
   document and the prompt version, with its ``rule.candidate.created`` and the document's
   ``extracted`` status, in one transaction; an extraction stored before writes nothing.

Both answer ``skipped`` while ``CW_PIPELINE_EXTRACTION_ENABLED`` is off, with no call.
"""

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, ClassVar, Final, Self
from uuid import UUID

from pydantic import Field, model_validator
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from domain_kernel.documents import DocumentType, ExtractionContext, ParsedDocument
from domain_kernel.events import utc_now
from domain_kernel.ids import DocumentId, SourceId
from ontology import VERSION as ONTOLOGY_VERSION
from pipeline.application.activities import Frozen, on_thread
from pipeline.application.extractor import LlmRuleExtractor
from pipeline.application.knowledge_activities import IssueOut
from pipeline.application.validators import ValidationReport
from pipeline.domain.candidate import CandidateFields, conformance_problems
from pipeline.domain.classification import extracts_rules
from pipeline.domain.errors import ModelBudgetExhaustedError
from pipeline.domain.extraction import (
    MAX_ANSWER_CHARS,
    ExtractionOutcome,
    RuleExtraction,
    candidate_id_for,
)
from pipeline.domain.issues import Issue
from pipeline.domain.ports import RulebookReader
from pipeline.domain.raw_documents import DocumentStatus
from pipeline.domain.repository import UnitOfWorkFactory
from py_common.logging import get_logger
from py_common.temporal import ActivityBase

log = get_logger(__name__)

RULE_PROMPT: Final = ("extraction.rule_candidate", "1")
"""The registered prompt the extraction asks with (owner regulatory-intelligence, eval cases in
evals/golden/extraction)."""
RULE_PROMPT_REF: Final = f"{RULE_PROMPT[0]}@{RULE_PROMPT[1]}"
RETRY_TEMPERATURE: Final = 0.3
"""The second ask's temperature: high enough for a fresh sample, low enough to stay on task."""
BUDGET_ERROR: Final = "ModelBudgetExhaustedError"
"""The failure type of an attempt the gateway refused for a used-up budget."""
BUDGET_MIN_WAIT: Final = 15 * 60
BUDGET_MAX_WAIT: Final = 6 * 60 * 60
BUDGET_MAX_WAITS: Final = 160
"""A used-up budget is asked about again after its ``Retry-After``, between 15 minutes and 6
hours (a raised budget takes effect before the month ends), at most 160 times: some 40 days."""


@dataclass(frozen=True, slots=True)
class StageAnswer:
    """What the stage got: the candidate (None when the answer was not one), its validation, the
    model that answered, its last answer as given and how many asks it took."""

    fields: CandidateFields | None
    report: ValidationReport
    model: str
    answer: str
    attempts: int

    @property
    def needs_review(self) -> bool:
        return self.fields is None or self.report.needs_review


class RuleExtractionStage:
    """The extractor, asked again once when its answer is not a candidate."""

    def __init__(self, extractor: LlmRuleExtractor) -> None:
        self._extractor = extractor

    @property
    def prompt_ref(self) -> str:
        return self._extractor.prompt_ref

    def run(self, doc: ParsedDocument, ctx: ExtractionContext) -> StageAnswer:
        first = self._ask(doc, ctx, attempt=1)
        if first.fields is not None:
            return first
        log.warning(
            "pipeline.extraction_not_a_candidate",
            document_id=str(doc.document_id),
            issues=list(first.report.codes()),
        )
        return self._ask(doc, ctx, attempt=2)

    def _ask(self, doc: ParsedDocument, ctx: ExtractionContext, *, attempt: int) -> StageAnswer:
        outcome = self._extractor.run(
            doc, ctx, temperature=0.0 if attempt == 1 else RETRY_TEMPERATURE, attempt=attempt
        )
        fields, report = outcome.fields, outcome.report
        problems = () if fields is None else conformance_problems(fields)
        if problems:
            fields = None
            report = ValidationReport((Issue("output_unparseable", "; ".join(problems)),), 0, 0.0)
        return StageAnswer(fields, report, outcome.model, outcome.raw_text, attempt)


class ExtractionRequest(Frozen):
    """The document to extract a rule candidate from, as the classify step placed it. The
    ``*_wait*`` fields bound the waits for a used-up budget (tests shorten them)."""

    document_id: UUID
    source_id: UUID
    source_key: str = Field(min_length=1)
    regulator: str = Field(min_length=1)
    doc_type: DocumentType
    own_ref: str = ""
    min_wait_seconds: int = Field(default=BUDGET_MIN_WAIT, ge=1)
    max_wait_seconds: int = Field(default=BUDGET_MAX_WAIT, ge=1)
    max_waits: int = Field(default=BUDGET_MAX_WAITS, ge=0)

    @model_validator(mode="after")
    def _a_rule_kind(self) -> Self:
        if not extracts_rules(self.doc_type):
            raise ValueError(f"no rule is extracted from a {self.doc_type.value}")
        if self.min_wait_seconds > self.max_wait_seconds:
            raise ValueError("min_wait_seconds must not exceed max_wait_seconds")
        return self


class ExtractionAnswer(Frozen):
    """The model's answer as it crosses the workflow, for ``StoreExtraction`` to write:
    ``fields`` in the extraction schema's shape (None when it was not a candidate). ``stored``
    says the extraction was stored before and nothing is to be written; ``skipped`` that the
    extraction is off."""

    request: ExtractionRequest
    prompt_version: str = ""
    outcome: str = ExtractionOutcome.UNPARSEABLE.value
    model: str = ""
    attempts: int = 0
    fields: dict[str, Any] | None = None
    issues: list[IssueOut] = Field(default_factory=list)
    citation_count: int = 0
    confidence: float = 0.0
    needs_review: bool = True
    answer: str = Field(default="", max_length=MAX_ANSWER_CHARS)
    ontology_version: str = ""
    stored: bool = False
    skipped: bool = False


class ExtractionStored(Frozen):
    """The candidate the extraction made: written now (``created``), or stored before."""

    document_id: UUID
    candidate_id: UUID | None = None
    outcome: str = ""
    needs_review: bool = True
    created: bool = False
    skipped: bool = False


EXTRACT_RETRIES: Final = RetryPolicy(
    initial_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=10),
    maximum_attempts=6,
    non_retryable_error_types=[
        BUDGET_ERROR,
        "RulebookRejectedError",
        "KnowledgeContractError",
        "InvariantViolationError",
    ],
)
"""A gateway or rulebook outage is waited out for a quarter of an hour; a used-up budget is the
workflow's to wait out; a document the rulebook does not hold is not asked about again."""

STORE_RETRIES: Final = RetryPolicy(
    maximum_attempts=20,
    non_retryable_error_types=["InvariantViolationError", "DocumentNotFoundError"],
)
"""The write waits out a database that is away for a while; the answer it writes stays in the
workflow's history meanwhile, so no model is asked again."""


class ExtractRules(ActivityBase[ExtractionRequest, ExtractionAnswer]):
    """Ask the model for the document's rule candidate (once more when the answer is not one);
    writes nothing. An extraction stored before is returned as it is."""

    name: ClassVar[str] = "pipeline.extract_rules"
    input_type: ClassVar[type[ExtractionRequest]] = ExtractionRequest
    output_type: ClassVar[type[ExtractionAnswer]] = ExtractionAnswer
    start_to_close: ClassVar[timedelta] = timedelta(minutes=10)
    heartbeat_timeout: ClassVar[timedelta | None] = timedelta(minutes=2)
    retry_policy: ClassVar[RetryPolicy] = EXTRACT_RETRIES

    def __init__(
        self,
        reader: RulebookReader,
        stage: RuleExtractionStage | None,
        units: UnitOfWorkFactory,
        *,
        enabled: bool,
    ) -> None:
        if enabled and stage is None:
            raise ValueError("an enabled extraction activity needs its stage")
        self._reader = reader
        self._stage = stage
        self._units = units
        self._enabled = enabled

    async def run(self, input: ExtractionRequest) -> ExtractionAnswer:
        if not self._enabled or self._stage is None:
            return ExtractionAnswer(request=input, skipped=True)
        stage = self._stage
        try:
            return await on_thread(self, lambda: self._extract(input, stage))
        except ModelBudgetExhaustedError as exc:
            raise ApplicationError(
                str(exc), exc.retry_after_seconds, type=BUDGET_ERROR, non_retryable=True
            ) from exc

    def _extract(self, input: ExtractionRequest, stage: RuleExtractionStage) -> ExtractionAnswer:
        document_id = DocumentId(input.document_id)
        with self._units() as unit:
            stored = unit.extractions.get(document_id, stage.prompt_ref)
        if stored is not None:
            return answer_of(input, stored)
        # No transaction is open from here on: the rulebook and the gateway are HTTP calls.
        document = self._reader.parsed_document(document_id)
        if document.doc_type is not input.doc_type:
            document = _as_type(document, input.doc_type)
        ctx = ExtractionContext(
            regulator=input.regulator,
            prompt_version=stage.prompt_ref,
            model="llm-gateway",
            ontology_version=ONTOLOGY_VERSION,
        )
        got = stage.run(document, ctx)
        log.info(
            "pipeline.rules_extracted",
            document_id=str(document_id),
            parsed=got.fields is not None,
            attempts=got.attempts,
            issues=list(got.report.codes()),
        )
        return ExtractionAnswer(
            request=input,
            prompt_version=stage.prompt_ref,
            outcome=(
                ExtractionOutcome.UNPARSEABLE if got.fields is None else ExtractionOutcome.EXTRACTED
            ).value,
            model=got.model,
            attempts=got.attempts,
            fields=None if got.fields is None else got.fields.to_mapping(),
            issues=[_issue_out(issue) for issue in got.report.issues],
            citation_count=got.report.citation_count,
            confidence=got.report.confidence,
            needs_review=got.needs_review,
            answer=got.answer[:MAX_ANSWER_CHARS],
            ontology_version=ONTOLOGY_VERSION,
        )


class StoreExtraction(ActivityBase[ExtractionAnswer, ExtractionStored]):
    """Store the extraction with its rule.candidate.created and the document's ``extracted``
    status, in one transaction; an extraction stored before writes nothing."""

    name: ClassVar[str] = "pipeline.store_extraction"
    input_type: ClassVar[type[ExtractionAnswer]] = ExtractionAnswer
    output_type: ClassVar[type[ExtractionStored]] = ExtractionStored
    start_to_close: ClassVar[timedelta] = timedelta(minutes=2)
    retry_policy: ClassVar[RetryPolicy] = STORE_RETRIES

    def __init__(
        self, units: UnitOfWorkFactory, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._units = units
        self._clock = clock

    async def run(self, input: ExtractionAnswer) -> ExtractionStored:
        request = input.request
        if input.skipped:
            return ExtractionStored(document_id=request.document_id, skipped=True)
        return await on_thread(self, lambda: self.store(input))

    def store(self, input: ExtractionAnswer) -> ExtractionStored:
        request = input.request
        extraction = extraction_of(input, at=self._clock())
        created = False
        if not input.stored:
            with self._units() as unit:
                if unit.extractions.add(extraction):
                    created = True
                    unit.events.publish(extraction.event(SourceId(request.source_id)))
                    record = unit.documents.get(extraction.document_id)
                    if record is not None and record.status is DocumentStatus.CLASSIFIED:
                        unit.documents.set_status(extraction.document_id, DocumentStatus.EXTRACTED)
        log.info(
            "pipeline.extraction_stored",
            document_id=str(extraction.document_id),
            candidate_id=str(extraction.candidate_id),
            outcome=extraction.outcome.value,
            created=created,
        )
        return ExtractionStored(
            document_id=request.document_id,
            candidate_id=extraction.candidate_id.value,
            outcome=extraction.outcome.value,
            needs_review=extraction.needs_review,
            created=created,
        )


def extraction_of(answer: ExtractionAnswer, *, at: datetime) -> RuleExtraction:
    """The answer as the extraction the store keeps."""
    request = answer.request
    document_id = DocumentId(request.document_id)
    return RuleExtraction(
        document_id=document_id,
        prompt_version=answer.prompt_version,
        candidate_id=candidate_id_for(document_id, answer.prompt_version),
        outcome=ExtractionOutcome(answer.outcome),
        model=answer.model,
        attempts=answer.attempts,
        source_key=request.source_key,
        doc_type=request.doc_type,
        regulator=request.regulator,
        issues=tuple(Issue(i.code, i.detail, i.clause_ref) for i in answer.issues),
        citation_count=answer.citation_count,
        confidence=answer.confidence,
        needs_review=answer.needs_review,
        answer=answer.answer,
        ontology_version=answer.ontology_version,
        extracted_at=at,
        fields=answer.fields,
    )


def answer_of(request: ExtractionRequest, stored: RuleExtraction) -> ExtractionAnswer:
    """An extraction stored before, as the answer the workflow passes on (``stored``)."""
    return ExtractionAnswer(
        request=request,
        prompt_version=stored.prompt_version,
        outcome=stored.outcome.value,
        model=stored.model,
        attempts=stored.attempts,
        fields=None if stored.fields is None else _plain(stored.fields),
        issues=[_issue_out(issue) for issue in stored.issues],
        citation_count=stored.citation_count,
        confidence=stored.confidence,
        needs_review=stored.needs_review,
        answer=stored.answer,
        ontology_version=stored.ontology_version,
        stored=True,
    )


def _plain(value: Any) -> Any:
    if hasattr(value, "items"):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_plain(item) for item in value]
    return value


def _issue_out(issue: Issue) -> IssueOut:
    return IssueOut(code=issue.code, detail=issue.detail, clause_ref=issue.clause_ref)


def _as_type(document: ParsedDocument, doc_type: DocumentType) -> ParsedDocument:
    """The rulebook keeps the type of a document's first registration; the extraction reads it
    as the type it was classified as (a triage's, say)."""
    return dataclasses.replace(document, doc_type=doc_type)
