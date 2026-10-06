"""What the pipeline needs from the services it hands work to, from the store that keeps the
files it fetches, from the adapter registry and from Temporal, as protocols. The adapters live in
``infrastructure`` (HTTP, S3, disk, Temporal) and ``testing`` (memory)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from domain_kernel.documents import DocumentType, ParsedDocument, RawDocument
from domain_kernel.ids import ClauseId, DocumentId, SourceId
from domain_kernel.protocols import SourceAdapter
from pipeline.domain.crawl import CrawlRunId
from pipeline.domain.embedding import ClauseToEmbed, ClauseVector, EmbeddingBatch, EmbeddingsStored
from pipeline.domain.knowledge import (
    AlignmentReport,
    DocumentRecord,
    MentionSubmission,
    RegisteredDocument,
    RelationSubmission,
    RuleKey,
    StagingReport,
)
from pipeline.domain.raw_documents import RawDocumentRecord
from pipeline.domain.schedule import CrawlTrigger
from pipeline.domain.sources import SourceDefinition
from pipeline.domain.transcripts import Transcript


@dataclass(frozen=True, slots=True)
class ParseHints:
    """How to parse one document: as ``doc_type`` (None: its source's type); with
    ``parser_version`` first, the parser that parsed it before, which the chain then uses as it
    always did and never lets give way, so a document's clauses and their ids stay what they
    were while the code has that parser; or from ``transcript``, an analyst's, as ``manual@1``
    instead of from the bytes."""

    doc_type: DocumentType | None = None
    parser_version: str = ""
    transcript: Transcript | None = None


class DocumentParsers(Protocol):
    """The parser chain (``infrastructure.parsers.ParserChain``): text-layer PDF, table-aware
    PDF, HTML, table-aware HTML, each document taken by the first parser for its media type
    that reads it."""

    def parse_as(self, raw: RawDocument, hints: ParseHints) -> ParsedDocument:
        """The document's clauses, by the hints. ``UnsupportedDocumentError`` when no parser
        takes the media type, ``UnparsedDocumentError`` when none of those that do can read the
        bytes."""
        ...


class KnowledgeSink(Protocol):
    """Where parsed regulator documents and the knowledge found in them go: the rulebook."""

    def register_document(self, record: DocumentRecord) -> RegisteredDocument:
        """Store the document and its clauses; idempotent for the same parse. Raises
        ``RulebookConflictError`` for a different parse of stored bytes."""
        ...

    def submit_mentions(self, submission: MentionSubmission) -> AlignmentReport:
        """Align the mentions; the ones that do not resolve go to the review queue."""
        ...

    def submit_relations(self, submission: RelationSubmission) -> StagingReport:
        """Stage the proposed relations as candidates for review; idempotent per proposal."""
        ...


class RulebookReader(Protocol):
    """What the extraction stages read back from the rulebook."""

    def parsed_document(self, document_id: DocumentId) -> ParsedDocument:
        """The stored document with its clauses, as the kernel's ``ParsedDocument``."""
        ...

    def known_rules(self) -> tuple[RuleKey, ...]:
        """The rules a relation may name as the one it affects."""
        ...


class Embedder(Protocol):
    """Vectors for texts, through the llm-gateway's retrieval feature."""

    def embed(
        self,
        inputs: Sequence[str],
        *,
        model: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> EmbeddingBatch:
        """One vector per input, in order. ``model`` overrides the gateway's retrieval route;
        ``metadata`` tags the call's trace."""
        ...


class ClauseIndexSink(Protocol):
    """The rulebook's clause search index, as far as the pipeline fills it."""

    def unembedded_clauses(
        self,
        model: str,
        *,
        document_id: DocumentId | None = None,
        limit: int = 64,
        after: ClauseId | None = None,
    ) -> tuple[ClauseToEmbed, ...]:
        """Stored clauses with no vector from ``model``, in clause id order after ``after``;
        of one document, or of every document."""
        ...

    def put_embeddings(
        self, model: str, dims: int, items: Sequence[ClauseVector]
    ) -> EmbeddingsStored:
        """Store the vectors under ``model``; a clause that has one from it keeps it."""
        ...


class RawStore(Protocol):
    """Where fetched files are kept, by their content (guide section 7): the key names the
    SHA-256 of the bytes, a file is never overwritten, and storing the same bytes again stores
    nothing."""

    def put(self, raw: RawDocument) -> str:
        """Store the bytes unless they are stored; their storage key either way."""
        ...

    def get(self, storage_key: str) -> bytes:
        """The bytes under ``storage_key``, checked against the digest it names. Raises
        ``RawObjectMissingError`` or ``RawObjectCorruptError``."""
        ...

    def uri(self, storage_key: str) -> str:
        """Where the key's bytes are, as a URI: ``s3://bucket/key``, ``file:///...``."""
        ...


@dataclass(frozen=True, slots=True)
class ResolvedSource:
    """A source the pipeline can fetch from: its id, what it is, and the adapter that reads
    it."""

    source_id: SourceId
    definition: SourceDefinition
    adapter: SourceAdapter


class SourceCatalog(Protocol):
    """The sources the pipeline knows, by id."""

    def resolve(self, source_id: SourceId) -> ResolvedSource:
        """The source with this id; ``UnknownSourceError`` when there is none."""
        ...


@dataclass(frozen=True, slots=True)
class SourceKind:
    """What an adapter type makes of a source's parameters: the parameters as the type reads
    them (JSON values, defaults filled in), and the regulator, site and document type they give.
    ``listable`` is False for an upload-only type, whose sources the schedule never crawls.
    """

    adapter_type: str
    parameters: Mapping[str, object]
    regulator: str
    site: str
    doc_type: DocumentType
    listable: bool = True


class AdapterTypes(Protocol):
    """The adapter types the code has (the registry's ``ADAPTER_TYPES``)."""

    def names(self) -> Sequence[str]:
        """Every adapter type, sorted."""
        ...

    def listable(self, adapter_type: str) -> bool:
        """Whether sources of the type list documents (False for an upload-only type); a type
        the code does not have counts as listable, so its crawl reports what is wrong."""
        ...

    def describe(self, adapter_type: str, parameters: Mapping[str, object]) -> SourceKind:
        """The type's reading of the parameters; ``SourceInvalidError`` for a type the code
        does not have, or parameters the type refuses (anything it does not name, a value of
        the wrong kind, a CBIC category without a recorded listing)."""
        ...


@dataclass(frozen=True, slots=True)
class CrawlStart:
    """A crawl to start: the workflow's id, the run it records, the source, and why."""

    workflow_id: str
    run_id: CrawlRunId
    source_key: str
    trigger: CrawlTrigger


class CrawlStarter(Protocol):
    """Starts the crawl workflow (``pipeline.crawl_source``) on Temporal."""

    def start(self, start: CrawlStart) -> bool:
        """Start the workflow; False when a workflow with its id exists already, running or
        not (it is never started twice). ``CrawlUnavailableError`` when Temporal does not
        answer."""
        ...


@dataclass(frozen=True, slots=True)
class IngestStart:
    """An ingest of a stored document to start (``pipeline.ingest_document`` with
    ``IngestRequest.stored``): the workflow's id; the document as its record holds it, under the
    source it is stored for (its id and regulator) and where the raw store keeps it; whether
    those bytes were stored before; the analyst's transcript to parse it from, if any; and
    whether the knowledge steps run."""

    workflow_id: str
    record: RawDocumentRecord
    source_id: SourceId
    regulator: str
    raw_uri: str
    duplicate: bool = False
    transcript_key: str = ""
    knowledge: bool = False


class IngestStarter(Protocol):
    """Starts the ingest of a stored document on Temporal (an upload's, a resolution's)."""

    def start(self, start: IngestStart) -> bool:
        """Start the workflow; False when a workflow with its id runs or has completed (one
        that failed may run again). ``IngestUnavailableError`` when Temporal does not answer."""
        ...
