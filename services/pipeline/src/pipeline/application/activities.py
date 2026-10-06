"""The ingest activities: discover a document at a source, fetch and store it, parse it into
clauses.

Each activity is an ``ActivityBase`` over the kernel's and the domain's protocols
(``SourceCatalog``, ``DocumentParser``, ``RawStore``), so the same code runs against the fakes in
tests and the real adapters in the worker. The blocking work (HTTP, the raw store, the database,
the PDF parser) runs on a thread while the activity heartbeats, so the worker's event loop never
waits on it. Inputs and outputs are pydantic models: what crosses the Temporal wire is explicit
and small.

``FetchAndStore`` (``pipeline.fetch_and_store``) fetches the bytes, keeps them in the raw store
and records the document with its document.discovered (``application.store_document``); its
output names the storage key and carries no bytes, and ``ParseDocument`` reads them back from the
raw store. ``FetchDocument`` (``pipeline.fetch_document``) is what the ingest workflow ran before
the store: it carries the bytes in ``Fetched``, and stays registered so the workflows started
before it finish on it.
"""

import asyncio
import dataclasses
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any, ClassVar, Final, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from temporalio.common import RetryPolicy

from domain_kernel.documents import (
    DiscoveredDocument,
    DocumentRef,
    ParsedDocument,
    RawDocument,
)
from domain_kernel.documents import document_id_for as kernel_document_id_for
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import DocumentId, SourceId
from domain_kernel.protocols import DocumentParser, SourceAdapter
from pipeline.application.store_document import StoreDocument, StoreRequest
from pipeline.domain.errors import RawStoreError
from pipeline.domain.ports import RawStore, SourceCatalog
from py_common.temporal import ActivityBase
from py_common.temporal.activity import DEFAULT_RETRY_POLICY

HEARTBEAT_SECONDS: Final = 10.0
SHA256_PATTERN: Final = r"^[0-9a-f]{64}$"


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DiscoverRequest(Frozen):
    source_id: UUID
    since: AwareDatetime


class Discovered(Frozen):
    source_id: UUID
    url: str = Field(min_length=1)
    external_ref: str = ""
    title: str = ""
    published_at: date | None = None


class Fetched(Frozen):
    source_id: UUID
    url: str = Field(min_length=1)
    external_ref: str = ""
    media_type: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_PATTERN)
    fetched_at: AwareDatetime
    content: bytes


class Stored(Frozen):
    """A fetched document as the raw store keeps it: the storage key, never the bytes.
    ``duplicate`` says the same bytes were stored before; ``storage_key`` is then theirs."""

    document_id: UUID
    source_id: UUID
    source_key: str = Field(min_length=1)
    regulator: str = Field(min_length=1)
    url: str = Field(min_length=1)
    external_ref: str = ""
    media_type: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_PATTERN)
    size: int = Field(ge=1)
    fetched_at: AwareDatetime
    storage_key: str = Field(min_length=1)
    raw_uri: str = Field(min_length=1)
    duplicate: bool = False


class ParseRequest(Frozen):
    """The bytes to parse: carried in ``fetched`` by the workflows started before the store,
    named by ``stored`` since."""

    document_id: UUID
    fetched: Fetched | None = None
    stored: Stored | None = None
    doc_type: str = "notification"
    title: str = ""
    published_at: date | None = None

    @model_validator(mode="after")
    def _one_source_of_bytes(self) -> Self:
        if (self.fetched is None) == (self.stored is None):
            raise ValueError("a parse request names exactly one of fetched and stored")
        return self

    @property
    def source_id(self) -> UUID:
        return self.fetched.source_id if self.fetched is not None else self._stored.source_id

    @property
    def url(self) -> str:
        return self.fetched.url if self.fetched is not None else self._stored.url

    @property
    def external_ref(self) -> str:
        if self.fetched is not None:
            return self.fetched.external_ref
        return self._stored.external_ref

    @property
    def media_type(self) -> str:
        return self.fetched.media_type if self.fetched is not None else self._stored.media_type

    @property
    def sha256(self) -> str:
        return self.fetched.sha256 if self.fetched is not None else self._stored.sha256

    @property
    def fetched_at(self) -> datetime:
        return self.fetched.fetched_at if self.fetched is not None else self._stored.fetched_at

    @property
    def raw_uri(self) -> str | None:
        return None if self.stored is None else self.stored.raw_uri

    @property
    def _stored(self) -> Stored:
        if self.stored is None:
            raise ValueError("the parse request carries its bytes")
        return self.stored


class Parsed(Frozen):
    document_id: UUID
    doc_type: str
    title: str
    language: str
    clause_count: int = Field(ge=1)
    clause_refs: list[str]


class NothingDiscoveredError(Exception):
    """The source listed nothing since the requested time."""


class UnsupportedDocumentError(Exception):
    """No parser handles this media type."""


async def on_thread[T](
    activity: ActivityBase[Any, Any], work: Callable[[], T], *, every: float = HEARTBEAT_SECONDS
) -> T:
    """``work()`` on a thread of its own, the activity heartbeating every ``every`` seconds
    until it returns."""
    running = asyncio.ensure_future(asyncio.to_thread(work))
    while not running.done():
        await asyncio.wait({running}, timeout=every)
        if not running.done():
            activity.heartbeat()
    return running.result()


def _first_listed(adapter: SourceAdapter, since: datetime) -> DiscoveredDocument | None:
    return next(iter(adapter.list_documents(since)), None)


class DiscoverDocument(ActivityBase[DiscoverRequest, Discovered]):
    """The first document the source lists since ``since``."""

    name: ClassVar[str] = "pipeline.discover_document"
    input_type: ClassVar[type[DiscoverRequest]] = DiscoverRequest
    output_type: ClassVar[type[Discovered]] = Discovered
    start_to_close: ClassVar[timedelta] = timedelta(minutes=2)
    retry_policy: ClassVar[RetryPolicy] = dataclasses.replace(
        DEFAULT_RETRY_POLICY, non_retryable_error_types=["UnknownSourceError"]
    )

    def __init__(self, sources: SourceCatalog) -> None:
        self._sources = sources

    def validate(self, input: DiscoverRequest) -> None:
        if input.since > datetime.now(input.since.tzinfo) + timedelta(days=1):
            raise ValueError("since must not be in the future")

    async def run(self, input: DiscoverRequest) -> Discovered:
        adapter = self._sources.resolve(SourceId(input.source_id)).adapter
        document = await on_thread(self, lambda: _first_listed(adapter, input.since))
        if document is None:
            raise NothingDiscoveredError(
                f"source {input.source_id} listed nothing since {input.since}"
            )
        return Discovered(
            source_id=document.ref.source_id.value,
            url=document.ref.url,
            external_ref=document.ref.external_ref,
            title=document.title,
            published_at=document.published_at,
        )


FETCH_RETRIES: Final = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=5),
    maximum_attempts=5,
    non_retryable_error_types=[
        "InvariantViolationError",
        "UnknownSourceError",
        "DisallowedByRobotsError",
    ],
)
"""A regulator site that fails or times out is tried again with backoff; an empty file, a
source nobody knows and a path robots.txt disallows are not."""


class FetchDocument(ActivityBase[Discovered, Fetched]):
    """Fetch the bytes and their digest through the adapter, and carry them back."""

    name: ClassVar[str] = "pipeline.fetch_document"
    input_type: ClassVar[type[Discovered]] = Discovered
    output_type: ClassVar[type[Fetched]] = Fetched
    start_to_close: ClassVar[timedelta] = timedelta(minutes=5)
    heartbeat_timeout: ClassVar[timedelta | None] = timedelta(minutes=1)
    retry_policy: ClassVar[RetryPolicy] = FETCH_RETRIES

    def __init__(self, sources: SourceCatalog) -> None:
        self._sources = sources

    async def run(self, input: Discovered) -> Fetched:
        adapter = self._sources.resolve(SourceId(input.source_id)).adapter
        ref = DocumentRef(SourceId(input.source_id), input.url, input.external_ref)
        raw = await on_thread(self, lambda: adapter.fetch(ref))
        self.heartbeat(raw.sha256)
        return Fetched(
            source_id=input.source_id,
            url=input.url,
            external_ref=input.external_ref,
            media_type=raw.media_type,
            sha256=raw.sha256,
            fetched_at=raw.fetched_at,
            content=raw.content,
        )

    def record(self, input: Discovered, result: Fetched) -> None:
        if len(result.content) == 0:
            raise InvariantViolationError("fetched document is empty")


class FetchAndStore(ActivityBase[Discovered, Stored]):
    """Fetch the document, keep its bytes in the raw store and record it with its
    document.discovered in one transaction; a document whose bytes are stored already is
    reported as a duplicate and nothing is written."""

    name: ClassVar[str] = "pipeline.fetch_and_store"
    input_type: ClassVar[type[Discovered]] = Discovered
    output_type: ClassVar[type[Stored]] = Stored
    start_to_close: ClassVar[timedelta] = timedelta(minutes=10)
    heartbeat_timeout: ClassVar[timedelta | None] = timedelta(minutes=1)
    retry_policy: ClassVar[RetryPolicy] = dataclasses.replace(
        FETCH_RETRIES,
        non_retryable_error_types=[
            *(FETCH_RETRIES.non_retryable_error_types or []),
            "RawObjectCorruptError",
        ],
    )

    def __init__(
        self, store: StoreDocument, *, heartbeat_seconds: float = HEARTBEAT_SECONDS
    ) -> None:
        self._store = store
        self._heartbeat_seconds = heartbeat_seconds

    async def run(self, input: Discovered) -> Stored:
        request = StoreRequest(
            source_id=SourceId(input.source_id),
            url=input.url,
            external_ref=input.external_ref,
            title=input.title,
            published_at=input.published_at,
        )
        outcome = await on_thread(
            self, lambda: self._store.run(request), every=self._heartbeat_seconds
        )
        record = outcome.record
        return Stored(
            document_id=record.document_id.value,
            source_id=outcome.source.source_id.value,
            source_key=outcome.source.definition.key,
            regulator=outcome.source.definition.regulator,
            url=outcome.url,
            external_ref=outcome.external_ref,
            media_type=outcome.media_type,
            sha256=record.sha256,
            size=record.size,
            fetched_at=outcome.fetched_at,
            storage_key=record.storage_key,
            raw_uri=outcome.raw_uri,
            duplicate=outcome.duplicate,
        )


class ParseDocument(ActivityBase[ParseRequest, Parsed]):
    """Split the document's bytes into clauses with stable references."""

    name: ClassVar[str] = "pipeline.parse_document"
    input_type: ClassVar[type[ParseRequest]] = ParseRequest
    output_type: ClassVar[type[Parsed]] = Parsed
    start_to_close: ClassVar[timedelta] = timedelta(minutes=10)
    retry_policy: ClassVar[RetryPolicy] = RetryPolicy(
        maximum_attempts=2,
        non_retryable_error_types=[
            "UnsupportedDocumentError",
            "RawObjectMissingError",
            "RawObjectCorruptError",
        ],
    )

    def __init__(self, parser: DocumentParser, raw_store: RawStore | None = None) -> None:
        self._parser = parser
        self._raw = raw_store

    async def run(self, input: ParseRequest) -> Parsed:
        parsed = await on_thread(self, lambda: parse_request(self._parser, input, self._raw))
        return Parsed(
            document_id=parsed.document_id.value,
            doc_type=parsed.doc_type.value,
            title=parsed.title,
            language=parsed.language,
            clause_count=len(parsed.clauses),
            clause_refs=[clause.clause_ref for clause in parsed.clauses],
        )


def raw_document_of(request: ParseRequest, raw_store: RawStore | None) -> RawDocument:
    """The bytes the request names, with where they came from: carried in ``fetched``, or read
    from the raw store by ``stored.storage_key``."""
    if request.fetched is not None:
        content = request.fetched.content
    elif request.stored is not None and raw_store is not None:
        content = raw_store.get(request.stored.storage_key)
    else:
        raise RawStoreError("this worker has no raw store to read the stored document from")
    return RawDocument(
        ref=DocumentRef(SourceId(request.source_id), request.url, request.external_ref),
        content=content,
        media_type=request.media_type,
        sha256=request.sha256,
        fetched_at=request.fetched_at,
    )


def parse_request(
    parser: DocumentParser, request: ParseRequest, raw_store: RawStore | None
) -> ParsedDocument:
    """Parse the bytes the request names; ``UnsupportedDocumentError`` when the parser cannot
    read them."""
    raw = raw_document_of(request, raw_store)
    if not parser.supports(raw):
        raise UnsupportedDocumentError(f"no parser for {raw.media_type}")
    return parser.parse(raw)


def document_id_for(fetched: Fetched) -> DocumentId:
    """Deterministic per digest: a re-run of the workflow parses the same document id."""
    return kernel_document_id_for(fetched.sha256)
