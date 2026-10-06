"""The pipeline's events serialise to messages the published event schemas accept, and the
candidate a rule.candidate.created carries is in the extractor's own schema."""

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator

from cw_contracts.events import TOPICS, EventEnvelopeV1
from cw_contracts.events.document_classified_v1 import DocumentClassifiedV1
from cw_contracts.events.document_discovered_v1 import DocumentDiscoveredV1
from cw_contracts.events.document_parsed_v1 import DocumentParsedV1
from cw_contracts.events.rule_candidate_created_v1 import RuleCandidateCreatedV1
from domain_kernel.documents import DocumentType, clause_id_for, document_id_for
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import DocumentId, SourceId, TenantId
from pipeline.domain.candidate import CANDIDATE_SCHEMA, candidate_from_mapping
from pipeline.domain.classification import Relevance, TypeConfidence
from pipeline.domain.events import DocumentClassified, DocumentDiscovered, DocumentParsed
from pipeline.domain.extraction import ExtractionOutcome, RuleExtraction, candidate_id_for
from pipeline.domain.issues import Issue
from pipeline.domain.tasks import TaskId
from py_common.events import decode, encode, to_message

SHA256 = hashlib.sha256(b"%PDF-1.7 notification 17/2025").hexdigest()
SOURCE = SourceId.new()


def event(**overrides: object) -> DocumentDiscovered:
    values: dict[str, object] = {
        "source_id": SOURCE,
        "document_id": document_id_for(SHA256),
        "regulator": "CBIC",
        "url": "https://taxinformation.cbic.gov.in/content/pdf/gst-ct-17-2025.pdf",
        "external_ref": "17/2025-Central Tax",
        "title": "Seeks to extend the due date for FORM GSTR-3B",
        "published_at": date(2025, 9, 18),
        "sha256": SHA256,
        "media_type": "application/pdf",
        "fetched_at": datetime(2026, 10, 6, 4, 30, tzinfo=UTC),
        "raw_uri": f"s3://cw-raw/raw/{SHA256[:2]}/{SHA256}",
    }
    values.update(overrides)
    return DocumentDiscovered(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "overrides",
    [{}, {"external_ref": "", "title": "", "published_at": None}],
    ids=["listed", "undated"],
)
def test_document_discovered_matches_its_schema(overrides: dict[str, object]) -> None:
    message = decode(encode(to_message(event(**overrides))))
    EventEnvelopeV1.model_validate(message.model_dump(mode="json"))
    spec = TOPICS[message.topic]
    assert message.topic == "document.discovered"
    assert message.schema_version == spec.version
    assert not spec.tenant_scoped
    assert message.tenant_id is None
    spec.model.model_validate(message.payload)
    payload = DocumentDiscoveredV1.model_validate(message.payload)
    assert payload.document_id == document_id_for(SHA256).value


def test_a_document_event_is_keyed_by_its_source_and_has_no_tenant() -> None:
    assert event().partition_key == str(SOURCE)
    with pytest.raises(InvariantViolationError, match="regulatory"):
        event(tenant_id=TenantId.new())
    with pytest.raises(InvariantViolationError, match="first half of sha256"):
        event(document_id=DocumentId.new())


def parsed(**overrides: object) -> DocumentParsed:
    values: dict[str, object] = {
        "source_id": SOURCE,
        "document_id": document_id_for(SHA256),
        "doc_type": DocumentType.NOTIFICATION,
        "title": "Seeks to extend the due date for FORM GSTR-3B",
        "language": "en",
        "published_at": date(2025, 9, 18),
        "clause_count": 3,
        "clause_refs": ("en.p1", "en.p2", "en.p3"),
        "parser_version": "pdf-tables@1",
    }
    values.update(overrides)
    return DocumentParsed(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {
            "doc_type": DocumentType.STATUTE,
            "published_at": None,
            "clause_count": 1,
            "clause_refs": ("hi.p1",),
            "parser_version": "manual@1",
        },
    ],
    ids=["notification", "transcribed-statute"],
)
def test_document_parsed_matches_its_schema(overrides: dict[str, object]) -> None:
    message = decode(encode(to_message(parsed(**overrides))))
    EventEnvelopeV1.model_validate(message.model_dump(mode="json"))
    spec = TOPICS[message.topic]
    assert (message.topic, message.schema_version) == ("document.parsed", spec.version)
    assert spec.version == "1.1.0"
    assert message.tenant_id is None
    payload = DocumentParsedV1.model_validate(message.payload)
    assert payload.clause_count == len(payload.clause_refs)


def test_a_parsed_event_counts_its_unique_clauses() -> None:
    with pytest.raises(InvariantViolationError, match="count"):
        parsed(clause_count=2)
    with pytest.raises(InvariantViolationError, match="unique"):
        parsed(clause_count=2, clause_refs=("en.p1", "en.p1"))
    with pytest.raises(InvariantViolationError, match="parser_version"):
        parsed(parser_version="pdf")


SCHEMAS = Path(__file__).resolve().parents[4] / "packages" / "contracts" / "events" / "schemas"


def schema(topic: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((SCHEMAS / f"{topic}.v1.json").read_text("utf-8"))
    return loaded


def strict(topic: str) -> Draft202012Validator:
    return Draft202012Validator(schema(topic), format_checker=Draft202012Validator.FORMAT_CHECKER)


def plain(value: object) -> object:
    """The kernel's frozen schema as JSON values."""
    if isinstance(value, Mapping):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [plain(item) for item in value]
    return value


def classified(**overrides: object) -> DocumentClassified:
    values: dict[str, object] = {
        "source_id": SOURCE,
        "document_id": document_id_for(SHA256),
        "source_key": "cbic_notifications",
        "doc_type": DocumentType.NOTIFICATION,
        "relevance": Relevance.RELEVANT,
        "confidence": TypeConfidence.CERTAIN,
        "reasons": ("its opening names it a notification, the type its source publishes",),
        "classifier": "detector@1",
    }
    values.update(overrides)
    return DocumentClassified(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {
            "doc_type": DocumentType.CIRCULAR,
            "confidence": TypeConfidence.CONFLICT,
            "task_id": TaskId(UUID(int=9)),
        },
        {
            "doc_type": DocumentType.STATUTE,
            "classifier": "triage",
            "task_id": TaskId(UUID(int=9)),
            "decided_by": UUID(int=42),
        },
        {"relevance": Relevance.IRRELEVANT, "confidence": TypeConfidence.DEFAULT},
    ],
    ids=["certain", "conflict", "triaged", "irrelevant"],
)
def test_document_classified_matches_its_schema(overrides: dict[str, object]) -> None:
    message = decode(encode(to_message(classified(**overrides))))
    EventEnvelopeV1.model_validate(message.model_dump(mode="json"))
    spec = TOPICS[message.topic]
    assert (message.topic, message.schema_version) == ("document.classified", spec.version)
    assert spec.version == "1.0.0"
    assert message.tenant_id is None
    strict("document.classified").validate(message.payload)
    payload = DocumentClassifiedV1.model_validate(message.payload)
    assert payload.document_id == document_id_for(SHA256).value


def test_a_classified_event_gives_its_reasons() -> None:
    with pytest.raises(InvariantViolationError, match="reasons"):
        classified(reasons=())
    assert classified().partition_key == str(SOURCE)


def test_the_candidate_payload_schema_is_the_extractors_output_schema() -> None:
    """A rule.candidate.created's candidate is what the extractor asks the model for: the schema
    file keeps CANDIDATE_SCHEMA (without its $schema) under $defs, and a change to one without
    the other fails here."""
    extractor = plain(CANDIDATE_SCHEMA)
    assert isinstance(extractor, dict)
    fields = {key: value for key, value in extractor.items() if key != "$schema"}
    document = schema("rule.candidate.created")
    assert document["$defs"]["rule_candidate_fields"] == fields
    assert document["properties"]["candidate"]["anyOf"] == [
        {"$ref": "#/$defs/rule_candidate_fields"},
        {"type": "null"},
    ]
    generated = RuleCandidateCreatedV1.model_fields["candidate"]
    assert "RuleCandidateFields" in str(generated.annotation)


GOLDEN = {
    "title": "Example: the due date of an example return is extended",
    "summary": "An example notification extends the due date of FORM GSTR-3B for monthly filers.",
    "doc_kind": "notification",
    "change_kind": "extension",
    "effective_from": "2026-04-20",
    "effective_to": None,
    "references": [],
    "applies_to": [
        {
            "attribute": "filing_scheme",
            "operator": "eq",
            "value": "regular_monthly",
            "clause_ref": "en.p3",
        }
    ],
    "obligation": {
        "title": "File FORM GSTR-3B for the example month",
        "steps": ["Furnish FORM GSTR-3B by the extended date"],
        "evidence_type": "filing_acknowledgement",
        "due_in_days": None,
        "clause_ref": "en.p3",
    },
    "recurrence": None,
    "amounts": [],
    "citations": [{"clause_ref": "en.p3", "quote": "extends the due date"}],
    "confidence": 0.9,
}


def extraction(**overrides: object) -> RuleExtraction:
    document_id = document_id_for(SHA256)
    values: dict[str, object] = {
        "document_id": document_id,
        "prompt_version": "extraction.rule_candidate@1",
        "candidate_id": candidate_id_for(document_id, "extraction.rule_candidate@1"),
        "outcome": ExtractionOutcome.EXTRACTED,
        "model": "scripted/golden",
        "attempts": 1,
        "source_key": "cbic_notifications",
        "doc_type": DocumentType.NOTIFICATION,
        "regulator": "CBIC",
        "issues": (),
        "citation_count": 1,
        "confidence": 0.9,
        "needs_review": False,
        "answer": json.dumps(GOLDEN),
        "ontology_version": "0.2.0",
        "extracted_at": datetime(2026, 10, 6, 6, 30, tzinfo=UTC),
        "fields": candidate_from_mapping(GOLDEN).to_mapping(),
    }
    values.update(overrides)
    return RuleExtraction(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {
            "outcome": ExtractionOutcome.UNPARSEABLE,
            "fields": None,
            "attempts": 2,
            "confidence": 0.0,
            "citation_count": 0,
            "needs_review": True,
            "doc_type": DocumentType.CIRCULAR,
            "issues": (Issue("output_unparseable", "not JSON: Expecting value at 0"),),
        },
    ],
    ids=["extracted", "unparseable"],
)
def test_rule_candidate_created_matches_its_schema(overrides: dict[str, object]) -> None:
    stored = extraction(**overrides)
    message = decode(encode(to_message(stored.event(SOURCE))))
    EventEnvelopeV1.model_validate(message.model_dump(mode="json"))
    spec = TOPICS[message.topic]
    assert (message.topic, message.schema_version) == ("rule.candidate.created", spec.version)
    assert spec.version == "1.1.0"
    assert message.tenant_id is None
    strict("rule.candidate.created").validate(message.payload)
    payload = RuleCandidateCreatedV1.model_validate(message.payload)
    assert payload.candidate_id == stored.candidate_id.value
    if stored.fields is None:
        assert (payload.candidate, payload.clause_ids, payload.suggested_rule_key) == (
            None,
            [],
            None,
        )
    else:
        assert payload.candidate is not None
        assert payload.candidate.model_dump(mode="json") == GOLDEN
        assert payload.suggested_rule_key == "gstr3b_monthly"
        assert payload.clause_ids == [clause_id_for(stored.document_id, "en.p3").value]
