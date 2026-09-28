"""The relation stage: one gateway call per document that asks which of the grammar's targets
the document acts on, then the validators.

No call is made when the grammar found nothing to act on. The answer is read by
``parse_relations`` (structure) and ``validate_relations`` (content); an answer that is not JSON
at all is kept verbatim as a run issue, and so is every item that could not become a relation.
"""

from dataclasses import dataclass
from typing import ClassVar

from domain_kernel.documents import ParsedDocument
from domain_kernel.llm import CompletionRequest
from domain_kernel.protocols import LLMProvider
from pipeline.application.detector import ChangeKind
from pipeline.application.extractor import render_document
from pipeline.application.relation_validators import RelationContext, validate_relations
from pipeline.application.stages import PipelineStage, StageInputError
from pipeline.domain.grammar import ExtractedMention
from pipeline.domain.issues import Issue
from pipeline.domain.knowledge import RuleKey, StagedRelation
from pipeline.domain.prompt import PromptText
from pipeline.domain.relations import (
    RelationParseError,
    parse_relations,
    relation_schema,
    render_mentions,
)

FEATURE = "extraction"
RAW_KEPT = 2_000


@dataclass(frozen=True, slots=True)
class RelationInput:
    document: ParsedDocument
    mentions: tuple[ExtractedMention, ...]
    rules: tuple[RuleKey, ...] = ()
    change_kind: ChangeKind = ChangeKind.NONE
    own_ref: str = ""
    regulator: str = ""


@dataclass(frozen=True, slots=True)
class RelationBatch:
    """The stage's output: the outcome of the run, the model that answered, the candidates and
    the run-level issues."""

    outcome: str
    model: str = ""
    candidates: tuple[StagedRelation, ...] = ()
    run_issues: tuple[Issue, ...] = ()


class LlmRelationExtractor:
    def __init__(self, provider: LLMProvider, prompt: PromptText) -> None:
        self._provider = provider
        self._prompt = prompt

    @property
    def prompt_ref(self) -> str:
        return self._prompt.ref

    def propose(
        self, input: RelationInput, targets: str, schema: dict[str, object]
    ) -> tuple[str, str]:
        """The model's answer and the model that gave it."""
        rules = "\n".join(f"{rule.rule_key}: {rule.title}" for rule in input.rules) or "(none)"
        user = "\n".join(
            [
                render_document(input.document),
                "",
                f"The document's own number: {input.own_ref or '(not given)'}",
                f"The change detector reads it as: {input.change_kind.value}",
                "",
                "Targets:",
                targets,
                "",
                "Rule keys:",
                rules,
            ]
        )
        response = self._provider.complete(
            CompletionRequest(
                feature=FEATURE,
                prompt_version=self._prompt.ref,
                system=self._prompt.system,
                user=user,
                json_schema=schema,
                max_tokens=2048,
                metadata={
                    "document_id": str(input.document.document_id),
                    "regulator": input.regulator,
                    "stage": "relations",
                },
            )
        )
        return response.text, response.model


class RelationStage(PipelineStage[RelationInput, RelationBatch]):
    name: ClassVar[str] = "relations"
    version: ClassVar[str] = "extraction.rule_relations@1"

    def __init__(self, extractor: LlmRelationExtractor) -> None:
        self._extractor = extractor

    def validate(self, input: RelationInput) -> None:
        if not isinstance(input.document, ParsedDocument):
            raise StageInputError("the relation stage reads a ParsedDocument")

    def process(self, input: RelationInput) -> RelationBatch:
        listing, targets, truncated = render_mentions(input.mentions)
        if not targets:
            return RelationBatch(outcome="no_targets")
        clause_refs = [clause.clause_ref for clause in input.document.clauses]
        rule_keys = [rule.rule_key for rule in input.rules]
        schema = relation_schema(list(targets), clause_refs, rule_keys)
        text, model = self._extractor.propose(input, listing, schema)
        run_issues: list[Issue] = []
        if truncated:
            run_issues.append(Issue("mentions_truncated", f"only {len(targets)} targets offered"))
        try:
            proposals, unusable = parse_relations(
                text, mention_ids=list(targets), clause_refs=clause_refs, rule_keys=rule_keys
            )
        except RelationParseError as exc:
            run_issues.append(Issue("relation_output_unparseable", f"{exc}: {text[:RAW_KEPT]}"))
            return RelationBatch("unparseable", model, (), tuple(run_issues))
        run_issues.extend(
            Issue("relation_item_unusable", f"{item.reason}: {item.raw}") for item in unusable
        )
        candidates, issues = validate_relations(
            proposals, RelationContext(input.document, targets, input.change_kind)
        )
        run_issues.extend(issues)
        needs_review = bool(run_issues) or any(c.needs_review for c in candidates)
        return RelationBatch(
            "needs_review" if needs_review else "ok", model, candidates, tuple(run_issues)
        )

    def needs_review(self, output: RelationBatch, issues: tuple[Issue, ...]) -> bool:
        return output.outcome in {"needs_review", "unparseable", "failed"}
