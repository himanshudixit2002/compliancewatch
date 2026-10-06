"""The pipeline's store over a recorded notification, in one process.

CBIC's listing and Notification 01/2026-Central Tax replay from the recorded fixtures through the
registry's CBIC adapter; the raw store is the S3 store against the stubbed S3 endpoint, which
checks every signature; the records and the outbox are the memory store's. The notification is
fetched, its bytes land in the bucket under their digest, encrypted, its row and its
document.discovered commit together, the parse reads the bytes back from the bucket, and a
refetch adds nothing: no object, no row, no event.
"""

from datetime import UTC, datetime
from pathlib import Path

from cw_contracts.events import TOPICS
from cw_contracts.events.document_discovered_v1 import DocumentDiscoveredV1
from domain_kernel.documents import document_id_for
from pipeline.application.activities import (
    Discovered,
    FetchAndStore,
    ParseDocument,
    ParseRequest,
)
from pipeline.application.store_document import StoreDocument
from pipeline.domain.raw_documents import DocumentStatus
from pipeline.infrastructure.adapters import RegistryCatalog, source_id_for
from pipeline.infrastructure.http import ClientConfig, PoliteClient
from pipeline.infrastructure.memory import MemoryStore
from pipeline.infrastructure.parsers import SourceParsers
from pipeline.infrastructure.raw_store import S3RawStore, storage_key_for
from pipeline.infrastructure.s3 import S3Client, S3Credentials
from pipeline.testing import StubS3, recorded_sources
from py_common.events import decode, encode, to_message

FIXTURES = Path(__file__).resolve().parents[4] / "services" / "pipeline" / "tests" / "fixtures"
CREDENTIALS = S3Credentials("pipeline-raw-writer", "secret-of-the-journey")
NUMBER = "01/2026-Central Tax"
SINCE = datetime(2026, 1, 1, tzinfo=UTC)


async def test_a_recorded_notification_is_stored_once_and_announced_once() -> None:
    site = PoliteClient(
        ClientConfig(min_delay_seconds=0, respect_robots=False),
        transport=recorded_sources(FIXTURES),
        sleep=lambda _: None,
    )
    catalog = RegistryCatalog(site)
    bucket = StubS3("cw-raw-journey", CREDENTIALS)
    raw_store = S3RawStore(
        S3Client(
            bucket=bucket.bucket,
            region=bucket.region,
            credentials=CREDENTIALS,
            endpoint_url="http://minio.journey:9000",
            transport=bucket.transport(),
        )
    )
    store = MemoryStore()
    fetch_and_store = FetchAndStore(StoreDocument(catalog, store, raw_store))

    cbic = source_id_for("cbic_notifications")
    listing = catalog.resolve(cbic).adapter.list_documents(SINCE)
    (listed,) = [d for d in listing if d.ref.external_ref == NUMBER]
    discovered = Discovered(
        source_id=cbic.value,
        url=listed.ref.url,
        external_ref=NUMBER,
        title=listed.title,
        published_at=listed.published_at,
    )

    stored = await fetch_and_store.run(discovered)
    assert (stored.source_key, stored.regulator, stored.media_type) == (
        "cbic_notifications",
        "CBIC",
        "application/pdf",
    )
    assert not stored.duplicate
    assert stored.storage_key == f"raw/{storage_key_for(stored.sha256)}"
    assert stored.raw_uri == f"s3://cw-raw-journey/{stored.storage_key}"
    content, headers = bucket.objects[stored.storage_key]
    assert content.startswith(b"%PDF-")
    assert len(content) == stored.size
    assert headers["x-amz-server-side-encryption"] == "AES256"
    assert headers["content-type"] == "application/pdf"

    (record,) = store.documents.values()
    assert record.document_id == document_id_for(stored.sha256)
    assert (record.source_key, record.source_url, record.external_ref) == (
        "cbic_notifications",
        listed.ref.url,
        NUMBER,
    )
    assert (record.published_on, record.status) == (listed.published_at, DocumentStatus.DISCOVERED)
    assert store.sources["cbic_notifications"].adapter_type == "cbic"

    (event,) = store.events
    message = decode(encode(to_message(event)))
    assert (message.topic, message.tenant_id) == ("document.discovered", None)
    assert message.schema_version == TOPICS["document.discovered"].version
    payload = DocumentDiscoveredV1.model_validate(message.payload)
    assert (payload.document_id, payload.source_id) == (record.document_id.value, cbic.value)
    assert (payload.regulator, payload.external_ref, payload.raw_uri) == (
        "CBIC",
        NUMBER,
        stored.raw_uri,
    )
    assert payload.published_at == listed.published_at

    parse = ParseDocument(SourceParsers(catalog), raw_store)
    parsed = await parse.run(ParseRequest(document_id=stored.document_id, stored=stored))
    assert parsed.document_id == stored.document_id
    assert (parsed.doc_type, parsed.clause_count > 3) == ("notification", True)
    assert bucket.methods() == ["HEAD", "PUT", "GET"]

    again = await fetch_and_store.run(discovered)
    assert again.duplicate
    assert (again.document_id, again.storage_key) == (stored.document_id, stored.storage_key)
    assert bucket.methods() == ["HEAD", "PUT", "GET"], "the refetch never reached the bucket"
    assert len(bucket.objects) == len(store.documents) == len(store.events) == 1
