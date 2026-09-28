"""Activities that hand the pipeline's output to the rulebook, which owns regulator records.

``RegisterDocument`` stores a parsed document and its clauses. It parses the fetched bytes again
rather than carrying clause text through the workflow history, and checks that the rulebook
derived the same clause ids the kernel gives here. ``ExtractMentions`` runs the mention grammar
over the stored document and hands the mentions to alignment; ``ProposeRelations`` asks the
model which of them the document acts on, and ``SubmitRelations`` stages the answer for review.
All four sit behind ``CW_PIPELINE_KNOWLEDGE_ENABLED``: disabled, they answer ``skipped`` without
a call.
"""

import dataclasses
from datetime import date, timedelta
from typing import ClassVar
from uuid import UUID

from pydantic import Field
from temporalio.common import RetryPolicy

from domain_kernel.documents import clause_id_for
from domain_kernel.ids import DocumentId, SourceId
from domain_kernel.knowledge import EntityType, RelationKind
from domain_kernel.protocols import DocumentParser
from pipeline.application.activities import Frozen, ParseRequest, parse_fetched
from pipeline.application.detector import detect
from pipeline.application.mentions import MentionInput, MentionStage
from pipeline.application.relations import RelationInput, RelationStage
from pipeline.domain.errors import KnowledgeContractError
from pipeline.domain.grammar import ExtractedMention, mentions_for
from pipeline.domain.issues import Issue
from pipeline.domain.knowledge import (
    DocumentRecord,
    MentionSubmission,
    RelationSubmission,
    StagedRelation,
)
from pipeline.domain.ports import KnowledgeSink, RulebookReader
from py_common.temporal import ActivityBase


class RegisterRequest(Frozen):
    parse: ParseRequest
    regulator: str = Field(min_length=1)


class Registered(Frozen):
    document_id: UUID
    clause_count: int = 0
    created: bool = False
    skipped: bool = False


class RegisterDocument(ActivityBase[RegisterRequest, Registered]):
    """Store the parsed document in the rulebook; idempotent, so a retry is harmless."""

    name: ClassVar[str] = "pipeline.register_document"
    input_type: ClassVar[type[RegisterRequest]] = RegisterRequest
    output_type: ClassVar[type[Registered]] = Registered
    start_to_close: ClassVar[timedelta] = timedelta(minutes=2)
    retry_policy: ClassVar[RetryPolicy] = RetryPolicy(
        initial_interval=timedelta(seconds=5),
        backoff_coefficient=2.0,
        maximum_interval=timedelta(minutes=2),
        maximum_attempts=5,
        non_retryable_error_types=[
            "RulebookConflictError",
            "RulebookRejectedError",
            "KnowledgeContractError",
            "UnsupportedDocumentError",
        ],
    )

    def __init__(self, parser: DocumentParser, sink: KnowledgeSink, *, enabled: bool) -> None:
        self._parser = parser
        self._sink = sink
        self._enabled = enabled

    async def run(self, input: RegisterRequest) -> Registered:
        if not self._enabled:
            return Registered(document_id=input.parse.document_id, skipped=True)
        request = input.parse
        fetched = request.fetched
        parsed = parse_fetched(self._parser, fetched)
        parsed = dataclasses.replace(
            parsed,
            title=request.title or parsed.title,
            published_at=request.published_at or parsed.published_at,
        )
        registered = self._sink.register_document(
            DocumentRecord(
                document=parsed,
                source_id=SourceId(fetched.source_id),
                sha256=fetched.sha256,
                regulator=input.regulator,
                url=fetched.url,
                media_type=fetched.media_type,
                fetched_at=fetched.fetched_at,
                external_ref=fetched.external_ref,
            )
        )
        expected = {
            clause.clause_ref: clause_id_for(parsed.document_id, clause.clause_ref)
            for clause in parsed.clauses
        }
        if registered.document_id != parsed.document_id or dict(registered.clause_ids) != expected:
            raise KnowledgeContractError(
                f"the rulebook's ids for document {parsed.document_id} differ from the kernel's"
            )
        return Registered(
            document_id=parsed.document_id.value,
            clause_count=len(parsed.clauses),
            created=registered.created,
        )


class MentionsRequest(Frozen):
    document_id: UUID
    own_ref: str = ""


class MentionsReport(Frozen):
    found: int = 0
    aligned: int = 0
    queued: int = 0
    unchanged: int = 0
    skipped: bool = False


class ExtractMentions(ActivityBase[MentionsRequest, MentionsReport]):
    """Run the mention grammar over a stored document and hand the mentions to alignment."""

    name: ClassVar[str] = "pipeline.extract_mentions"
    input_type: ClassVar[type[MentionsRequest]] = MentionsRequest
    output_type: ClassVar[type[MentionsReport]] = MentionsReport
    start_to_close: ClassVar[timedelta] = timedelta(minutes=2)
    retry_policy: ClassVar[RetryPolicy] = RegisterDocument.retry_policy

    def __init__(self, reader: RulebookReader, sink: KnowledgeSink, *, enabled: bool) -> None:
        self._reader = reader
        self._sink = sink
        self._enabled = enabled

    async def run(self, input: MentionsRequest) -> MentionsReport:
        if not self._enabled:
            return MentionsReport(skipped=True)
        document = self._reader.parsed_document(DocumentId(input.document_id))
        outcome = MentionStage().execute(MentionInput(document, own_ref=input.own_ref))
        report = self._sink.submit_mentions(
            MentionSubmission(document.document_id, MentionStage.version, outcome.output)
        )
        return MentionsReport(
            found=len(outcome.output),
            aligned=report.aligned,
            queued=report.queued,
            unchanged=report.unchanged,
        )


class RelationsRequest(Frozen):
    document_id: UUID
    own_ref: str = ""
    regulator: str = ""


class MentionOut(Frozen):
    clause_ref: str
    entity_type: str
    text: str
    span_start: int
    span_end: int
    proposed_name: str
    self_ref: bool = False


class IssueOut(Frozen):
    code: str
    detail: str
    clause_ref: str | None = None


class StagedOut(Frozen):
    relation: str
    target: MentionOut
    evidence_clause_ref: str
    evidence_quote: str
    quote_score: float
    confidence: float
    needs_review: bool
    rule_key: str | None = None
    period_label: str | None = None
    new_due_on: date | None = None
    issues: list[IssueOut] = Field(default_factory=list)


class RelationBatchOut(Frozen):
    """The relation stage's output as it crosses the workflow: submitted by a separate activity,
    so a failed write is retried without asking the model again."""

    document_id: UUID
    extractor: str
    outcome: str
    model: str = ""
    candidates: list[StagedOut] = Field(default_factory=list)
    run_issues: list[IssueOut] = Field(default_factory=list)
    skipped: bool = False


class ProposeRelations(ActivityBase[RelationsRequest, RelationBatchOut]):
    """Ask the model, through the gateway, which targets the document acts on, and validate the
    answer. Writes nothing."""

    name: ClassVar[str] = "pipeline.propose_relations"
    input_type: ClassVar[type[RelationsRequest]] = RelationsRequest
    output_type: ClassVar[type[RelationBatchOut]] = RelationBatchOut
    start_to_close: ClassVar[timedelta] = timedelta(minutes=5)
    retry_policy: ClassVar[RetryPolicy] = RetryPolicy(
        initial_interval=timedelta(seconds=10),
        backoff_coefficient=2.0,
        maximum_interval=timedelta(minutes=2),
        maximum_attempts=3,
        non_retryable_error_types=["RulebookRejectedError", "KnowledgeContractError"],
    )

    def __init__(
        self, reader: RulebookReader, stage: RelationStage | None, *, enabled: bool
    ) -> None:
        if enabled and stage is None:
            raise ValueError("an enabled relation activity needs its stage")
        self._reader = reader
        self._stage = stage
        self._enabled = enabled

    async def run(self, input: RelationsRequest) -> RelationBatchOut:
        if not self._enabled or self._stage is None:
            return RelationBatchOut(
                document_id=input.document_id,
                extractor=RelationStage.version,
                outcome="ok",
                skipped=True,
            )
        document = self._reader.parsed_document(DocumentId(input.document_id))
        detection = detect(document, own_ref=input.own_ref)
        batch = self._stage.execute(
            RelationInput(
                document=document,
                mentions=mentions_for(document, own_ref=input.own_ref),
                rules=self._reader.known_rules(),
                change_kind=detection.change_kind,
                own_ref=input.own_ref,
                regulator=input.regulator,
            )
        ).output
        return RelationBatchOut(
            document_id=input.document_id,
            extractor=RelationStage.version,
            outcome=batch.outcome,
            model=batch.model,
            candidates=[_staged_out(c) for c in batch.candidates],
            run_issues=[_issue_out(i) for i in batch.run_issues],
        )


class RelationsReport(Frozen):
    outcome: str
    created: int = 0
    unchanged: int = 0
    skipped: bool = False


class SubmitRelations(ActivityBase[RelationBatchOut, RelationsReport]):
    """Stage the proposed relations in the rulebook as candidates for review."""

    name: ClassVar[str] = "pipeline.submit_relations"
    input_type: ClassVar[type[RelationBatchOut]] = RelationBatchOut
    output_type: ClassVar[type[RelationsReport]] = RelationsReport
    start_to_close: ClassVar[timedelta] = timedelta(minutes=2)
    retry_policy: ClassVar[RetryPolicy] = RegisterDocument.retry_policy

    def __init__(self, sink: KnowledgeSink, *, enabled: bool) -> None:
        self._sink = sink
        self._enabled = enabled

    async def run(self, input: RelationBatchOut) -> RelationsReport:
        if not self._enabled or input.skipped:
            return RelationsReport(outcome=input.outcome, skipped=True)
        report = self._sink.submit_relations(
            RelationSubmission(
                document_id=DocumentId(input.document_id),
                extractor=input.extractor,
                model=input.model,
                outcome=input.outcome,
                candidates=tuple(_staged(c) for c in input.candidates),
                run_issues=tuple(_issue(i) for i in input.run_issues),
            )
        )
        return RelationsReport(
            outcome=input.outcome, created=report.created, unchanged=report.unchanged
        )


def _issue_out(issue: Issue) -> IssueOut:
    return IssueOut(code=issue.code, detail=issue.detail, clause_ref=issue.clause_ref)


def _issue(issue: IssueOut) -> Issue:
    return Issue(issue.code, issue.detail, issue.clause_ref)


def _staged_out(staged: StagedRelation) -> StagedOut:
    target = staged.target
    return StagedOut(
        relation=staged.relation.value,
        target=MentionOut(
            clause_ref=target.clause_ref,
            entity_type=target.entity_type.value,
            text=target.text,
            span_start=target.span_start,
            span_end=target.span_end,
            proposed_name=target.proposed_name,
            self_ref=target.self_ref,
        ),
        evidence_clause_ref=staged.evidence_clause_ref,
        evidence_quote=staged.evidence_quote,
        quote_score=staged.quote_score,
        confidence=staged.confidence,
        needs_review=staged.needs_review,
        rule_key=staged.rule_key,
        period_label=staged.period_label,
        new_due_on=staged.new_due_on,
        issues=[_issue_out(i) for i in staged.issues],
    )


def _staged(out: StagedOut) -> StagedRelation:
    target = out.target
    return StagedRelation(
        relation=RelationKind(out.relation),
        target=ExtractedMention(
            clause_ref=target.clause_ref,
            entity_type=EntityType(target.entity_type),
            text=target.text,
            span_start=target.span_start,
            span_end=target.span_end,
            proposed_name=target.proposed_name,
            self_ref=target.self_ref,
        ),
        evidence_clause_ref=out.evidence_clause_ref,
        evidence_quote=out.evidence_quote,
        quote_score=out.quote_score,
        confidence=out.confidence,
        needs_review=out.needs_review,
        rule_key=out.rule_key,
        period_label=out.period_label,
        new_due_on=out.new_due_on,
        issues=tuple(_issue(i) for i in out.issues),
    )
