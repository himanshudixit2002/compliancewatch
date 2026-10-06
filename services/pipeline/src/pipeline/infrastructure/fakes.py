"""In-memory source adapter, parser and source catalog for the sample workflow and the
tests."""

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

from domain_kernel.documents import (
    Clause,
    DiscoveredDocument,
    DocumentRef,
    DocumentType,
    ParsedDocument,
    RawDocument,
    document_id_for,
)
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import SourceId
from pipeline.domain.errors import UnknownSourceError
from pipeline.domain.ports import ResolvedSource
from pipeline.domain.sources import SourceDefinition

PARSER_VERSION = "fake@1"

SAMPLE_TEXT = (
    "Notification No. 17/2026 - Central Tax\n\n"
    "In exercise of the powers conferred by section 39 of the Central Goods and Services Tax "
    "Act, 2017, the Commissioner extends the due date for furnishing FORM GSTR-3B.\n\n"
    "This notification shall come into force on the date of its publication."
)


@dataclass
class FakeSourceAdapter:
    """Lists the documents it was given and serves their bytes."""

    source_id: SourceId
    documents: Sequence[tuple[DiscoveredDocument, bytes, str]] = field(default_factory=tuple)
    fetches: int = 0

    @classmethod
    def with_sample(cls, source_id: SourceId | None = None) -> "FakeSourceAdapter":
        source = source_id or SourceId(UUID(int=1))
        ref = DocumentRef(source, "https://example.invalid/notifications/17-2026", "17/2026")
        listed = DiscoveredDocument(ref, title="Notification No. 17/2026 - Central Tax")
        return cls(source, ((listed, SAMPLE_TEXT.encode("utf-8"), "text/plain"),))

    def list_documents(self, since: datetime) -> Iterable[DiscoveredDocument]:
        return [listed for listed, _, _ in self.documents]

    def fetch(self, ref: DocumentRef) -> RawDocument:
        self.fetches += 1
        for listed, content, media_type in self.documents:
            if listed.ref == ref:
                return RawDocument.from_bytes(ref, content, media_type)
        raise InvariantViolationError(f"unknown document {ref.url}")


class FakePlainTextParser:
    """Paragraphs become clauses ``p1``, ``p2``, ... with a document id derived from the digest."""

    def supports(self, doc: RawDocument) -> bool:
        return doc.media_type.startswith("text/plain")

    def parse(self, doc: RawDocument) -> ParsedDocument:
        text = doc.content.decode("utf-8")
        paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
        clauses = tuple(
            Clause(clause_ref=f"p{index}", text=part) for index, part in enumerate(paragraphs, 1)
        )
        return ParsedDocument(
            document_id=document_id_for(hashlib.sha256(doc.content).hexdigest()),
            doc_type=DocumentType.NOTIFICATION,
            title=paragraphs[0] if paragraphs else doc.ref.url,
            clauses=clauses,
            language="en",
            parser_version=PARSER_VERSION,
        )


SAMPLE_SOURCE = SourceDefinition(
    key="sample",
    adapter_type="fake",
    parameters={},
    cadence=timedelta(hours=1),
    regulator="CBIC",
    doc_type=DocumentType.NOTIFICATION,
)
"""The source the sample notification is listed at."""


@dataclass(frozen=True)
class StaticCatalog:
    """The sources it was given, by id."""

    sources: Mapping[SourceId, ResolvedSource]

    @classmethod
    def of(cls, *resolved: ResolvedSource) -> "StaticCatalog":
        return cls({source.source_id: source for source in resolved})

    def resolve(self, source_id: SourceId) -> ResolvedSource:
        found = self.sources.get(source_id)
        if found is None:
            raise UnknownSourceError(f"no source has the id {source_id}")
        return found


def sample_catalog(adapter: FakeSourceAdapter | None = None) -> StaticCatalog:
    """The sample notification's source (``UUID(int=1)``, key ``sample``) and nothing else."""
    sample = adapter or FakeSourceAdapter.with_sample()
    return StaticCatalog.of(ResolvedSource(sample.source_id, SAMPLE_SOURCE, sample))
