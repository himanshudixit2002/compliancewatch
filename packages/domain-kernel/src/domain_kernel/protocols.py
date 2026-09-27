"""Interfaces the domain declares and the infrastructure implements.

Structural (no ``runtime_checkable``): a class satisfies a protocol by having the methods.
"""

from collections.abc import Iterable, Sequence
from datetime import date, datetime
from typing import Protocol

from domain_kernel.decisions import ApplicabilityDecision
from domain_kernel.documents import (
    DiscoveredDocument,
    DocumentRef,
    ExtractionContext,
    ParsedDocument,
    RawDocument,
    RuleCandidate,
)
from domain_kernel.ids import BusinessId, DecisionId, RuleVersionId
from domain_kernel.llm import CompletionRequest, CompletionResponse
from domain_kernel.notifications import DeliveryReceipt, RenderedMessage
from domain_kernel.predicates import Predicate, PredicateResult
from domain_kernel.profiles import ProfileSnapshot
from domain_kernel.rules import RuleVersionSnapshot
from domain_kernel.vectors import ClauseFilter, EmbeddedClause, ScoredClause, Vector


class SourceAdapter(Protocol):
    """One regulator source: lists what changed and fetches documents."""

    def list_documents(self, since: datetime) -> Iterable[DiscoveredDocument]: ...

    def fetch(self, ref: DocumentRef) -> RawDocument: ...


class DocumentParser(Protocol):
    """Turns fetched bytes into clauses with stable references."""

    def supports(self, doc: RawDocument) -> bool: ...

    def parse(self, doc: RawDocument) -> ParsedDocument: ...


class RuleExtractor(Protocol):
    def extract(self, doc: ParsedDocument, ctx: ExtractionContext) -> RuleCandidate: ...


class PredicateEvaluator(Protocol):
    """Decides one predicate against a profile; deterministic or model-backed."""

    def evaluate(self, predicate: Predicate, profile: ProfileSnapshot) -> PredicateResult: ...


class NotificationChannel(Protocol):
    def send(self, message: RenderedMessage) -> DeliveryReceipt: ...


class LLMProvider(Protocol):
    def complete(self, req: CompletionRequest) -> CompletionResponse: ...


class VectorStore(Protocol):
    def upsert(self, items: Sequence[EmbeddedClause]) -> None: ...

    def search(self, query: Vector, filters: ClauseFilter, k: int) -> list[ScoredClause]: ...


class RuleReader(Protocol):
    """Read access to published rule versions."""

    def published_as_of(self, as_of: date) -> Sequence[RuleVersionSnapshot]: ...

    def get(self, rule_version_id: RuleVersionId) -> RuleVersionSnapshot | None: ...


class DecisionRepository(Protocol):
    def add(self, decision: ApplicabilityDecision) -> None: ...

    def get(self, decision_id: DecisionId) -> ApplicabilityDecision | None: ...

    def latest(
        self, business_id: BusinessId, rule_version_id: RuleVersionId
    ) -> ApplicabilityDecision | None: ...


class WorkflowHandle(Protocol):
    """Identifies a running workflow without naming the orchestrator."""

    @property
    def workflow_id(self) -> str: ...

    @property
    def run_id(self) -> str: ...
