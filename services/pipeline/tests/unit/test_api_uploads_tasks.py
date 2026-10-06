"""The upload and task routes on the memory store, in header, dual and token mode: who may upload,
read the queue, resolve and dismiss; what each answers; the ingest each starts; the audit
entries each write; and the limits an upload is held to."""

import base64
import hashlib
import io
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from domain_kernel.access import Role, Scope
from domain_kernel.documents import DocumentType
from domain_kernel.ids import DocumentId, TenantId, UserId
from pipeline.domain.errors import IngestUnavailableError
from pipeline.domain.raw_documents import DocumentStatus
from pipeline.domain.tasks import PipelineTask, TaskKind
from pipeline.domain.transcripts import decode_transcript
from pipeline.infrastructure.adapters import RegistryAdapterTypes
from pipeline.infrastructure.memory import MemoryStore
from pipeline.infrastructure.raw_store import MemoryRawStore
from pipeline.infrastructure.temporal import ingest_payload
from pipeline.main import build_app
from pipeline.testing import WRITE_TOKEN, MemoryCrawls, MemoryIngests, pipeline_settings
from pipeline.workflows import IngestRequest
from py_common.auth.testing import TestIssuer, bearer
from py_common.settings import AuthMode

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
ISSUER = TestIssuer()
BASE = "/v1/pipeline"
WRITE = {"x-cw-write-token": WRITE_TOKEN}
INTERNAL = TenantId.new()
ADMIN_ID = UserId.new()
ADMIN = bearer(ISSUER.user(INTERNAL, [Role.ADMIN], mfa=True, user_id=ADMIN_ID))
ANALYST = bearer(ISSUER.user(INTERNAL, [Role.ANALYST], mfa=True))
OWNER = bearer(ISSUER.user(TenantId.new(), [Role.OWNER]))
SERVICE = bearer(ISSUER.service("pipeline", [Scope.RULEBOOK_WRITE]))
ASSERTED = UUID(int=99)
REASON = "An example document for the tests"
FIELDS = {"actor_id": str(ASSERTED), "reason": REASON}
NOW = datetime(2026, 10, 6, 6, 0, tzinfo=UTC)
TRANSCRIPT = {
    "title": "Example statute",
    "blocks": [
        {"type": "heading", "text": "Example chapter"},
        {"type": "paragraph", "number": "1.", "text": "Example text of the first section."},
        {"type": "table", "header": ["Example", "Rate"], "rows": [["Example item", "5%"]]},
    ],
}


def table_notification() -> bytes:
    wrapper = json.loads((FIXTURES / "cbic" / "gst-ct-10-2025.pdf.json").read_text())
    return base64.b64decode(wrapper["data"])


def scan() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class Wired:
    def __init__(self, client: TestClient, store: MemoryStore, raw: MemoryRawStore) -> None:
        self.client = client
        self.store = store
        self.raw = raw
        app = client.app
        assert isinstance(app, FastAPI)
        self.ingests: MemoryIngests = app.state.ingests

    def upload(
        self,
        content: bytes,
        *,
        key: str = "cgst_rules",
        media_type: str = "application/pdf",
        headers: dict[str, str] | None = None,
        **fields: str,
    ) -> Any:
        return self.client.post(
            f"{BASE}/sources/{key}/uploads",
            files={"file": ("document.pdf", content, media_type)},
            data={**FIELDS, **fields},
            headers=WRITE if headers is None else headers,
        )

    def task_for(self, content: bytes) -> PipelineTask:
        """What the ingest does with a document no parser reads: a manual-parse task."""
        document_id = DocumentId(UUID(hashlib.sha256(content).hexdigest()[:32]))
        with self.store() as unit:
            record = unit.documents.get(document_id)
            assert record is not None
            unit.documents.set_status(document_id, DocumentStatus.FAILED)
            return unit.tasks.open(
                PipelineTask.opened(
                    TaskKind.MANUAL_PARSE,
                    document_id,
                    record.source_key,
                    at=NOW,
                    reason="pdf@1: UnparsedDocumentError: the PDF has no text layer",
                )
            )


def wired(mode: AuthMode, **overrides: Any) -> Iterator[Wired]:
    store, raw, ingests = MemoryStore(), MemoryRawStore(), MemoryIngests()
    values: dict[str, Any] = {
        "pipeline_knowledge_enabled": True,
        **ISSUER.settings_overrides(mode),
    }
    values.update(overrides)
    app = build_app(
        pipeline_settings(**values),
        units=store,
        raw_store=raw,
        starter=MemoryCrawls(),
        adapter_types=RegistryAdapterTypes(),
        ingests=ingests,
    )
    app.state.ingests = ingests
    with TestClient(app) as client:
        yield Wired(client, store, raw)


@pytest.fixture
def header() -> Iterator[Wired]:
    yield from wired("header")


@pytest.fixture
def token() -> Iterator[Wired]:
    yield from wired("token")


@pytest.fixture
def dual() -> Iterator[Wired]:
    yield from wired("dual")


def problem(response: Any) -> str:
    kind: str = response.json()["type"]
    return kind.rsplit(":", 1)[-1]


# ---------------------------------------------------------------- uploads


def test_an_upload_is_stored_recorded_audited_and_its_ingest_started(header: Wired) -> None:
    response = header.upload(
        table_notification(),
        title="Example statute extract",
        published_on="2017-06-19",
        external_ref="Rule 61",
    )
    assert response.status_code == 202, response.text
    body = response.json()
    document = body["document"]
    digest = hashlib.sha256(table_notification()).hexdigest()
    assert (body["duplicate"], document["sha256"], document["source_key"]) == (
        False,
        digest,
        "cgst_rules",
    )
    assert document["source_url"] == f"upload://cgst_rules/{digest}"
    assert (document["title"], document["external_ref"], document["published_on"]) == (
        "Example statute extract",
        "Rule 61",
        "2017-06-19",
    )
    assert (document["status"], document["parser_version"], document["doc_type"]) == (
        "discovered",
        "",
        None,
    )
    assert header.raw.files[document["storage_key"]] == table_notification()
    (event,) = header.store.events
    assert (event.topic, str(event.document_id)) == ("document.discovered", document["document_id"])
    (entry,) = header.store.audit
    assert (entry.action, entry.subject_id, entry.reason) == (
        "pipeline.document.upload",
        document["document_id"],
        REASON,
    )
    assert (entry.actor.id, entry.tenant_id) == (str(ASSERTED), None)
    (start,) = header.ingests.started
    assert start.workflow_id == body["workflow_id"]
    assert body["workflow_id"].startswith("pipeline-upload-cgst_rules-")
    assert (start.regulator, start.knowledge, start.duplicate, start.transcript_key) == (
        "CBIC",
        True,
        False,
        "",
    )
    request = IngestRequest.model_validate(ingest_payload(start))
    assert request.stored is not None
    assert (request.stored.title, str(request.stored.published_at)) == (
        "Example statute extract",
        "2017-06-19",
    )


def test_the_same_bytes_again_are_a_duplicate_ingested_again(header: Wired) -> None:
    first = header.upload(scan()).json()
    again = header.upload(scan(), document_type="notification")
    assert again.status_code == 202
    assert again.json()["duplicate"] is True
    assert again.json()["document"]["document_id"] == first["document"]["document_id"]
    assert [event.topic for event in header.store.events] == ["document.discovered"]
    assert [entry.action for entry in header.store.audit] == ["pipeline.document.upload"] * 2
    assert [start.duplicate for start in header.ingests.started] == [False, True]


def test_the_uploaders_type_is_recorded(header: Wired) -> None:
    body = header.upload(scan(), key="cbic_notifications", document_type="circular").json()
    assert body["document"]["doc_type"] == "circular"
    record = header.store.documents[DocumentId(UUID(body["document"]["document_id"]))]
    assert record.doc_type is DocumentType.CIRCULAR


@pytest.mark.parametrize(
    ("content", "media_type", "status", "slug"),
    [
        (b"plain text", "text/plain", 415, "pipeline-upload-unsupported"),
        (b"%PDF-1.7 a pdf", "text/html", 415, "pipeline-upload-unsupported"),
        (b"just words", "text/html", 415, "pipeline-upload-unsupported"),
        (b"", "application/pdf", 415, "pipeline-upload-unsupported"),
    ],
)
def test_a_file_that_is_not_a_pdf_or_a_page_is_refused(
    header: Wired, content: bytes, media_type: str, status: int, slug: str
) -> None:
    response = header.upload(content, media_type=media_type)
    assert (response.status_code, problem(response)) == (status, slug)
    assert (header.store.documents, header.raw.files, header.ingests.started) == ({}, {}, [])


def test_an_html_page_is_taken(header: Wired) -> None:
    page = b"\xef\xbb\xbf  <html><body><p>Example page</p></body></html>"
    response = header.upload(page, media_type="text/html; charset=utf-8")
    assert response.status_code == 202
    assert response.json()["document"]["content_type"] == "text/html"


def test_an_upload_past_the_limit_is_refused_before_it_is_read() -> None:
    for wired_app in wired("header", pipeline_upload_max_bytes=1_000):
        response = wired_app.upload(table_notification())
        assert (response.status_code, problem(response)) == (413, "pipeline-upload-too-large")
        small = wired_app.upload(b"%PDF-1.7 " + b"x" * 1_200)
        assert (small.status_code, problem(small)) == (413, "pipeline-upload-too-large")
        assert wired_app.store.documents == {}


def test_an_unknown_source_and_a_short_reason_are_refused(header: Wired) -> None:
    unknown = header.upload(scan(), key="no_such_source")
    assert (unknown.status_code, problem(unknown)) == (404, "pipeline-source-not-found")
    short = header.upload(scan(), reason="short")
    assert short.status_code == 422
    assert header.store.audit == []


def test_an_ingest_temporal_does_not_start_is_a_503_and_the_document_stays(header: Wired) -> None:
    header.ingests.fail = IngestUnavailableError("temporal is away")
    response = header.upload(scan())
    assert (response.status_code, problem(response)) == (503, "pipeline-ingest-unavailable")
    assert len(header.store.documents) == 1, "stored: an upload of the same file mends it"
    again = header.upload(scan())
    assert (again.status_code, again.json()["duplicate"]) == (202, True)


def test_in_header_mode_an_upload_needs_the_write_token(header: Wired) -> None:
    for headers in ({}, {"x-cw-write-token": "wrong"}):
        response = header.upload(scan(), headers=headers)
        assert (response.status_code, problem(response)) == (401, "pipeline-write-token-invalid")
    for unset in wired("header", rulebook_write_token=None):
        refused = unset.upload(scan())
        assert (refused.status_code, problem(refused)) == (503, "pipeline-writes-disabled")


def test_in_token_mode_only_an_admin_uploads_and_is_audited_as_themselves(token: Wired) -> None:
    assert token.upload(scan(), headers=WRITE).status_code == 401
    assert token.upload(scan(), headers=ANALYST).status_code == 403
    assert token.upload(scan(), headers=SERVICE).status_code == 403
    accepted = token.upload(scan(), headers=ADMIN)
    assert accepted.status_code == 202
    (entry,) = token.store.audit
    assert (entry.actor.id, entry.actor.label) == (str(ADMIN_ID), "admin")


def test_in_dual_mode_the_bearer_or_the_shared_token_uploads(dual: Wired) -> None:
    assert dual.upload(scan(), headers=ADMIN).status_code == 202
    assert dual.upload(table_notification(), headers=WRITE).status_code == 202
    assert dual.upload(scan(), headers=ANALYST).status_code == 403


# ---------------------------------------------------------------- tasks


def test_the_queue_lists_tasks_oldest_first_with_their_documents(header: Wired) -> None:
    header.upload(scan())
    task = header.task_for(scan())
    response = header.client.get(f"{BASE}/tasks", params={"status": "open"})
    assert response.status_code == 200
    (item,) = response.json()["items"]
    assert (item["task_id"], item["kind"], item["status"], item["source_key"]) == (
        str(task.id),
        "manual_parse",
        "open",
        "cgst_rules",
    )
    assert item["reason"].startswith("pdf@1: UnparsedDocumentError")
    assert item["document"]["status"] == "failed"
    assert header.client.get(f"{BASE}/tasks", params={"kind": "triage"}).json()["items"] == []
    resolved = header.client.get(f"{BASE}/tasks", params={"status": "resolved"})
    assert resolved.json() == {"items": [], "next_cursor": None}
    assert header.client.get(f"{BASE}/tasks", params={"status": "closed"}).status_code == 422


def test_the_queue_pages_with_a_cursor_of_its_filters(header: Wired) -> None:
    for n in range(3):
        content = scan() + f"% example {n}".encode()
        header.upload(content)
        header.task_for(content)
    first = header.client.get(f"{BASE}/tasks", params={"limit": 2, "status": "open"}).json()
    rest = header.client.get(
        f"{BASE}/tasks", params={"limit": 2, "status": "open", "cursor": first["next_cursor"]}
    ).json()
    assert len(first["items"]) == 2
    assert len(rest["items"]) == 1
    assert rest["next_cursor"] is None
    other = header.client.get(f"{BASE}/tasks", params={"limit": 2, "cursor": first["next_cursor"]})
    assert (other.status_code, problem(other)) == (422, "pagination-cursor-invalid")


def test_a_transcript_resolves_a_manual_parse_and_starts_its_ingest(header: Wired) -> None:
    header.upload(scan())
    task = header.task_for(scan())
    response = header.client.post(
        f"{BASE}/tasks/{task.id}/resolve",
        json={**FIELDS, "transcript": TRANSCRIPT},
        headers=WRITE,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    resolved = body["task"]
    assert (resolved["status"], resolved["resolved_by"], resolved["note"]) == (
        "resolved",
        str(ASSERTED),
        REASON,
    )
    resolution = resolved["resolution"]
    assert (resolution["parser_version"], resolution["clauses"]) == ("manual@1", 4)
    key = resolution["transcript_key"]
    assert decode_transcript(header.raw.files[key]).title == "Example statute"
    assert (body["workflow_id"], body["started"]) == (
        f"pipeline-manual-parse-{task.id.value.hex}",
        True,
    )
    start = header.ingests.started[-1]
    assert (start.transcript_key, start.duplicate) == (key, True)
    request = IngestRequest.model_validate(ingest_payload(start))
    assert request.transcript_key == key
    entry = header.store.audit[-1]
    assert (entry.action, entry.subject_type, entry.subject_id) == (
        "pipeline.task.resolve",
        "pipeline_task",
        str(task.id),
    )
    assert entry.before is not None
    assert entry.before["status"] == "open"

    again = header.client.post(
        f"{BASE}/tasks/{task.id}/resolve", json={**FIELDS, "transcript": TRANSCRIPT}, headers=WRITE
    )
    assert (again.status_code, again.json()["started"]) == (200, False), "the same, idempotent"
    other = {**TRANSCRIPT, "title": "Another example"}
    closed = header.client.post(
        f"{BASE}/tasks/{task.id}/resolve", json={**FIELDS, "transcript": other}, headers=WRITE
    )
    assert (closed.status_code, problem(closed)) == (409, "pipeline-task-closed")


def test_a_resolution_whose_ingest_did_not_start_is_started_by_the_same_request(
    header: Wired,
) -> None:
    header.upload(scan())
    task = header.task_for(scan())
    header.ingests.fail = IngestUnavailableError("temporal is away")
    body = {**FIELDS, "transcript": TRANSCRIPT}
    failed = header.client.post(f"{BASE}/tasks/{task.id}/resolve", json=body, headers=WRITE)
    assert (failed.status_code, problem(failed)) == (503, "pipeline-ingest-unavailable")
    retried = header.client.post(f"{BASE}/tasks/{task.id}/resolve", json=body, headers=WRITE)
    assert (retried.status_code, retried.json()["started"]) == (200, True)
    assert [e.action for e in header.store.audit].count("pipeline.task.resolve") == 1


@pytest.mark.parametrize(
    ("transcript", "fragment"),
    [
        (None, "resolved with the analyst's transcript"),
        ({"blocks": [{"type": "table", "rows": [[" "]]}]}, "blocks[0].rows[0] has no text"),
        ({"blocks": [{"type": "list", "text": "x"}]}, None),
        ({"blocks": []}, None),
    ],
)
def test_a_resolution_that_does_not_fit_is_refused(
    header: Wired, transcript: Any, fragment: str | None
) -> None:
    header.upload(scan())
    task = header.task_for(scan())
    body = {**FIELDS} if transcript is None else {**FIELDS, "transcript": transcript}
    response = header.client.post(f"{BASE}/tasks/{task.id}/resolve", json=body, headers=WRITE)
    assert response.status_code == 422
    if fragment is not None:
        assert fragment in response.json()["detail"]
    assert header.ingests.started[-1].transcript_key == "", "no resolution's ingest started"


def test_a_task_is_dismissed_with_a_reason_once(header: Wired) -> None:
    header.upload(scan())
    task = header.task_for(scan())
    response = header.client.post(
        f"{BASE}/tasks/{task.id}/dismiss",
        json={"actor_id": str(ASSERTED), "reason": "A duplicate scan of another notice"},
        headers=WRITE,
    )
    assert response.status_code == 200
    assert (response.json()["status"], response.json()["note"]) == (
        "dismissed",
        "A duplicate scan of another notice",
    )
    assert response.json()["document"]["status"] == "failed"
    again = header.client.post(f"{BASE}/tasks/{task.id}/dismiss", json=FIELDS, headers=WRITE)
    assert (again.status_code, problem(again)) == (409, "pipeline-task-closed")
    unknown = header.client.post(f"{BASE}/tasks/{UUID(int=5)}/dismiss", json=FIELDS, headers=WRITE)
    assert (unknown.status_code, problem(unknown)) == (404, "pipeline-task-not-found")
    assert header.store.audit[-1].action == "pipeline.task.dismiss"


def test_in_token_mode_regulatory_roles_read_the_queue_and_admins_work_it(token: Wired) -> None:
    token.upload(scan(), headers=ADMIN)
    task = token.task_for(scan())
    for reader in (ANALYST, ADMIN):
        assert token.client.get(f"{BASE}/tasks", headers=reader).status_code == 200
    assert token.client.get(f"{BASE}/tasks", headers=OWNER).status_code == 403
    assert token.client.get(f"{BASE}/tasks").status_code == 401
    body = {**FIELDS, "transcript": TRANSCRIPT}
    refused = token.client.post(f"{BASE}/tasks/{task.id}/resolve", json=body, headers=ANALYST)
    assert refused.status_code == 403
    resolved = token.client.post(f"{BASE}/tasks/{task.id}/resolve", json=body, headers=ADMIN)
    assert resolved.status_code == 200
    assert resolved.json()["task"]["resolved_by"] == str(ADMIN_ID), (
        "the token's user, not the body's"
    )
