"""The ingest activities: discover a document at a source, fetch it, parse it into clauses.

Each activity is an ``ActivityBase`` over the kernel protocols (``SourceAdapter``,
``DocumentParser``), so the same code runs against the fakes in tests and the real adapters
later. Inputs and outputs are pydantic models: what crosses the Temporal wire is explicit and
small. The sample carries the fetched bytes in ``Fetched``; the real pipeline stores the raw
file and carries its URI.
"""

from datetime import date, datetime, timedelta
from typing import ClassVar
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from temporalio.common import RetryPolicy

from domain_kernel.documents import DocumentRef, RawDocument
from domain_kernel.documents import document_id_for as kernel_document_id_for
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import DocumentId, SourceId
from domain_kernel.protocols import DocumentParser, SourceAdapter
from py_common.temporal import ActivityBase


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
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fetched_at: AwareDatetime
    content: bytes


class ParseRequest(Frozen):
    document_id: UUID
    fetched: Fetched
    doc_type: str = "notification"
    title: str = ""
    published_at: date | None = None


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


class DiscoverDocument(ActivityBase[DiscoverRequest, Discovered]):
    """The first document the source lists since ``since``."""

    name: ClassVar[str] = "pipeline.discover_document"
    input_type: ClassVar[type[DiscoverRequest]] = DiscoverRequest
    output_type: ClassVar[type[Discovered]] = Discovered
    start_to_close: ClassVar[timedelta] = timedelta(minutes=2)

    def __init__(self, adapter: SourceAdapter) -> None:
        self._adapter = adapter

    def validate(self, input: DiscoverRequest) -> None:
        if input.since > datetime.now(input.since.tzinfo) + timedelta(days=1):
            raise ValueError("since must not be in the future")

    async def run(self, input: DiscoverRequest) -> Discovered:
        for document in self._adapter.list_documents(input.since):
            self.heartbeat(document.ref.url)
            return Discovered(
                source_id=document.ref.source_id.value,
                url=document.ref.url,
                external_ref=document.ref.external_ref,
                title=document.title,
                published_at=document.published_at,
            )
        raise NothingDiscoveredError(f"source {input.source_id} listed nothing since {input.since}")


class FetchDocument(ActivityBase[Discovered, Fetched]):
    """Fetch the bytes and their digest through the adapter."""

    name: ClassVar[str] = "pipeline.fetch_document"
    input_type: ClassVar[type[Discovered]] = Discovered
    output_type: ClassVar[type[Fetched]] = Fetched
    start_to_close: ClassVar[timedelta] = timedelta(minutes=5)
    heartbeat_timeout: ClassVar[timedelta | None] = timedelta(minutes=1)
    retry_policy: ClassVar[RetryPolicy] = RetryPolicy(
        initial_interval=timedelta(seconds=5),
        backoff_coefficient=2.0,
        maximum_interval=timedelta(minutes=5),
        maximum_attempts=5,
        non_retryable_error_types=["InvariantViolationError"],
    )

    def __init__(self, adapter: SourceAdapter) -> None:
        self._adapter = adapter

    async def run(self, input: Discovered) -> Fetched:
        ref = DocumentRef(SourceId(input.source_id), input.url, input.external_ref)
        raw = self._adapter.fetch(ref)
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


class ParseDocument(ActivityBase[ParseRequest, Parsed]):
    """Split the fetched bytes into clauses with stable references."""

    name: ClassVar[str] = "pipeline.parse_document"
    input_type: ClassVar[type[ParseRequest]] = ParseRequest
    output_type: ClassVar[type[Parsed]] = Parsed
    start_to_close: ClassVar[timedelta] = timedelta(minutes=10)
    retry_policy: ClassVar[RetryPolicy] = RetryPolicy(
        maximum_attempts=2, non_retryable_error_types=["UnsupportedDocumentError"]
    )

    def __init__(self, parser: DocumentParser) -> None:
        self._parser = parser

    async def run(self, input: ParseRequest) -> Parsed:
        fetched = input.fetched
        raw = RawDocument(
            ref=DocumentRef(SourceId(fetched.source_id), fetched.url, fetched.external_ref),
            content=fetched.content,
            media_type=fetched.media_type,
            sha256=fetched.sha256,
            fetched_at=fetched.fetched_at,
        )
        if not self._parser.supports(raw):
            raise UnsupportedDocumentError(f"no parser for {raw.media_type}")
        parsed = self._parser.parse(raw)
        return Parsed(
            document_id=parsed.document_id.value,
            doc_type=parsed.doc_type.value,
            title=parsed.title,
            language=parsed.language,
            clause_count=len(parsed.clauses),
            clause_refs=[clause.clause_ref for clause in parsed.clauses],
        )


def document_id_for(fetched: Fetched) -> DocumentId:
    """Deterministic per digest: a re-run of the workflow parses the same document id."""
    return kernel_document_id_for(fetched.sha256)
