"""The pipeline's events serialise to messages the published event schemas accept."""

import hashlib
from datetime import UTC, date, datetime

import pytest

from cw_contracts.events import TOPICS, EventEnvelopeV1
from cw_contracts.events.document_discovered_v1 import DocumentDiscoveredV1
from domain_kernel.documents import document_id_for
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import DocumentId, SourceId, TenantId
from pipeline.domain.events import DocumentDiscovered
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
