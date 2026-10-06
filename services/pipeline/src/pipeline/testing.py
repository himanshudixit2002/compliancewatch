"""Test doubles for adapter tests and demos: recorded sources, scripted models (by document, or
answers in turn) and an embedder, a rulebook, an S3 endpoint, a recorded adapter type and a
crawl starter.

``FixtureTransport`` maps a request to a file under ``tests/fixtures`` (or a literal body) and
answers 404 for anything else, so a test that reaches an unrecorded URL fails loudly instead of
touching the network. Routes are exact matches on method and URL; the CBIC listing routes also
insist on the token header the real site wants. ``MemoryRulebook`` stands in for the rulebook's
write API with the same rules: ids from the kernel, the first parse of a document kept (another
parser version's parse is answered with it, the same version's different parse refused), a
clause's first vector from a model kept. ``StubS3`` answers the raw store's S3 calls the way
S3 does, signature checks included, from a dict. ``sample_activities`` are the worker's
activities on the sample notification's source, the plain-text parser and memory stores.

The crawl's tests and demos read recorded sources only: ``RECORDED_TYPE`` is an adapter type,
``recorded``, whose adapter lists the CBIC notifications its ``numbers`` parameter names from
the recorded listing files (whatever today's date) and fetches their recorded PDFs through the
client it is given, the fixture transport of ``recorded_sources``; ``recorded_types()`` are the
registry's types with it. ``MemoryCrawls`` and ``MemoryIngests`` are a crawl and an ingest starter
that record what they would start and refuse an id they have seen, as Temporal does.
``pipeline_settings`` are the app's settings for tests: memory stores and the shared write token
``WRITE_TOKEN``. ``LockRace`` lets another request in just before a unit of work opens, as a
request that holds a row lock commits while this one waits for it.
"""

import hashlib
import json
import math
import re
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Self
from urllib.parse import unquote, urlsplit

import httpx2
from pydantic import Field, model_validator

from domain_kernel.documents import (
    DiscoveredDocument,
    DocumentRef,
    DocumentType,
    ParsedDocument,
    RawDocument,
    clause_id_for,
)
from domain_kernel.ids import ClauseId, DocumentId, SourceId
from domain_kernel.knowledge import EntityType
from domain_kernel.llm import CompletionRequest, CompletionResponse
from domain_kernel.vectors import EMBEDDING_DIMS, Vector
from pipeline.domain.embedding import (
    ClauseToEmbed,
    ClauseVector,
    EmbeddingBatch,
    EmbeddingsStored,
)
from pipeline.domain.errors import RulebookConflictError, RulebookRejectedError
from pipeline.domain.knowledge import (
    AlignmentReport,
    DocumentRecord,
    MentionSubmission,
    RegisteredDocument,
    RelationSubmission,
    RuleKey,
    StagingReport,
)
from pipeline.domain.ports import CrawlStart, IngestStart
from pipeline.domain.repository import UnitOfWork, UnitOfWorkFactory
from pipeline.infrastructure.adapters._shared import on_or_after, parse_iso_date
from pipeline.infrastructure.adapters.cbic import CbicAdapter
from pipeline.infrastructure.adapters.registry import ADAPTER_TYPES, AdapterType, Parameters
from pipeline.infrastructure.fakes import FakePlainTextParser, sample_catalog
from pipeline.infrastructure.http import ClientConfig, PoliteClient
from pipeline.infrastructure.memory import MemoryStore
from pipeline.infrastructure.raw_store import MemoryRawStore
from pipeline.infrastructure.s3 import S3Credentials, sign
from pipeline.settings import PipelineSettings
from py_common.temporal import ActivityBase

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
    """An ``LLMProvider`` that answers from a script: the golden label for a document id (or for
    a document id and a prompt, ``(document_id, "name@version")``), or one text for everything.
    The harness uses it to prove the scoring; it is not a model."""

    MODEL = "scripted/golden"

    def __init__(
        self, answers: Mapping[str | tuple[str, str], str] | None = None, default: str = "{}"
    ) -> None:
        self._answers = dict(answers or {})
        self._default = default
        self.requests: list[CompletionRequest] = []

    def complete(self, req: CompletionRequest) -> CompletionResponse:
        self.requests.append(req)
        document_id = req.metadata.get("document_id", "")
        text = self._answers.get(
            (document_id, req.prompt_version), self._answers.get(document_id, self._default)
        )
        return CompletionResponse(text=text, model=self.MODEL, input_tokens=0, output_tokens=0)


class AnswersInTurn:
    """An ``LLMProvider`` that gives its answers one after another, raising any exception among
    them (a used-up budget, an outage): for the rule extraction's retries in tests. Every
    request is kept in ``requests``."""

    MODEL = "scripted/turns"

    def __init__(self, *answers: str | Exception) -> None:
        self.answers = list(answers)
        self.requests: list[CompletionRequest] = []

    def complete(self, req: CompletionRequest) -> CompletionResponse:
        self.requests.append(req)
        if not self.answers:
            raise AssertionError(f"no answer left for request {len(self.requests)}")
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return CompletionResponse(text=answer, model=self.MODEL, input_tokens=0, output_tokens=0)


def hash_vector(text: str, dims: int = EMBEDDING_DIMS) -> Vector:
    """A unit vector of ``dims`` components from the SHA-256 of ``text`` in counter mode:
    deterministic, and the same text always gets the same vector. Not a model: similar texts do
    not get similar vectors."""
    stream = b"".join(
        hashlib.sha256(f"{block}:{text}".encode()).digest() for block in range(dims // 32 + 1)
    )
    raw = [byte / 127.5 - 1.0 for byte in stream[:dims]]
    norm = math.sqrt(sum(x * x for x in raw)) or 1.0
    return tuple(x / norm for x in raw)


class ScriptedEmbedder:
    """An ``Embedder`` that answers every text with its ``hash_vector``, served by ``model`` (or
    by the override it is asked for, as the gateway would). ``dims`` other than
    ``EMBEDDING_DIMS`` stands in for a misconfigured route. Every call is kept in
    ``requests``."""

    MODEL = "scripted/hash-512"

    def __init__(self, *, model: str = MODEL, dims: int = EMBEDDING_DIMS) -> None:
        self.model = model
        self.dims = dims
        self.requests: list[tuple[tuple[str, ...], str | None, dict[str, str]]] = []

    def embed(
        self,
        inputs: Sequence[str],
        *,
        model: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> EmbeddingBatch:
        texts = tuple(inputs)
        self.requests.append((texts, model, dict(metadata or {})))
        return EmbeddingBatch(
            model=model or self.model,
            dims=self.dims,
            vectors=tuple(hash_vector(text, self.dims) for text in texts),
            input_tokens=sum(len(text.split()) for text in texts),
        )


class MemoryRulebook:
    """The rulebook's write and read API in memory: a ``KnowledgeSink``, a ``RulebookReader``
    and a ``ClauseIndexSink``. ``records`` keeps every stored document by id; mentions resolve
    when their (type, name) is in ``entities``; submissions are kept for tests to read, and
    vectors in ``embeddings`` by clause id and model."""

    def __init__(
        self,
        *,
        entities: set[tuple[EntityType, str]] | None = None,
        rules: tuple[RuleKey, ...] = (),
    ) -> None:
        self.records: dict[DocumentId, DocumentRecord] = {}
        self.entities = entities or set()
        self.rules = rules
        self.mentions: list[MentionSubmission] = []
        self.relations: list[RelationSubmission] = []
        self.embeddings: dict[tuple[ClauseId, str], Vector] = {}
        self.calls = 0

    def register_document(self, record: DocumentRecord) -> RegisteredDocument:
        self.calls += 1
        document = record.document
        stored = self.records.get(document.document_id)
        if (
            stored is not None
            and stored.document.parser_version == document.parser_version
            and _clauses(stored.document) != _clauses(document)
        ):
            raise RulebookConflictError(f"409: document {document.document_id} differs")
        if stored is None:
            self.records[document.document_id] = record
        kept = (stored or record).document
        return RegisteredDocument(
            document_id=document.document_id,
            created=stored is None,
            clause_ids={
                clause.clause_ref: clause_id_for(document.document_id, clause.clause_ref)
                for clause in kept.clauses
            },
            parser_version=kept.parser_version,
        )

    def submit_mentions(self, submission: MentionSubmission) -> AlignmentReport:
        document = self.parsed_document(submission.document_id)
        texts = {clause.clause_ref: clause.text for clause in document.clauses}
        for mention in submission.mentions:
            if texts.get(mention.clause_ref, "")[mention.span_start : mention.span_end] != (
                mention.text
            ):
                raise RulebookRejectedError(f"422: span of {mention.text!r} does not match")
        repeat = submission in self.mentions
        self.mentions.append(submission)
        aligned = sum(
            (m.entity_type, m.proposed_name) in self.entities for m in submission.mentions
        )
        if repeat:
            return AlignmentReport(0, 0, len(submission.mentions))
        return AlignmentReport(aligned, len(submission.mentions) - aligned, 0)

    def submit_relations(self, submission: RelationSubmission) -> StagingReport:
        self.parsed_document(submission.document_id)
        repeat = submission in self.relations
        self.relations.append(submission)
        count = len(submission.candidates)
        return StagingReport(0, count) if repeat else StagingReport(count, 0)

    def parsed_document(self, document_id: DocumentId) -> ParsedDocument:
        record = self.records.get(document_id)
        if record is None:
            raise RulebookRejectedError(f"404: document {document_id} is not stored")
        return record.document

    def known_rules(self) -> tuple[RuleKey, ...]:
        return self.rules

    def unembedded_clauses(
        self,
        model: str,
        *,
        document_id: DocumentId | None = None,
        limit: int = 64,
        after: ClauseId | None = None,
    ) -> tuple[ClauseToEmbed, ...]:
        found = sorted(
            (
                clause
                for record in self.records.values()
                if document_id is None or record.document.document_id == document_id
                for clause in _to_embed(record)
                if (clause.clause_id, model) not in self.embeddings
                and (after is None or clause.clause_id.value > after.value)
            ),
            key=lambda clause: clause.clause_id.value,
        )
        return tuple(found[:limit])

    def put_embeddings(
        self, model: str, dims: int, items: Sequence[ClauseVector]
    ) -> EmbeddingsStored:
        if dims != EMBEDDING_DIMS or any(len(item.vector) != dims for item in items):
            raise RulebookRejectedError(f"422: vectors must have {EMBEDDING_DIMS} components")
        known = {
            clause_id_for(record.document.document_id, clause.clause_ref)
            for record in self.records.values()
            for clause in record.document.clauses
        }
        unknown = [str(item.clause_id) for item in items if item.clause_id not in known]
        if unknown:
            raise RulebookRejectedError(f"422: clauses {unknown} are not stored")
        stored = 0
        for item in items:
            if (item.clause_id, model) not in self.embeddings:
                self.embeddings[item.clause_id, model] = item.vector
                stored += 1
        return EmbeddingsStored(stored=stored, unchanged=len(items) - stored)


def _clauses(document: ParsedDocument) -> list[tuple[str, str, int | None]]:
    return [(c.clause_ref, c.text, c.page) for c in document.clauses]


def _to_embed(record: DocumentRecord) -> list[ClauseToEmbed]:
    document = record.document
    return [
        ClauseToEmbed(
            clause_id=clause_id_for(document.document_id, clause.clause_ref),
            document_id=document.document_id,
            clause_ref=clause.clause_ref,
            text=clause.text,
            regulator=record.regulator,
            doc_type=document.doc_type,
            external_ref=record.external_ref,
            title=document.title,
            published_at=document.published_at,
        )
        for clause in document.clauses
    ]


_AUTHORIZATION = re.compile(
    r"AWS4-HMAC-SHA256 Credential=(?P<key>[^/]+)/(?P<day>\d{8})/(?P<region>[^/]+)"
    r"/s3/aws4_request, SignedHeaders=(?P<names>[a-z0-9;-]+), "
    r"Signature=(?P<signature>[0-9a-f]{64})"
)
_FROM_SIGNATURE = frozenset({"x-amz-date", "x-amz-content-sha256", "x-amz-security-token"})


@dataclass
class StubS3:
    """An S3 endpoint for tests, as the handler of ``httpx2.MockTransport(stub)``: HEAD, PUT and
    GET of the objects of one bucket, path-style or virtual-hosted. It checks each request the
    way S3 does: the body against ``x-amz-content-sha256``, every ``x-amz-*`` header signed, and
    the signature over the headers the request names, with the same credentials. A PUT with
    ``If-None-Match: *`` of a key that exists gets 412. ``objects`` keeps each object's bytes
    and the headers it was written with, ``requests`` every request; ``fail`` answers the next
    requests with these statuses before anything else."""

    bucket: str
    credentials: S3Credentials
    region: str = "ap-south-1"
    objects: dict[str, tuple[bytes, dict[str, str]]] = field(default_factory=dict)
    requests: list[httpx2.Request] = field(default_factory=list)
    fail: list[int] = field(default_factory=list)

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self)

    def methods(self) -> list[str]:
        return [request.method for request in self.requests]

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if self.fail:
            return _s3_error(self.fail.pop(0), "InternalError")
        key = self._key(request)
        if key is None:
            return _s3_error(404, "NoSuchBucket")
        body = request.read()
        if hashlib.sha256(body).hexdigest() != request.headers.get("x-amz-content-sha256"):
            return _s3_error(400, "XAmzContentSHA256Mismatch")
        if not self._signed(request):
            return _s3_error(403, "SignatureDoesNotMatch")
        stored = self.objects.get(key)
        if request.method == "PUT":
            if stored is not None and request.headers.get("if-none-match") == "*":
                return _s3_error(412, "PreconditionFailed")
            kept = {
                name: value
                for name, value in request.headers.items()
                if name == "content-type" or name.startswith("x-amz-server-side-encryption")
            }
            self.objects[key] = (body, kept)
            return httpx2.Response(200)
        if stored is None:
            return _s3_error(404, "NoSuchKey") if request.method == "GET" else httpx2.Response(404)
        if request.method == "HEAD":
            return httpx2.Response(200, headers={"content-length": str(len(stored[0]))})
        if request.method == "GET":
            return httpx2.Response(200, content=stored[0], headers=stored[1])
        return _s3_error(405, "MethodNotAllowed")

    def _key(self, request: httpx2.Request) -> str | None:
        host, path = request.url.host, unquote(urlsplit(str(request.url)).path)
        if host.startswith(f"{self.bucket}.s3."):
            return path.removeprefix("/")
        bucket, _, key = path.removeprefix("/").partition("/")
        return key if bucket == self.bucket and key else None

    def _signed(self, request: httpx2.Request) -> bool:
        found = _AUTHORIZATION.fullmatch(request.headers.get("authorization", ""))
        if found is None or found.group("key") != self.credentials.access_key_id:
            return False
        names = found.group("names").split(";")
        if any(name.startswith("x-amz-") and name not in names for name in request.headers):
            return False
        headers = {name: request.headers[name] for name in names if name not in _FROM_SIGNATURE}
        moment = datetime.strptime(request.headers["x-amz-date"], "%Y%m%dT%H%M%SZ")
        expected = sign(
            request.method,
            str(request.url),
            headers,
            request.headers["x-amz-content-sha256"],
            self.credentials,
            self.region,
            moment.replace(tzinfo=UTC),
        )
        return expected["authorization"] == request.headers["authorization"]


def _s3_error(status: int, code: str) -> httpx2.Response:
    body = f'<?xml version="1.0" encoding="UTF-8"?><Error><Code>{code}</Code></Error>'
    return httpx2.Response(status, text=body, headers={"content-type": "application/xml"})


def sample_activities(
    settings: PipelineSettings | None = None,
    *,
    units: UnitOfWorkFactory | None = None,
    raw_store: MemoryRawStore | None = None,
    **overrides: Any,
) -> list[ActivityBase[Any, Any]]:
    """``pipeline.worker.activities`` on the sample notification's source (``UUID(int=1)``),
    the plain-text parser and memory stores; pass ``units`` and ``raw_store`` to read them."""
    # Imported here: the eval harness imports this module at run time and needs none of the
    # worker's wiring.
    from pipeline.worker import activities

    return activities(
        settings,
        sources=sample_catalog(),
        parser=FakePlainTextParser(),
        units=units or MemoryStore(),
        raw_store=raw_store or MemoryRawStore(),
        **overrides,
    )


FIXTURES: Final = Path(__file__).resolve().parents[2] / "tests" / "fixtures"
"""The recorded responses, beside the service's sources (not in the image)."""
WRITE_TOKEN: Final = "test-write-token"
"""The shared write token ``pipeline_settings`` configures; send it as ``x-cw-write-token``."""
RECORDED_LISTINGS: Final = (
    "cbic/notifications-2026-p0.json",
    "cbic/notifications-2025-p0.json",
    "cbic/notifications-2025-p1.json",
)
"""The recorded CBIC notification listings, newest first."""


def pipeline_settings(**overrides: Any) -> PipelineSettings:
    """Settings that ignore the repo ``.env``: memory stores and ``WRITE_TOKEN``."""
    values: dict[str, Any] = {
        "_env_file": None,
        "service_name": "pipeline",
        "pipeline_store": "memory",
        "pipeline_raw_store": "memory",
        "rulebook_write_token": WRITE_TOKEN,
    }
    values.update(overrides)
    return PipelineSettings(**values)


def recorded_client(fixtures: Path = FIXTURES) -> PoliteClient:
    """A polite client over ``recorded_sources``: no delay, no robots.txt, no network."""
    return PoliteClient(
        ClientConfig(min_delay_seconds=0, respect_robots=False),
        transport=recorded_sources(fixtures),
        sleep=lambda _: None,
    )


class RecordedParameters(Parameters):
    """The recorded CBIC notifications the source lists, by number (``01/2026-Central Tax``);
    each must have its PDF recorded (``RECORDED_NOTIFICATIONS``)."""

    numbers: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _recorded(self) -> Self:
        missing = [number for number in self.numbers if number not in RECORDED_NOTIFICATIONS]
        if missing:
            raise ValueError(f"no recorded PDF for {', '.join(missing)}")
        return self


class RecordedAdapter:
    """Lists the named notifications from the recorded listing files, newest first, those
    published since ``since``; fetches them as the CBIC adapter does, through ``client``."""

    def __init__(
        self,
        client: PoliteClient,
        source_id: SourceId,
        numbers: Sequence[str],
        *,
        fixtures: Path = FIXTURES,
    ) -> None:
        self._cbic = CbicAdapter(client, source_id, listing="notifications", category="Central Tax")
        self._source_id = source_id
        self._items = [
            item
            for item in _recorded_items(fixtures)
            if str(item.get("notificationNo", "")) in set(numbers)
        ]

    def list_documents(self, since: datetime) -> Iterable[DiscoveredDocument]:
        for item in self._items:
            published = parse_iso_date(item.get("notificationDt"))
            if not on_or_after(published, since):
                continue
            path = str(item.get("docFilePath", "")).replace("\\", "/")
            yield DiscoveredDocument(
                ref=DocumentRef(
                    self._source_id,
                    f"{CBIC}/content/pdf/{path}",
                    external_ref=str(item["notificationNo"]),
                ),
                title=str(item.get("notificationName", "")).strip(),
                published_at=published,
            )

    def fetch(self, ref: DocumentRef) -> RawDocument:
        return self._cbic.fetch(ref)


def _recorded_items(fixtures: Path) -> Iterator[Mapping[str, Any]]:
    for relative in RECORDED_LISTINGS:
        items = json.loads((fixtures / relative).read_text(encoding="utf-8"))
        yield from (item for item in items if isinstance(item, Mapping))


def _recorded(client: PoliteClient, source_id: SourceId, parameters: Any) -> RecordedAdapter:
    return RecordedAdapter(client, source_id, parameters.numbers)


RECORDED_TYPE: Final = AdapterType(
    "recorded",
    "CBIC",
    "taxinformation.cbic.gov.in",
    RecordedParameters,
    _recorded,
    lambda _: DocumentType.NOTIFICATION,
)
"""An adapter type over the recorded CBIC notifications, for tests and demos only."""


def recorded_types() -> dict[str, AdapterType]:
    """The registry's adapter types and ``recorded``."""
    return {**ADAPTER_TYPES, RECORDED_TYPE.name: RECORDED_TYPE}


@dataclass
class MemoryCrawls:
    """A ``CrawlStarter`` that keeps what it starts and refuses an id it has seen, as Temporal's
    REJECT_DUPLICATE does; ``fail`` makes the next start raise it."""

    started: list[CrawlStart] = field(default_factory=list)
    fail: Exception | None = None

    def start(self, start: CrawlStart) -> bool:
        if self.fail is not None:
            error, self.fail = self.fail, None
            raise error
        if any(seen.workflow_id == start.workflow_id for seen in self.started):
            return False
        self.started.append(start)
        return True


@dataclass
class MemoryIngests:
    """An ``IngestStarter`` that keeps what it starts and applies Temporal's id reuse policies:
    a start of an id it has seen is refused while that workflow runs or once it completed
    (ALLOW_DUPLICATE_FAILED_ONLY), and, for a start that uses its id ``once``
    (REJECT_DUPLICATE), whatever became of it; only a workflow that failed may run again.
    ``fail`` makes the next start raise it. A workflow it started runs until ``finish`` ends it
    completed or ``fail_runs`` ends it failed (every one, without ids); ``running_ids`` names
    more that run (a crawl's ingest, an extraction), and ``running_fails`` makes the next
    ``running`` raise it."""

    started: list[IngestStart] = field(default_factory=list)
    fail: Exception | None = None
    finished: set[str] = field(default_factory=set)
    failed: set[str] = field(default_factory=set)
    running_ids: set[str] = field(default_factory=set)
    running_fails: Exception | None = None
    asked: list[frozenset[str]] = field(default_factory=list)

    def start(self, start: IngestStart) -> bool:
        if self.fail is not None:
            error, self.fail = self.fail, None
            raise error
        workflow_id = start.workflow_id
        seen = any(found.workflow_id == workflow_id for found in self.started)
        if seen and (start.once or workflow_id not in self.failed):
            return False
        self.finished.discard(workflow_id)
        self.failed.discard(workflow_id)
        self.started.append(start)
        return True

    def running(self, workflow_ids: Collection[str]) -> frozenset[str]:
        if self.running_fails is not None:
            error, self.running_fails = self.running_fails, None
            raise error
        asked = frozenset(workflow_ids)
        self.asked.append(asked)
        mine = {start.workflow_id for start in self.started} - self.finished
        return asked & (mine | self.running_ids)

    def finish(self, *workflow_ids: str) -> None:
        """The workflows of these ids completed; with none, every one started so far."""
        ended = set(workflow_ids or (start.workflow_id for start in self.started))
        self.finished |= ended
        self.failed -= ended

    def fail_runs(self, *workflow_ids: str) -> None:
        """The workflows of these ids failed (or timed out, or were terminated); with none,
        every one started so far."""
        ended = set(workflow_ids or (start.workflow_id for start in self.started))
        self.finished |= ended
        self.failed |= ended


class LockRace:
    """The memory store's units of work, letting another request in once: what ``let_in``
    names runs, and commits, just before the ``before``-th unit opened from then on, as a request
    that took a row lock first commits while this one waits for the lock. A resolution opens its
    second unit to lock the task."""

    def __init__(self, store: MemoryStore) -> None:
        self.store = store
        self._meanwhile: Callable[[], object] | None = None
        self._left = 0

    def let_in(self, meanwhile: Callable[[], object], *, before: int) -> None:
        self._meanwhile, self._left = meanwhile, before

    def __call__(self) -> AbstractContextManager[UnitOfWork]:
        if self._meanwhile is not None:
            self._left -= 1
            if self._left == 0:
                meanwhile, self._meanwhile = self._meanwhile, None
                meanwhile()
        return self.store()
