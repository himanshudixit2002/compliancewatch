from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime

from domain_kernel.channels import Channel
from domain_kernel.confidence import CERTAIN
from domain_kernel.decisions import ApplicabilityDecision
from domain_kernel.dedupe import DedupeKey
from domain_kernel.documents import (
    Clause,
    DiscoveredDocument,
    DocumentRef,
    DocumentType,
    ExtractionContext,
    ParsedDocument,
    RawDocument,
    RuleCandidate,
)
from domain_kernel.ids import (
    BusinessId,
    CandidateId,
    ClauseId,
    DecisionId,
    DocumentId,
    RuleId,
    RuleVersionId,
    SourceId,
    TenantId,
)
from domain_kernel.llm import CompletionRequest, CompletionResponse
from domain_kernel.notifications import DeliveryReceipt, DeliveryStatus, RenderedMessage
from domain_kernel.ontology import Ontology
from domain_kernel.operators import Operator
from domain_kernel.periods import EffectivePeriod
from domain_kernel.predicates import (
    Applicability,
    Predicate,
    PredicateResult,
    evaluate_predicate,
)
from domain_kernel.profiles import ProfileSnapshot
from domain_kernel.protocols import (
    DecisionRepository,
    DocumentParser,
    LLMProvider,
    NotificationChannel,
    PredicateEvaluator,
    RuleExtractor,
    RuleReader,
    SourceAdapter,
    VectorStore,
    WorkflowHandle,
)
from domain_kernel.rules import ObligationTemplate, RuleVersionSnapshot
from domain_kernel.vectors import ClauseFilter, EmbeddedClause, ScoredClause, Vector

_NOW = datetime(2026, 9, 27, tzinfo=UTC)
_REF = DocumentRef(SourceId.new(), "https://cbic.gov.in/n/1")


class FakeSource:
    def list_documents(self, since: datetime) -> Iterable[DiscoveredDocument]:
        return [DiscoveredDocument(_REF, "Notification 1", since.date())]

    def fetch(self, ref: DocumentRef) -> RawDocument:
        return RawDocument.from_bytes(ref, b"%PDF", "application/pdf", _NOW)


class FakeParser:
    def supports(self, doc: RawDocument) -> bool:
        return doc.media_type == "application/pdf"

    def parse(self, doc: RawDocument) -> ParsedDocument:
        return ParsedDocument(
            DocumentId.new(), DocumentType.NOTIFICATION, "N1", (Clause("1", "Shall file."),)
        )


class FakeExtractor:
    def extract(self, doc: ParsedDocument, ctx: ExtractionContext) -> RuleCandidate:
        return RuleCandidate(
            CandidateId.new(),
            doc.document_id,
            {"title": doc.title},
            ctx.model,
            ctx.prompt_version,
            CERTAIN,
        )


class FakeEvaluator:
    def __init__(self, ontology: Ontology) -> None:
        self.ontology = ontology

    def evaluate(self, predicate: Predicate, profile: ProfileSnapshot) -> PredicateResult:
        return evaluate_predicate(predicate, profile.attributes, self.ontology)


class FakeChannel:
    def send(self, message: RenderedMessage) -> DeliveryReceipt:
        return DeliveryReceipt(DeliveryStatus.SENT, _NOW, f"{message.channel.value}-1")


class FakeProvider:
    def complete(self, req: CompletionRequest) -> CompletionResponse:
        return CompletionResponse("{}", req.model or "fake", len(req.user), 2)


class FakeVectorStore:
    def __init__(self) -> None:
        self.items: list[EmbeddedClause] = []

    def upsert(self, items: Sequence[EmbeddedClause]) -> None:
        self.items.extend(items)

    def search(self, query: Vector, filters: ClauseFilter, k: int) -> list[ScoredClause]:
        return [ScoredClause(item.clause_id, 1.0) for item in self.items][:k]


class FakeRuleReader:
    def __init__(self, snapshot: RuleVersionSnapshot) -> None:
        self.snapshot = snapshot

    def published_as_of(self, as_of: date) -> Sequence[RuleVersionSnapshot]:
        return [self.snapshot] if self.snapshot.is_effective_on(as_of) else []

    def get(self, rule_version_id: RuleVersionId) -> RuleVersionSnapshot | None:
        return self.snapshot if self.snapshot.rule_version_id == rule_version_id else None


class FakeDecisions:
    def __init__(self) -> None:
        self.rows: dict[DecisionId, ApplicabilityDecision] = {}

    def add(self, decision: ApplicabilityDecision) -> None:
        self.rows[decision.decision_id] = decision

    def get(self, decision_id: DecisionId) -> ApplicabilityDecision | None:
        return self.rows.get(decision_id)

    def latest(
        self, business_id: BusinessId, rule_version_id: RuleVersionId
    ) -> ApplicabilityDecision | None:
        matches = [
            row
            for row in self.rows.values()
            if row.business_id == business_id and row.rule_version_id == rule_version_id
        ]
        return max(matches, key=lambda row: row.decided_at, default=None)


class FakeHandle:
    @property
    def workflow_id(self) -> str:
        return "fan-out-1"

    @property
    def run_id(self) -> str:
        return "run-1"


def test_pipeline_protocols_are_satisfied_structurally() -> None:
    source: SourceAdapter = FakeSource()
    parser: DocumentParser = FakeParser()
    extractor: RuleExtractor = FakeExtractor()
    discovered = list(source.list_documents(_NOW))
    raw = source.fetch(discovered[0].ref)
    assert parser.supports(raw)
    parsed = parser.parse(raw)
    candidate = extractor.extract(parsed, ExtractionContext("CBIC", "v3", "fake", "0.1.0"))
    assert candidate.document_id == parsed.document_id
    assert candidate.payload["title"] == "N1"


def test_evaluator_delegates_to_evaluate_predicate(ontology: Ontology) -> None:
    evaluator: PredicateEvaluator = FakeEvaluator(ontology)
    profile = ProfileSnapshot(BusinessId.new(), TenantId.new(), 1, {"registration_type": "regular"})
    result = evaluator.evaluate(Predicate("registration_type", Operator.EQ, "regular"), profile)
    assert result.outcome is Applicability.APPLIES
    assert result.confidence == CERTAIN


def test_channel_provider_and_vector_store() -> None:
    channel: NotificationChannel = FakeChannel()
    key = DedupeKey.for_notification(RuleVersionId.new(), BusinessId.new(), Channel.WHATSAPP)
    receipt = channel.send(RenderedMessage(Channel.WHATSAPP, "+91", "Hi", key))
    assert receipt.provider_message_id == "whatsapp-1"
    provider: LLMProvider = FakeProvider()
    response = provider.complete(CompletionRequest("extract", "v3", "sys", "user"))
    assert (response.model, response.input_tokens) == ("fake", 4)
    store: VectorStore = FakeVectorStore()
    clause = EmbeddedClause(
        ClauseId.new(), DocumentId.new(), (0.5,), "embed", "CBIC", DocumentType.CIRCULAR
    )
    store.upsert([clause])
    assert store.search((0.5,), ClauseFilter(), 5) == [ScoredClause(clause.clause_id, 1.0)]


def test_rule_reader_and_decision_repository() -> None:
    snapshot = RuleVersionSnapshot(
        RuleId.new(),
        RuleVersionId.new(),
        1,
        "CBIC",
        "Rule",
        Predicate("registration_type", Operator.EQ, "regular"),
        EffectivePeriod(date(2026, 1, 1)),
        ObligationTemplate("Do it"),
    )
    reader: RuleReader = FakeRuleReader(snapshot)
    assert reader.published_as_of(date(2026, 6, 1)) == [snapshot]
    assert reader.published_as_of(date(2025, 6, 1)) == []
    assert reader.get(snapshot.rule_version_id) is snapshot
    assert reader.get(RuleVersionId.new()) is None
    repository: DecisionRepository = FakeDecisions()
    business = BusinessId.new()
    decision = ApplicabilityDecision(
        DecisionId.new(),
        TenantId.new(),
        business,
        snapshot.rule_version_id,
        Applicability.APPLIES,
        CERTAIN,
        (),
        1,
        _NOW,
    )
    repository.add(decision)
    assert repository.get(decision.decision_id) is decision
    assert repository.latest(business, snapshot.rule_version_id) is decision
    assert repository.latest(BusinessId.new(), snapshot.rule_version_id) is None


def test_workflow_handle() -> None:
    handle: WorkflowHandle = FakeHandle()
    assert (handle.workflow_id, handle.run_id) == ("fan-out-1", "run-1")
