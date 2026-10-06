"""A manual parse through the one deployable: a document no parser reads opens a task, and the
analyst's transcript resolves it and registers it.

The whole app runs as ``cw-mvp serve`` runs it, on memory stores, with knowledge on and the
pipeline's ingest starter handed in (a recording one, no Temporal). An admin uploads two documents
on the internal listener with the shared write token: the recorded table-heavy notification
10/2025-Central Tax, and a synthetic scan (a PDF page with no text layer) of the CGST Rules, an
upload-only statute source. Each ingest then runs as the worker runs it, step by step: the
recorded notification parses with the table-aware PDF parser and is registered in the rulebook
over its HTTP API; the scan is read by no parser, so its document is set failed, a manual-parse
task opens and nothing is registered. The analyst's transcript (synthetic text) resolves the task
and starts an ingest that parses the scan from the transcript as manual@1 and registers it as a
statute; an ingest of the same bytes later parses it from the transcript again and opens no task.
The public listener answers none of these routes in header mode.
"""

import base64
import io
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Final
from uuid import UUID

import httpx2
from pypdf import PdfWriter

from cw_mvp.app import CombinedApp
from cw_mvp.testing import LOCALHOST, MEMORY_SERVICES, running_app
from domain_kernel.ids import DocumentId
from pipeline.application.activities import (
    OpenManualParse,
    ParseDocument,
    ParseFailure,
    ParseRequest,
)
from pipeline.application.knowledge_activities import RegisterDocument, RegisterRequest
from pipeline.domain.errors import UnparsedDocumentError, UnsupportedDocumentError
from pipeline.domain.ports import IngestStart
from pipeline.domain.raw_documents import DocumentStatus
from pipeline.infrastructure.adapters import StoreCatalog
from pipeline.infrastructure.memory import MemoryStore
from pipeline.infrastructure.parsers import ParserChain
from pipeline.infrastructure.raw_store import MemoryRawStore
from pipeline.infrastructure.rulebook_client import HttpRulebook
from pipeline.infrastructure.temporal import ingest_payload
from pipeline.testing import MemoryIngests, recorded_client
from pipeline.workflows import IngestRequest

FIXTURES: Final = Path(__file__).resolve().parents[4] / "services/pipeline/tests/fixtures"
PIPELINE: Final = "/v1/pipeline"
RULEBOOK: Final = "/v1/rulebook"
TOKEN: Final = "journey-write-token"
WRITE: Final = {"x-cw-write-token": TOKEN}
ACTOR: Final = str(UUID(int=42))
ROUTE_NOT_FOUND: Final = "urn:compliancewatch:problem:route-not-found"
TRANSCRIPT: Final = {
    "title": "Example rules for the journey",
    "blocks": [
        {"type": "heading", "text": "Example chapter of the journey"},
        {
            "type": "paragraph",
            "number": "1.",
            "text": "Example text of the first rule, typed by an analyst for the journey.",
        },
        {
            "type": "table",
            "header": ["Example item", "Example rate"],
            "rows": [["First example item", "5%"], ["Second example item", "12%"]],
        },
    ],
}


def table_notification() -> bytes:
    wrapper = json.loads((FIXTURES / "cbic" / "gst-ct-10-2025.pdf.json").read_text())
    return base64.b64decode(wrapper["data"])


def scan() -> bytes:
    """A synthetic scan: one PDF page with no text layer, which no parser reads."""
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class Pipeline:
    """The pipeline's store, raw store and ingest starter, shared by the app and the steps the
    worker would run, and the steps themselves."""

    def __init__(self) -> None:
        self.store = MemoryStore()
        self.raw = MemoryRawStore()
        self.ingests = MemoryIngests()

    def overrides(self) -> dict[str, dict[str, Any]]:
        return {"pipeline": {"units": self.store, "raw_store": self.raw, "ingests": self.ingests}}

    async def ingest(self, start: IngestStart, rulebook: HttpRulebook) -> dict[str, Any]:
        """What the ingest workflow does with a stored document, one activity after another:
        parse; on a parse no parser can do, open the manual-parse task; else register."""
        request = IngestRequest.model_validate(ingest_payload(start))
        assert request.stored is not None
        chain = ParserChain(StoreCatalog(self.store, recorded_client()))
        parse = ParseRequest(
            document_id=request.stored.document_id,
            stored=request.stored,
            title=request.stored.title,
            published_at=request.stored.published_at,
            transcript_key=request.transcript_key,
        )
        try:
            parsed = await ParseDocument(chain, self.raw, units=self.store).run(parse)
        except (UnparsedDocumentError, UnsupportedDocumentError) as exc:
            reason = f"{type(exc).__name__}: {exc}"
            opened = await OpenManualParse(self.store).run(
                ParseFailure(document_id=parse.document_id, reason=reason)
            )
            return {"parse_failed": True, "task_id": opened.task_id}
        registered = await RegisterDocument(
            chain, rulebook, enabled=True, raw_store=self.raw, units=self.store
        ).run(RegisterRequest(parse=parse, regulator=request.regulator))
        return {
            "parse_failed": False,
            "parser_version": parsed.parser_version,
            "registered": not registered.skipped,
            "kept": registered.parser_version,
        }


@contextmanager
def listeners(app: CombinedApp) -> Iterator[tuple[httpx2.Client, httpx2.Client]]:
    public_url = f"http://{LOCALHOST}:{app.settings.mvp_public_port}"
    with (
        httpx2.Client(base_url=public_url, timeout=30.0) as public,
        httpx2.Client(base_url=app.settings.mvp_internal_url, timeout=30.0) as internal,
    ):
        yield public, internal


def ok(response: httpx2.Response, status: int = 200) -> Any:
    assert response.status_code == status, (response.status_code, response.text)
    return response.json()


def upload(internal: httpx2.Client, key: str, content: bytes, **fields: str) -> Any:
    return ok(
        internal.post(
            f"{PIPELINE}/sources/{key}/uploads",
            headers=WRITE,
            files={"file": ("document.pdf", content, "application/pdf")},
            data={"actor_id": ACTOR, "reason": "A document for the journey", **fields},
        ),
        202,
    )


async def test_a_scan_opens_a_task_and_its_transcript_registers_it() -> None:
    pipeline = Pipeline()
    services = {
        **MEMORY_SERVICES,
        "pipeline": {
            **MEMORY_SERVICES["pipeline"],
            "pipeline_knowledge_enabled": True,
            "rulebook_write_token": TOKEN,
        },
        "rulebook": {**MEMORY_SERVICES["rulebook"], "rulebook_write_token": TOKEN},
    }
    with (
        running_app(service_overrides=services, build_overrides=pipeline.overrides()) as app,
        listeners(app) as (public, internal),
    ):
        rulebook = HttpRulebook(token=TOKEN, client=internal)

        notice = upload(internal, "cbic_notifications", table_notification(), title="10/2025")
        tables = await pipeline.ingest(pipeline.ingests.started[-1], rulebook)
        assert tables == {
            "parse_failed": False,
            "parser_version": "pdf-tables@1",
            "registered": True,
            "kept": "pdf-tables@1",
        }
        stored = ok(internal.get(f"{RULEBOOK}/documents/{notice['document']['document_id']}"))
        assert (stored["parser_version"], stored["doc_type"]) == ("pdf-tables@1", "notification")
        assert any(
            clause["text"].startswith("“23. | Chennai Outer | Districts of Viluppuram")
            for clause in stored["clauses"]
        ), "the table's rows are clauses of their cells"

        uploaded = upload(
            internal, "cgst_rules", scan(), title="Example rules", external_ref="Example rules"
        )
        document_id = uploaded["document"]["document_id"]
        assert uploaded["document"]["source_url"].startswith("upload://cgst_rules/")
        failed = await pipeline.ingest(pipeline.ingests.started[-1], rulebook)
        assert failed["parse_failed"] is True
        (task,) = ok(
            internal.get(f"{PIPELINE}/tasks", params={"status": "open", "kind": "manual_parse"})
        )["items"]
        assert (task["task_id"], task["document_id"], task["source_key"]) == (
            str(failed["task_id"]),
            document_id,
            "cgst_rules",
        )
        assert "pdf@1: UnparsedDocumentError: the PDF has no text layer" in task["reason"]
        assert task["document"]["status"] == "failed"
        missing = internal.get(f"{RULEBOOK}/documents/{document_id}")
        assert missing.status_code == 404, "a document no parser reads is never registered"

        resolved = ok(
            internal.post(
                f"{PIPELINE}/tasks/{task['task_id']}/resolve",
                headers=WRITE,
                json={
                    "actor_id": ACTOR,
                    "reason": "Typed from the scan for the journey",
                    "transcript": TRANSCRIPT,
                },
            )
        )
        assert (resolved["started"], resolved["task"]["status"]) == (True, "resolved")
        start = pipeline.ingests.started[-1]
        assert start.workflow_id == resolved["workflow_id"]
        manual = await pipeline.ingest(start, rulebook)
        assert manual == {
            "parse_failed": False,
            "parser_version": "manual@1",
            "registered": True,
            "kept": "manual@1",
        }
        statute = ok(internal.get(f"{RULEBOOK}/documents/{document_id}"))
        assert (statute["doc_type"], statute["parser_version"], statute["title"]) == (
            "statute",
            "manual@1",
            "Example rules",
        )
        assert [clause["text"] for clause in statute["clauses"]] == [
            "Example chapter of the journey",
            "1. Example text of the first rule, typed by an analyst for the journey.",
            "Example item | Example rate",
            "First example item | 5%",
            "Second example item | 12%",
        ]
        record = pipeline.store.documents[DocumentId(UUID(document_id))]
        assert (record.status, record.parser_version) == (DocumentStatus.PARSED, "manual@1")

        again = upload(internal, "cgst_rules", scan())
        assert again["duplicate"] is True
        reparsed = await pipeline.ingest(pipeline.ingests.started[-1], rulebook)
        assert (reparsed["parser_version"], reparsed["kept"]) == ("manual@1", "manual@1")
        assert ok(internal.get(f"{PIPELINE}/tasks", params={"status": "open"}))["items"] == []
        assert [entry.action for entry in pipeline.store.audit] == [
            "pipeline.document.upload",
            "pipeline.document.upload",
            "pipeline.task.resolve",
            "pipeline.document.upload",
        ]
        topics = [event.topic for event in pipeline.store.events]
        assert topics.count("document.parsed") == 2, "each document once, when first parsed"

        for method, path in (
            ("GET", f"{PIPELINE}/tasks"),
            ("POST", f"{PIPELINE}/sources/cgst_rules/uploads"),
            ("POST", f"{PIPELINE}/tasks/{task['task_id']}/resolve"),
        ):
            refused = public.request(method, path, headers=WRITE)
            assert (refused.status_code, refused.json()["type"]) == (404, ROUTE_NOT_FOUND)
