"""Fetch a document, keep its bytes and record it once: the use case behind the
``pipeline.fetch_and_store`` activity.

The steps run in this order, with no transaction open during the first three:

1. fetch the bytes through the source's adapter (HTTP);
2. look the bytes up: a document with the same content is a duplicate, and then nothing is
   written, neither a file nor a row nor an event;
3. store the bytes in the raw store under their content key (S3 or disk);
4. in one transaction, record the source when it is new, insert the document's row and write
   its document.discovered to the outbox.

The file is stored before the row, so a committed row always names stored bytes. Two fetches of
the same bytes at once store the same object; the database lets one insert win, and only that one
writes the event. A Temporal retry after the commit finds the row and reports a duplicate, and
the event has gone out once.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

from domain_kernel._validation import require_instance, require_text
from domain_kernel.documents import DocumentRef, RawDocument, document_id_for
from domain_kernel.events import utc_now
from domain_kernel.ids import SourceId
from pipeline.domain.events import DocumentDiscovered
from pipeline.domain.ports import RawStore, ResolvedSource, SourceCatalog
from pipeline.domain.raw_documents import RawDocumentRecord
from pipeline.domain.repository import UnitOfWorkFactory
from pipeline.domain.sources import Source
from py_common.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class StoreRequest:
    """A document the source listed: where it is and what the listing said about it."""

    source_id: SourceId
    url: str
    external_ref: str = ""
    title: str = ""
    published_at: date | None = None

    def __post_init__(self) -> None:
        require_instance(self.source_id, SourceId, "source_id")
        require_text(self.url, "url")


@dataclass(frozen=True, slots=True)
class StoredDocument:
    """What one fetch came to. ``record`` is the stored row: the one this fetch wrote, or for a
    duplicate the one written first, whose ``storage_key`` holds the bytes. ``url``,
    ``external_ref``, ``fetched_at`` and ``media_type`` are this fetch's."""

    source: ResolvedSource
    record: RawDocumentRecord
    url: str
    external_ref: str
    fetched_at: datetime
    media_type: str
    raw_uri: str
    duplicate: bool


class StoreDocument:
    def __init__(
        self,
        sources: SourceCatalog,
        units: UnitOfWorkFactory,
        raw_store: RawStore,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._sources = sources
        self._units = units
        self._raw = raw_store
        self._clock = clock

    def run(self, request: StoreRequest) -> StoredDocument:
        source = self._sources.resolve(request.source_id)
        ref = DocumentRef(source.source_id, request.url, request.external_ref)
        raw = source.adapter.fetch(ref)
        document_id = document_id_for(raw.sha256)
        with self._units() as unit:
            stored = unit.documents.get(document_id)
        if stored is not None:
            return self._outcome(source, request, raw, stored, duplicate=True)
        key = self._raw.put(raw)
        record = RawDocumentRecord(
            document_id=document_id,
            source_key=source.definition.key,
            source_url=request.url,
            fetched_at=raw.fetched_at,
            content_type=raw.media_type,
            size=len(raw.content),
            sha256=raw.sha256,
            storage_key=key,
            external_ref=request.external_ref,
            title=request.title,
            published_on=request.published_at,
        )
        with self._units() as unit:
            unit.sources.add(Source.of(source.definition, self._clock()))
            if unit.documents.add(record):
                unit.events.publish(self._discovered(source, request, raw, key))
                duplicate = False
            else:
                # Another fetch of the same bytes committed between the look-up and the insert.
                found = unit.documents.get(document_id)
                record = record if found is None else found
                duplicate = True
        return self._outcome(source, request, raw, record, duplicate=duplicate)

    def _discovered(
        self, source: ResolvedSource, request: StoreRequest, raw: RawDocument, key: str
    ) -> DocumentDiscovered:
        return DocumentDiscovered(
            source_id=source.source_id,
            document_id=document_id_for(raw.sha256),
            regulator=source.definition.regulator,
            url=request.url,
            external_ref=request.external_ref,
            title=request.title,
            published_at=request.published_at,
            sha256=raw.sha256,
            media_type=raw.media_type,
            fetched_at=raw.fetched_at,
            raw_uri=self._raw.uri(key),
        )

    def _outcome(
        self,
        source: ResolvedSource,
        request: StoreRequest,
        raw: RawDocument,
        record: RawDocumentRecord,
        *,
        duplicate: bool,
    ) -> StoredDocument:
        log.info(
            "pipeline.document_stored",
            source=source.definition.key,
            document_id=str(record.document_id),
            sha256=record.sha256,
            storage_key=record.storage_key,
            duplicate=duplicate,
        )
        return StoredDocument(
            source=source,
            record=record,
            url=request.url,
            external_ref=request.external_ref,
            fetched_at=raw.fetched_at,
            media_type=raw.media_type,
            raw_uri=self._raw.uri(record.storage_key),
            duplicate=duplicate,
        )
