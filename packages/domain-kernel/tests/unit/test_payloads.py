import hashlib
from datetime import UTC, date, datetime
from types import MappingProxyType

import pytest

from domain_kernel.channels import Channel
from domain_kernel.confidence import CERTAIN, Confidence
from domain_kernel.decisions import ApplicabilityDecision
from domain_kernel.dedupe import DedupeKey
from domain_kernel.documents import (
    BBox,
    Clause,
    DiscoveredDocument,
    DocumentRef,
    DocumentType,
    ExtractionContext,
    ParsedDocument,
    RawDocument,
    RuleCandidate,
)
from domain_kernel.errors import InvariantViolationError
from domain_kernel.financial_year import FinancialYear
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
from domain_kernel.operators import Operator
from domain_kernel.periods import EffectivePeriod
from domain_kernel.predicates import Applicability, Predicate, PredicateResult
from domain_kernel.profiles import ProfileSnapshot
from domain_kernel.recurrence import Recurrence
from domain_kernel.rules import ObligationTemplate, RuleVersionSnapshot
from domain_kernel.vectors import ClauseFilter, EmbeddedClause, ScoredClause

_NOW = datetime(2026, 9, 27, 10, 0, tzinfo=UTC)
_NAIVE = datetime(2026, 9, 27, 10, 0)
_REF = DocumentRef(SourceId.new(), "https://cbic.gov.in/notification/1", "N-1")
_CLAUSE = Clause("1", "Every registered person shall file.", page=1, bbox=BBox(0, 0, 10, 10))
_PREDICATE = Predicate("registration_type", Operator.EQ, "regular")
_KEY = DedupeKey("31cfe6d670a19c81972252e3a1bc8b8338b36518d109de06ca27631f423ac845")


def _raises(message: str) -> pytest.RaisesExc[InvariantViolationError]:
    return pytest.raises(InvariantViolationError, match=message)


# ---- profiles --------------------------------------------------------------------------------


def test_profile_snapshot() -> None:
    snapshot = ProfileSnapshot(
        BusinessId.new(), TenantId.new(), 3, {"registration_type": "regular"}
    )
    assert snapshot.get("registration_type") == "regular"
    assert snapshot.get("missing") is None
    assert isinstance(snapshot.attributes, MappingProxyType)
    assert snapshot == ProfileSnapshot(
        snapshot.business_id, snapshot.tenant_id, 3, {"registration_type": "regular"}
    )
    assert hash(snapshot) == hash(
        ProfileSnapshot(snapshot.business_id, snapshot.tenant_id, 3, {"other": 1})
    )
    with pytest.raises(TypeError):
        snapshot.attributes["x"] = 1  # type: ignore[index]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"business_id": TenantId.new()}, "business_id must be BusinessId"),
        ({"tenant_id": "t"}, "tenant_id must be TenantId"),
        ({"version": 0}, "version must be at least 1"),
        ({"version": True}, "version must be an integer"),
        ({"attributes": [("a", 1)]}, "attributes must be a mapping"),
        ({"attributes": {1: "x"}}, "attributes keys must be strings"),
    ],
)
def test_profile_snapshot_invariants(kwargs: dict[str, object], message: str) -> None:
    fields: dict[str, object] = {
        "business_id": BusinessId.new(),
        "tenant_id": TenantId.new(),
        "version": 1,
        "attributes": {},
    }
    fields.update(kwargs)
    with _raises(message):
        ProfileSnapshot(**fields)  # type: ignore[arg-type]


# ---- documents -------------------------------------------------------------------------------


def test_document_ref_and_discovered_document() -> None:
    assert _REF.external_ref == "N-1"
    discovered = DiscoveredDocument(_REF, "Notification 1", date(2026, 9, 1))
    assert discovered.published_at == date(2026, 9, 1)
    assert DiscoveredDocument(_REF).title == ""
    with _raises("source_id must be SourceId"):
        DocumentRef("x", "https://a")  # type: ignore[arg-type]
    with _raises("url must not be blank"):
        DocumentRef(SourceId.new(), " ")
    with _raises("external_ref must be str"):
        DocumentRef(SourceId.new(), "https://a", None)  # type: ignore[arg-type]
    with _raises("ref must be DocumentRef"):
        DiscoveredDocument("ref")  # type: ignore[arg-type]
    with _raises("title must be str"):
        DiscoveredDocument(_REF, None)  # type: ignore[arg-type]
    with _raises("published_at must be a date"):
        DiscoveredDocument(_REF, "t", _NOW)


def test_raw_document_from_bytes_and_digest() -> None:
    raw = RawDocument.from_bytes(_REF, b"hello", "text/plain", _NOW)
    assert raw.sha256 == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    assert raw.sha256 == hashlib.sha256(b"hello").hexdigest()
    assert raw.fetched_at == _NOW
    assert RawDocument.from_bytes(_REF, b"x", "text/plain").fetched_at.tzinfo is not None
    assert raw == RawDocument(_REF, b"hello", "text/plain", raw.sha256, _NOW)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"ref": None}, "ref must be DocumentRef"),
        ({"content": b""}, "content must not be empty"),
        ({"content": "hello"}, "content must be bytes"),
        ({"media_type": ""}, "media_type must not be blank"),
        ({"sha256": "0" * 64}, "sha256 does not match content"),
        ({"sha256": None}, "sha256 must be str"),
        ({"fetched_at": _NAIVE}, "fetched_at must be timezone-aware"),
        ({"fetched_at": "now"}, "fetched_at must be a datetime"),
    ],
)
def test_raw_document_invariants(kwargs: dict[str, object], message: str) -> None:
    fields: dict[str, object] = {
        "ref": _REF,
        "content": b"hello",
        "media_type": "text/plain",
        "sha256": hashlib.sha256(b"hello").hexdigest(),
        "fetched_at": _NOW,
    }
    fields.update(kwargs)
    with _raises(message):
        RawDocument(**fields)  # type: ignore[arg-type]


def test_bbox_and_clause() -> None:
    assert BBox(0, 0, 0, 0) == BBox(0.0, 0.0, 0.0, 0.0)
    with _raises("x1 must be a finite number"):
        BBox(0, 0, float("inf"), 1)
    with _raises("y0 must be a finite number"):
        BBox(0, "0", 1, 1)  # type: ignore[arg-type]
    with _raises("corners must be ordered"):
        BBox(2, 0, 1, 1)
    with _raises("corners must be ordered"):
        BBox(0, 2, 1, 1)
    assert Clause("1", "text").page is None
    assert Clause("1", "text").bbox is None
    with _raises("clause_ref must not be blank"):
        Clause("", "text")
    with _raises("text must not be blank"):
        Clause("1", " \n")
    with _raises("page must be at least 1"):
        Clause("1", "text", page=0)
    with _raises("bbox must be BBox"):
        Clause("1", "text", bbox=(0, 0, 1, 1))  # type: ignore[arg-type]


def test_parsed_document() -> None:
    second = Clause("2", "Second clause.")
    parsed = ParsedDocument(
        DocumentId.new(), DocumentType.CIRCULAR, "Circular 1", (_CLAUSE, second), date(2026, 9, 1)
    )
    assert parsed.language == "en"
    assert parsed.find_clause("2") is second
    assert parsed.find_clause("3") is None
    assert ParsedDocument(DocumentId.new(), DocumentType.NOTIFICATION, "", (_CLAUSE,)).title == ""


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"document_id": ClauseId.new()}, "document_id must be DocumentId"),
        ({"doc_type": "circular"}, "doc_type must be DocumentType"),
        ({"title": None}, "title must be str"),
        ({"clauses": ()}, "clauses must not be empty"),
        ({"clauses": [_CLAUSE]}, "clauses must be tuple"),
        ({"clauses": (_CLAUSE, "x")}, r"clauses\[1\] must be Clause"),
        ({"clauses": (_CLAUSE, Clause("1", "again"))}, "duplicate clause_ref '1'"),
        ({"published_at": _NOW}, "published_at must be a date"),
        ({"language": " "}, "language must not be blank"),
    ],
)
def test_parsed_document_invariants(kwargs: dict[str, object], message: str) -> None:
    fields: dict[str, object] = {
        "document_id": DocumentId.new(),
        "doc_type": DocumentType.CIRCULAR,
        "title": "Circular 1",
        "clauses": (_CLAUSE,),
    }
    fields.update(kwargs)
    with _raises(message):
        ParsedDocument(**fields)  # type: ignore[arg-type]


def test_extraction_context() -> None:
    context = ExtractionContext("CBIC", "extract-v3", "model-x", "0.1.0")
    assert context.ontology_version == "0.1.0"
    for name in ("regulator", "prompt_version", "model", "ontology_version"):
        fields = {
            "regulator": "CBIC",
            "prompt_version": "v3",
            "model": "m",
            "ontology_version": "1",
        }
        fields[name] = ""
        with _raises(f"{name} must not be blank"):
            ExtractionContext(**fields)


def test_rule_candidate() -> None:
    candidate = RuleCandidate(
        CandidateId.new(), DocumentId.new(), {"title": "x"}, "model-x", "v3", Confidence(0.9)
    )
    assert isinstance(candidate.payload, MappingProxyType)
    assert candidate.payload["title"] == "x"
    assert hash(candidate) == hash(
        RuleCandidate(
            candidate.candidate_id, candidate.document_id, {}, "model-x", "v3", Confidence(0.9)
        )
    )
    with _raises("candidate_id must be CandidateId"):
        RuleCandidate(DocumentId.new(), DocumentId.new(), {}, "m", "v", CERTAIN)  # type: ignore[arg-type]
    with _raises("document_id must be DocumentId"):
        RuleCandidate(CandidateId.new(), "d", {}, "m", "v", CERTAIN)  # type: ignore[arg-type]
    with _raises("payload must be a mapping"):
        RuleCandidate(CandidateId.new(), DocumentId.new(), "{}", "m", "v", CERTAIN)  # type: ignore[arg-type]
    with _raises("model must not be blank"):
        RuleCandidate(CandidateId.new(), DocumentId.new(), {}, "", "v", CERTAIN)
    with _raises("prompt_version must not be blank"):
        RuleCandidate(CandidateId.new(), DocumentId.new(), {}, "m", "", CERTAIN)
    with _raises("confidence must be Confidence"):
        RuleCandidate(CandidateId.new(), DocumentId.new(), {}, "m", "v", 0.9)  # type: ignore[arg-type]


# ---- rules -----------------------------------------------------------------------------------


def test_obligation_template() -> None:
    template = ObligationTemplate("File GSTR-1", ("Log in", "Upload"), 10, "filing_receipt")
    assert template.due_in_days == 10
    assert ObligationTemplate("File").steps == ()
    assert ObligationTemplate("File", due_in_days=0).due_in_days == 0
    with _raises("title must not be blank"):
        ObligationTemplate("")
    with _raises("steps must be tuple"):
        ObligationTemplate("File", ["a"])  # type: ignore[arg-type]
    with _raises(r"steps\[1\] must not be blank"):
        ObligationTemplate("File", ("a", ""))
    with _raises("due_in_days must be at least 0"):
        ObligationTemplate("File", due_in_days=-1)
    with _raises("evidence_type must be str"):
        ObligationTemplate("File", evidence_type=None)  # type: ignore[arg-type]


def _snapshot(**overrides: object) -> RuleVersionSnapshot:
    fields: dict[str, object] = {
        "rule_id": RuleId.new(),
        "rule_version_id": RuleVersionId.new(),
        "version": 1,
        "regulator": "CBIC",
        "title": "E-invoicing threshold",
        "specification": _PREDICATE,
        "effective": EffectivePeriod(date(2026, 4, 1), date(2027, 4, 1)),
        "obligation_template": ObligationTemplate("Generate e-invoices"),
    }
    fields.update(overrides)
    return RuleVersionSnapshot(**fields)  # type: ignore[arg-type]


def test_rule_version_snapshot() -> None:
    snapshot = _snapshot()
    assert snapshot.is_effective_on(date(2026, 4, 1))
    assert snapshot.is_effective_on(date(2027, 3, 31))
    assert not snapshot.is_effective_on(date(2027, 4, 1))
    assert not snapshot.is_effective_on(date(2026, 3, 31))
    assert snapshot.specification.referenced_attributes() == {"registration_type"}


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"rule_id": RuleVersionId.new()}, "rule_id must be RuleId"),
        ({"rule_version_id": RuleId.new()}, "rule_version_id must be RuleVersionId"),
        ({"version": 0}, "version must be at least 1"),
        ({"regulator": ""}, "regulator must not be blank"),
        ({"title": " x"}, "title must not have leading"),
        ({"specification": "registration_type = regular"}, "specification must be a Specification"),
        ({"effective": (date(2026, 1, 1), None)}, "effective must be EffectivePeriod"),
        ({"obligation_template": {"title": "x"}}, "obligation_template must be ObligationTemplate"),
    ],
)
def test_rule_version_snapshot_invariants(kwargs: dict[str, object], message: str) -> None:
    with _raises(message):
        _snapshot(**kwargs)


# ---- decisions -------------------------------------------------------------------------------


def _decision(**overrides: object) -> ApplicabilityDecision:
    fields: dict[str, object] = {
        "decision_id": DecisionId.new(),
        "tenant_id": TenantId.new(),
        "business_id": BusinessId.new(),
        "rule_version_id": RuleVersionId.new(),
        "result": Applicability.APPLIES,
        "confidence": CERTAIN,
        "evaluated": (PredicateResult(_PREDICATE, Applicability.APPLIES, CERTAIN),),
        "profile_version": 2,
        "decided_at": _NOW,
    }
    fields.update(overrides)
    return ApplicabilityDecision(**fields)  # type: ignore[arg-type]


def test_applicability_decision_review() -> None:
    assert not _decision().needs_review
    assert _decision(result=Applicability.UNSURE).needs_review
    assert _decision(confidence=Confidence(0.5)).needs_review
    assert not _decision(evaluated=()).needs_review


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"decision_id": RuleId.new()}, "decision_id must be DecisionId"),
        ({"tenant_id": None}, "tenant_id must be TenantId"),
        ({"business_id": TenantId.new()}, "business_id must be BusinessId"),
        ({"rule_version_id": RuleId.new()}, "rule_version_id must be RuleVersionId"),
        ({"result": "applies"}, "result must be Applicability"),
        ({"confidence": 1.0}, "confidence must be Confidence"),
        ({"evaluated": []}, "evaluated must be tuple"),
        ({"evaluated": (_PREDICATE,)}, r"evaluated\[0\] must be PredicateResult"),
        ({"profile_version": 0}, "profile_version must be at least 1"),
        ({"decided_at": _NAIVE}, "decided_at must be timezone-aware"),
    ],
)
def test_applicability_decision_invariants(kwargs: dict[str, object], message: str) -> None:
    with _raises(message):
        _decision(**kwargs)


# ---- llm -------------------------------------------------------------------------------------


def test_completion_request_and_response() -> None:
    request = CompletionRequest(
        "extract", "v3", "", "Extract the rule.\n", json_schema={"type": "object"}
    )
    assert request.model is None
    assert request.temperature == 0.0
    assert request.max_tokens == 1024
    assert isinstance(request.json_schema, MappingProxyType)
    assert request.tenant_id is None
    assert request.metadata == {}
    assert isinstance(request.metadata, MappingProxyType)
    hashed = CompletionRequest("extract", "v3", "sys", "user", "m", 1, 10, None, TenantId.new())
    assert hash(hashed) == hash(hashed)
    response = CompletionResponse("", "model-x", 12, 0)
    assert response.cached is False
    assert response.trace_id == ""


def test_completion_request_metadata_is_a_frozen_copy() -> None:
    tags = {"document_id": "doc-1", "run": "abc"}
    request = CompletionRequest("extract", "v3", "sys", "user", metadata=tags)
    tags["document_id"] = "changed"
    assert request.metadata == {"document_id": "doc-1", "run": "abc"}
    assert isinstance(request.metadata, MappingProxyType)
    with pytest.raises(TypeError):
        request.metadata["run"] = "x"  # type: ignore[index]
    assert hash(request) == hash(CompletionRequest("extract", "v3", "sys", "user", metadata=tags))


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"feature": ""}, "feature must not be blank"),
        ({"prompt_version": " v3"}, "prompt_version must not have leading"),
        ({"system": None}, "system must be str"),
        ({"user": " "}, "user must not be blank"),
        ({"model": ""}, "model must not be blank"),
        ({"temperature": -0.1}, r"temperature must be within \[0, 2\]"),
        ({"temperature": 2.1}, r"temperature must be within \[0, 2\]"),
        ({"temperature": float("nan")}, "temperature must be a finite number"),
        ({"max_tokens": 0}, "max_tokens must be at least 1"),
        ({"max_tokens": 1.5}, "max_tokens must be an integer"),
        ({"json_schema": "{}"}, "json_schema must be a mapping"),
        ({"tenant_id": "t"}, "tenant_id must be TenantId"),
        ({"metadata": "doc-1"}, "metadata must be a mapping"),
        ({"metadata": {1: "a"}}, "metadata keys must be strings"),
        ({"metadata": {"pages": 3}}, "metadata values must be strings, got int for 'pages'"),
    ],
)
def test_completion_request_invariants(kwargs: dict[str, object], message: str) -> None:
    fields: dict[str, object] = {
        "feature": "extract",
        "prompt_version": "v3",
        "system": "sys",
        "user": "user",
    }
    fields.update(kwargs)
    with _raises(message):
        CompletionRequest(**fields)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"text": None}, "text must be str"),
        ({"model": ""}, "model must not be blank"),
        ({"input_tokens": -1}, "input_tokens must be at least 0"),
        ({"output_tokens": "3"}, "output_tokens must be an integer"),
        ({"cached": 1}, "cached must be bool"),
        ({"trace_id": 5}, "trace_id must be str"),
    ],
)
def test_completion_response_invariants(kwargs: dict[str, object], message: str) -> None:
    fields: dict[str, object] = {"text": "ok", "model": "m", "input_tokens": 1, "output_tokens": 1}
    fields.update(kwargs)
    with _raises(message):
        CompletionResponse(**fields)  # type: ignore[arg-type]


# ---- notifications ---------------------------------------------------------------------------


def test_rendered_message() -> None:
    whatsapp = RenderedMessage(Channel.WHATSAPP, "+919900000000", "Hello\n", _KEY)
    assert whatsapp.subject == ""
    assert whatsapp.language == "en"
    email = RenderedMessage(
        Channel.EMAIL, "a@b.in", "Hello", _KEY, subject="GST update", language="hi"
    )
    assert email.subject == "GST update"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"channel": "email"}, "channel must be Channel"),
        ({"recipient": ""}, "recipient must not be blank"),
        ({"body": " "}, "body must not be blank"),
        ({"dedupe_key": _KEY.value}, "dedupe_key must be DedupeKey"),
        ({"subject": None}, "subject must be str"),
        ({"channel": Channel.EMAIL}, "email messages need a subject"),
        ({"channel": Channel.EMAIL, "subject": " "}, "email messages need a subject"),
        ({"language": ""}, "language must not be blank"),
    ],
)
def test_rendered_message_invariants(kwargs: dict[str, object], message: str) -> None:
    fields: dict[str, object] = {
        "channel": Channel.WHATSAPP,
        "recipient": "+919900000000",
        "body": "Hello",
        "dedupe_key": _KEY,
    }
    fields.update(kwargs)
    with _raises(message):
        RenderedMessage(**fields)  # type: ignore[arg-type]


def test_delivery_receipt() -> None:
    sent = DeliveryReceipt(DeliveryStatus.SENT, _NOW, "wa-123")
    assert sent.error == ""
    failed = DeliveryReceipt(DeliveryStatus.FAILED, _NOW, error="number opted out")
    assert failed.provider_message_id == ""
    with _raises("status must be DeliveryStatus"):
        DeliveryReceipt("sent", _NOW)  # type: ignore[arg-type]
    with _raises("at must be timezone-aware"):
        DeliveryReceipt(DeliveryStatus.SENT, _NAIVE)
    with _raises("provider_message_id must be str"):
        DeliveryReceipt(DeliveryStatus.SENT, _NOW, None)  # type: ignore[arg-type]
    with _raises("error must be str"):
        DeliveryReceipt(DeliveryStatus.FAILED, _NOW, error=None)  # type: ignore[arg-type]
    with _raises("a failed receipt needs an error"):
        DeliveryReceipt(DeliveryStatus.FAILED, _NOW)
    with _raises("a sent receipt carries no error"):
        DeliveryReceipt(DeliveryStatus.SENT, _NOW, error="boom")


# ---- vectors ---------------------------------------------------------------------------------


def test_embedded_clause_filter_and_score() -> None:
    clause = EmbeddedClause(
        ClauseId.new(), DocumentId.new(), (0.1, 0.2, 3), "embed-v1", "CBIC", DocumentType.CIRCULAR
    )
    assert clause.effective is None
    assert EmbeddedClause(
        ClauseId.new(),
        DocumentId.new(),
        (1.0,),
        "embed-v1",
        "CBIC",
        DocumentType.CIRCULAR,
        EffectivePeriod(date(2026, 1, 1)),
    ).effective == EffectivePeriod(date(2026, 1, 1))
    empty = ClauseFilter()
    assert (empty.regulator, empty.doc_types, empty.as_of) == (None, frozenset(), None)
    narrow = ClauseFilter("CBIC", frozenset({DocumentType.CIRCULAR}), date(2026, 1, 1))
    assert narrow.doc_types == {DocumentType.CIRCULAR}
    assert ScoredClause(clause.clause_id, 0.87).score == 0.87


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"clause_id": DocumentId.new()}, "clause_id must be ClauseId"),
        ({"document_id": None}, "document_id must be DocumentId"),
        ({"vector": ()}, "vector must not be empty"),
        ({"vector": [0.1]}, "vector must be tuple"),
        ({"vector": (0.1, float("nan"))}, r"vector\[1\] must be a finite number"),
        ({"vector": (0.1, "x")}, r"vector\[1\] must be a finite number"),
        ({"model": ""}, "model must not be blank"),
        ({"regulator": " "}, "regulator must not be blank"),
        ({"doc_type": "circular"}, "doc_type must be DocumentType"),
        ({"effective": (date(2026, 1, 1),)}, "effective must be EffectivePeriod"),
    ],
)
def test_embedded_clause_invariants(kwargs: dict[str, object], message: str) -> None:
    fields: dict[str, object] = {
        "clause_id": ClauseId.new(),
        "document_id": DocumentId.new(),
        "vector": (0.1, 0.2),
        "model": "embed-v1",
        "regulator": "CBIC",
        "doc_type": DocumentType.CIRCULAR,
    }
    fields.update(kwargs)
    with _raises(message):
        EmbeddedClause(**fields)  # type: ignore[arg-type]


def test_clause_filter_and_score_invariants() -> None:
    with _raises("regulator must not be blank"):
        ClauseFilter(regulator="")
    with _raises("doc_types must be frozenset"):
        ClauseFilter(doc_types={DocumentType.CIRCULAR})  # type: ignore[arg-type]
    with _raises("doc_types must be DocumentType"):
        ClauseFilter(doc_types=frozenset({"circular"}))  # type: ignore[arg-type]
    with _raises("as_of must be a date"):
        ClauseFilter(as_of=_NOW)
    with _raises("clause_id must be ClauseId"):
        ScoredClause(DocumentId.new(), 0.5)  # type: ignore[arg-type]
    with _raises("score must be a finite number"):
        ScoredClause(ClauseId.new(), float("inf"))


def test_profile_snapshot_as_of_financial_year() -> None:
    snapshot = ProfileSnapshot(
        BusinessId.new(), TenantId.new(), 1, {"turnover_band": "x"}, as_of_fy=FinancialYear(2025)
    )
    assert snapshot.as_of_fy == FinancialYear(2025)
    assert ProfileSnapshot(BusinessId.new(), TenantId.new(), 1, {}).as_of_fy is None
    with pytest.raises(InvariantViolationError, match="as_of_fy must be FinancialYear"):
        ProfileSnapshot(BusinessId.new(), TenantId.new(), 1, {}, as_of_fy="2025-26")  # type: ignore[arg-type]


def test_rule_version_snapshot_recurrence() -> None:
    assert _snapshot().recurrence is None
    recurring = _snapshot(recurrence=Recurrence.monthly(20))
    assert recurring.recurrence == Recurrence.monthly(20)
    with pytest.raises(InvariantViolationError, match="recurrence must be Recurrence"):
        _snapshot(recurrence="monthly")
