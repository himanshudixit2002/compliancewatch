"""Test doubles for adapter tests and demos: recorded sources, a scripted model, a rulebook.

``FixtureTransport`` maps a request to a file under ``tests/fixtures`` (or a literal body) and
answers 404 for anything else, so a test that reaches an unrecorded URL fails loudly instead of
touching the network. Routes are exact matches on method and URL; the CBIC listing routes also
insist on the token header the real site wants. ``MemoryRulebook`` stands in for the rulebook's
write API with the same rules: ids from the kernel, a different parse of stored bytes refused.
"""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import httpx2

from domain_kernel.documents import ParsedDocument, clause_id_for
from domain_kernel.ids import DocumentId
from domain_kernel.llm import CompletionRequest, CompletionResponse
from pipeline.domain.errors import RulebookConflictError
from pipeline.domain.knowledge import DocumentRecord, RegisteredDocument

Responder = Callable[[httpx2.Request], httpx2.Response]

CBIC = "https://taxinformation.cbic.gov.in"
CBIC_NOTIFICATIONS = f"{CBIC}/api/cbic-notification-msts/fetchNotificationByYearAndCategory"
CBIC_CIRCULARS = f"{CBIC}/api/cbic-circular-msts/fetchCircularByYearCategory"
GSTCOUNCIL = "https://gstcouncil.gov.in"
GSTN = "https://www.gst.gov.in"
MAHAGST = "https://mahagst.gov.in"
EMPTY_TABLE = "<html><body><table><tbody></tbody></table></body></html>"
CBIC_PDF = f"{CBIC}/content/pdf/tax_repository/gst/notifications/"
RECORDED_NOTIFICATIONS: Mapping[str, str] = {
    "01/2026-Central Tax": "gst-ct-01-2026.pdf",
    "17/2025-Central Tax": "gst-ct-17-2025.pdf",
    "15/2025-Central Tax": "centaltax-15-2025.pdf",
    "10/2025-Central Tax": "gst-ct-10-2025.pdf",
    "13/2024-Central Tax": "central-tax-13-2024-11072024.pdf",
}
"""The CBIC notifications recorded in English, by number, with the file name under ``CBIC_PDF``;
the fixture is ``cbic/<file name>.json``. 01/2026 is also recorded in Hindi."""


@dataclass
class FixtureTransport(httpx2.BaseTransport):
    fixtures: Path
    routes: dict[tuple[str, str], Responder] = field(default_factory=dict)
    requests: list[httpx2.Request] = field(default_factory=list)

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        responder = self.routes.get((request.method, str(request.url)))
        if responder is None:
            return httpx2.Response(404, text=f"unrecorded: {request.method} {request.url}")
        return responder(request)

    def file(self, method: str, url: str, relative: str, media_type: str) -> None:
        content = (self.fixtures / relative).read_bytes()
        self.routes[(method, url)] = lambda _: httpx2.Response(
            200, content=content, headers={"content-type": media_type}
        )

    def body(
        self, method: str, url: str, content: bytes | str, media_type: str, status: int = 200
    ) -> None:
        data = content.encode("utf-8") if isinstance(content, str) else content
        self.routes[(method, url)] = lambda _: httpx2.Response(
            status, content=data, headers={"content-type": media_type}
        )

    def cbic_listing(self, url: str, relative: str | None) -> None:
        """A listing page that wants the token header; ``None`` records the empty last page."""
        content = b"[]" if relative is None else (self.fixtures / relative).read_bytes()

        def respond(request: httpx2.Request) -> httpx2.Response:
            if not request.headers.get("Authorization1", "").startswith("homeToken "):
                return httpx2.Response(401, json={"title": "Unauthorized"})
            return httpx2.Response(
                200, content=content, headers={"content-type": "application/json"}
            )

        self.routes[("GET", url)] = respond


def recorded_sources(fixtures: Path) -> FixtureTransport:
    """Every recorded source wired up as the sites answered on 2026-09-28."""
    transport = FixtureTransport(fixtures)
    transport.body(
        "POST", f"{CBIC}/api/authenticate-token", json.dumps({"id_token": "t"}), "application/json"
    )
    query = "&size=10&taxId=1000001&category="
    listing = f"{CBIC_NOTIFICATIONS}?year={{year}}&page={{page}}{query}Central%20Tax"
    transport.cbic_listing(listing.format(year=2026, page=0), "cbic/notifications-2026-p0.json")
    transport.cbic_listing(listing.format(year=2026, page=1), None)
    transport.cbic_listing(listing.format(year=2025, page=0), "cbic/notifications-2025-p0.json")
    transport.cbic_listing(listing.format(year=2025, page=1), "cbic/notifications-2025-p1.json")
    transport.cbic_listing(listing.format(year=2025, page=2), None)
    circulars = f"{CBIC_CIRCULARS}?year={{year}}&page={{page}}{query}Circulars%20CGST"
    transport.cbic_listing(circulars.format(year=2026, page=0), "cbic/circulars-2026-p0.json")
    transport.cbic_listing(circulars.format(year=2026, page=1), None)
    for name in ("gst-ct-01h-2026.pdf", *RECORDED_NOTIFICATIONS.values()):
        transport.file("GET", CBIC_PDF + name, f"cbic/{name}.json", "application/json")
    archive = f"{GSTCOUNCIL}/archive-press-release?page={{page}}"
    transport.file(
        "GET", archive.format(page=0), "gstcouncil/archive-press-release-page0.html", "text/html"
    )
    transport.file(
        "GET", archive.format(page=1), "gstcouncil/archive-press-release-page1.html", "text/html"
    )
    transport.body("GET", archive.format(page=2), EMPTY_TABLE, "text/html")
    transport.file(
        "GET",
        f"{GSTCOUNCIL}/sites/default/files/2025-09/faq.pdf",
        "gstcouncil/faq-56th-council.pdf",
        "application/pdf",
    )
    transport.file(
        "GET", f"{GSTN}/fomessage/newsupdates", "gstn/newsupdates.json", "application/json"
    )
    transport.file("GET", f"{MAHAGST}/en/notifications", "mahagst/notifications.html", "text/html")
    return transport


class ScriptedProvider:
    """An ``LLMProvider`` that answers from a script: the golden label for a document id, or one
    text for everything. The harness uses it to prove the scoring; it is not a model."""

    MODEL = "scripted/golden"

    def __init__(self, answers: Mapping[str, str] | None = None, default: str = "{}") -> None:
        self._answers = dict(answers or {})
        self._default = default
        self.requests: list[CompletionRequest] = []

    def complete(self, req: CompletionRequest) -> CompletionResponse:
        self.requests.append(req)
        text = self._answers.get(req.metadata.get("document_id", ""), self._default)
        return CompletionResponse(text=text, model=self.MODEL, input_tokens=0, output_tokens=0)


class MemoryRulebook:
    """A ``KnowledgeSink`` in memory. ``records`` keeps every stored document by id."""

    def __init__(self) -> None:
        self.records: dict[DocumentId, DocumentRecord] = {}
        self.calls = 0

    def register_document(self, record: DocumentRecord) -> RegisteredDocument:
        self.calls += 1
        document = record.document
        stored = self.records.get(document.document_id)
        if stored is not None and _clauses(stored.document) != _clauses(document):
            raise RulebookConflictError(f"409: document {document.document_id} differs")
        if stored is None:
            self.records[document.document_id] = record
        return RegisteredDocument(
            document_id=document.document_id,
            created=stored is None,
            clause_ids={
                clause.clause_ref: clause_id_for(document.document_id, clause.clause_ref)
                for clause in document.clauses
            },
        )


def _clauses(document: ParsedDocument) -> list[tuple[str, str, int | None]]:
    return [(c.clause_ref, c.text, c.page) for c in document.clauses]
