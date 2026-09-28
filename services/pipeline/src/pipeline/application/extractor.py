"""The rule extractor: one gateway call per document, then the validators.

The extractor never talks to a model directly. It renders the document as numbered clauses,
sends the registered prompt and the candidate schema through an ``LLMProvider`` (the gateway
client in production, a scripted provider in tests), reads the answer as ``CandidateFields``
and runs the validators. The result is a kernel ``RuleCandidate`` whose payload holds the
fields, the validation report and the prompt reference, and the report itself for the caller.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from domain_kernel.confidence import Confidence
from domain_kernel.documents import ExtractionContext, ParsedDocument, RuleCandidate
from domain_kernel.ids import CandidateId
from domain_kernel.llm import CompletionRequest
from domain_kernel.ontology import Ontology
from domain_kernel.protocols import LLMProvider
from pipeline.application.validators import Issue, ValidationReport, validate
from pipeline.domain.candidate import (
    CANDIDATE_SCHEMA,
    CandidateFields,
    CandidateParseError,
    parse_candidate,
)
from pipeline.domain.prompt import PromptText

FEATURE = "extraction"
MAX_CLAUSE_CHARS = 60_000


@dataclass(frozen=True, slots=True)
class ExtractionOutcome:
    candidate: RuleCandidate
    fields: CandidateFields | None
    report: ValidationReport
    model: str
    raw_text: str

    @property
    def needs_review(self) -> bool:
        return self.fields is None or self.report.needs_review


class LlmRuleExtractor:
    def __init__(self, provider: LLMProvider, prompt: PromptText, ontology: Ontology) -> None:
        self._provider = provider
        self._prompt = prompt
        self._ontology = ontology

    def extract(self, doc: ParsedDocument, ctx: ExtractionContext) -> RuleCandidate:
        return self.run(doc, ctx).candidate

    def run(self, doc: ParsedDocument, ctx: ExtractionContext) -> ExtractionOutcome:
        request = CompletionRequest(
            feature=FEATURE,
            prompt_version=self._prompt.ref,
            system=self._prompt.system,
            user=render_document(doc),
            json_schema=CANDIDATE_SCHEMA,
            max_tokens=4096,
            metadata={"document_id": str(doc.document_id), "regulator": ctx.regulator},
        )
        response = self._provider.complete(request)
        return self.assess(doc, ctx, response.text, response.model)

    def assess(
        self, doc: ParsedDocument, ctx: ExtractionContext, text: str, model: str
    ) -> ExtractionOutcome:
        """Read ``text`` as the model's answer for ``doc`` and validate it."""
        try:
            fields: CandidateFields | None = parse_candidate(text)
        except CandidateParseError as exc:
            fields = None
            report = ValidationReport((Issue("output_unparseable", str(exc)),), 0, 0.0)
        else:
            assert fields is not None
            report = validate(fields, doc, self._ontology)
        payload: dict[str, object] = {
            "fields": None if fields is None else fields.to_mapping(),
            "validation": {
                "issues": [
                    {"code": i.code, "detail": i.detail, "clause_ref": i.clause_ref}
                    for i in report.issues
                ],
                "citation_count": report.citation_count,
                "needs_review": fields is None or report.needs_review,
            },
            "prompt": self._prompt.ref,
            "ontology_version": ctx.ontology_version,
        }
        candidate = RuleCandidate(
            candidate_id=CandidateId.new(),
            document_id=doc.document_id,
            payload=payload,
            model=model,
            prompt_version=self._prompt.ref,
            confidence=Confidence(report.confidence),
        )
        return ExtractionOutcome(candidate, fields, report, model, text)


def render_document(doc: ParsedDocument, *, limit: int = MAX_CLAUSE_CHARS) -> str:
    """The document as the model sees it: the title, then ``[ref] text`` per clause."""
    lines = [f"Title: {doc.title}", f"Document type: {doc.doc_type.value}", ""]
    used = 0
    for clause in doc.clauses:
        line = f"[{clause.clause_ref}] {clause.text}"
        if used + len(line) > limit:
            lines.append("[truncated: the document continues]")
            break
        lines.append(line)
        used += len(line)
    return "\n".join(lines)


def issues_summary(reports: Sequence[ValidationReport]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for report in reports:
        for code in report.codes():
            counts[code] = counts.get(code, 0) + 1
    return counts
