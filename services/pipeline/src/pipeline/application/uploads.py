"""An analyst's upload of a document to a source: the way in for a document no site lists (the
statutes the rules cite) or a site blocks.

``UploadDocument`` checks the file (a PDF or an HTML page of at most the upload limit, its bytes
what its type says), keeps the bytes in the raw store with no transaction open, and then, in one
transaction, records the document with its ``document.discovered`` and its ``audit.event`` row
(``pipeline.document.upload``, of no tenant). With the transaction closed it starts the ingest
of the stored document (``IngestStarter``), which parses it, and registers it while knowledge is
on. Bytes stored before are a duplicate: nothing is recorded again, the upload is audited all
the same, and the ingest runs again (the parse and the registration are idempotent), so an
upload whose ingest could not start is mended by uploading the file again.

An uploaded document is listed at ``upload://<source key>/<sha256>``, its title, date and
reference are what the uploader gave, and its document type is the one the uploader gave
(recorded on the document) or else its source's.
"""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final
from uuid import UUID, uuid4

from domain_kernel.audit import AuditEntry
from domain_kernel.documents import DocumentRef, DocumentType, RawDocument, document_id_for
from domain_kernel.errors import InvariantViolationError
from domain_kernel.events import utc_now
from pipeline.application.sources import AdminAction, require_reason
from pipeline.domain.errors import (
    SourceNotFoundError,
    UploadTooLargeError,
    UploadUnsupportedError,
)
from pipeline.domain.events import DocumentDiscovered
from pipeline.domain.ports import AdapterTypes, IngestStart, IngestStarter, RawStore
from pipeline.domain.raw_documents import RawDocumentRecord
from pipeline.domain.repository import UnitOfWorkFactory
from pipeline.domain.sources import source_id_of
from py_common.logging import get_logger

log = get_logger(__name__)

UPLOAD_ACTION: Final = "pipeline.document.upload"
DOCUMENT_SUBJECT: Final = "raw_document"
PDF: Final = "application/pdf"
HTML: Final = "text/html"
XHTML: Final = "application/xhtml+xml"
UPLOAD_SCHEME: Final = "upload://"
MAX_TITLE_CHARS: Final = 2_000
MAX_REF_CHARS: Final = 200


def upload_url(source_key: str, sha256: str) -> str:
    """Where an uploaded document is listed: ``upload://<source key>/<sha256>``."""
    return f"{UPLOAD_SCHEME}{source_key}/{sha256}"


def upload_workflow_id(source_key: str, request: UUID) -> str:
    """``pipeline-upload-<key>-<request>``: one ingest per upload request."""
    return f"pipeline-upload-{source_key}-{request.hex}"


def media_type_of(content: bytes, declared: str) -> str:
    """The upload's media type: a PDF when the bytes are one, an HTML page when it says it is
    one and its bytes start like markup; ``UploadUnsupportedError`` for anything else."""
    kind = declared.split(";")[0].strip().lower()
    if content.startswith(b"%PDF-"):
        if kind not in (PDF, "application/octet-stream", ""):
            raise UploadUnsupportedError(f"the file is a PDF sent as {kind}")
        return PDF
    if kind in (HTML, XHTML):
        head = content[:1_024].lstrip(b"\xef\xbb\xbf \t\r\n")
        if not head.startswith(b"<"):
            raise UploadUnsupportedError("the file is sent as an HTML page but is not markup")
        return kind
    raise UploadUnsupportedError(
        f"only a PDF or an HTML page can be uploaded, not {kind or 'a file of no type'}"
    )


@dataclass(frozen=True, slots=True)
class Upload:
    """A file for a source, and what the uploader says of it."""

    source_key: str
    content: bytes
    media_type: str
    title: str = ""
    published_on: date | None = None
    external_ref: str = ""
    document_type: DocumentType | None = None


@dataclass(frozen=True, slots=True)
class UploadOutcome:
    """The stored document (for a duplicate, the record stored first, which may be another
    source's), whether its bytes were stored before, and the ingest started for it."""

    record: RawDocumentRecord
    duplicate: bool
    workflow_id: str


class UploadDocument:
    def __init__(
        self,
        units: UnitOfWorkFactory,
        raw_store: RawStore,
        starter: IngestStarter,
        types: AdapterTypes,
        *,
        max_bytes: int,
        knowledge: bool,
        clock: Callable[[], datetime] = utc_now,
        request_ids: Callable[[], UUID] = uuid4,
    ) -> None:
        self._units = units
        self._raw = raw_store
        self._starter = starter
        self._types = types
        self._max_bytes = max_bytes
        self._knowledge = knowledge
        self._clock = clock
        self._request_ids = request_ids

    def run(self, upload: Upload, admin: AdminAction) -> UploadOutcome:
        reason = require_reason(admin.reason)
        if len(upload.content) > self._max_bytes:
            raise UploadTooLargeError(
                f"the file has {len(upload.content)} bytes; at most {self._max_bytes} are taken"
            )
        if not upload.content:
            raise UploadUnsupportedError("the file is empty")
        media_type = media_type_of(upload.content, upload.media_type)
        title, ref = upload.title.strip(), upload.external_ref.strip()
        if len(title) > MAX_TITLE_CHARS or len(ref) > MAX_REF_CHARS:
            raise InvariantViolationError("the title or the reference is too long")
        key = upload.source_key
        with self._units() as unit:
            source = unit.sources.get(key)
        if source is None:
            raise SourceNotFoundError(f"no source has the key {key!r}")
        kind = self._types.describe(source.adapter_type, source.parameters)
        now = self._clock()
        sha256 = hashlib.sha256(upload.content).hexdigest()
        url = upload_url(key, sha256)
        raw = RawDocument(
            ref=DocumentRef(source_id_of(key), url, ref),
            content=upload.content,
            media_type=media_type,
            sha256=sha256,
            fetched_at=now,
        )
        storage_key = self._raw.put(raw)
        record = RawDocumentRecord(
            document_id=document_id_for(sha256),
            source_key=key,
            source_url=url,
            fetched_at=now,
            content_type=media_type,
            size=len(upload.content),
            sha256=sha256,
            storage_key=storage_key,
            external_ref=ref,
            title=title,
            published_on=upload.published_on,
            doc_type=upload.document_type,
        )
        with self._units() as unit:
            if unit.documents.add(record):
                duplicate = False
                unit.events.publish(
                    DocumentDiscovered(
                        source_id=source_id_of(key),
                        document_id=record.document_id,
                        regulator=kind.regulator,
                        url=url,
                        external_ref=ref,
                        title=title,
                        published_at=upload.published_on,
                        sha256=sha256,
                        media_type=media_type,
                        fetched_at=now,
                        raw_uri=self._raw.uri(storage_key),
                    )
                )
            else:
                found = unit.documents.get(record.document_id)
                record = record if found is None else found
                duplicate = True
            unit.audit.write(
                AuditEntry(
                    action=UPLOAD_ACTION,
                    tenant_id=None,
                    subject_type=DOCUMENT_SUBJECT,
                    subject_id=str(record.document_id),
                    actor=admin.actor,
                    reason=reason,
                    after={
                        "source_key": key,
                        "sha256": sha256,
                        "size": len(upload.content),
                        "media_type": media_type,
                        "title": title,
                        "external_ref": ref,
                        "published_on": None
                        if upload.published_on is None
                        else upload.published_on.isoformat(),
                        "document_type": None
                        if upload.document_type is None
                        else upload.document_type.value,
                        "duplicate": duplicate,
                    },
                    occurred_at=now,
                    correlation_id=admin.correlation_id,
                )
            )
        workflow_id = upload_workflow_id(key, self._request_ids())
        self._start(workflow_id, record, duplicate)
        log.info(
            "pipeline.document_uploaded",
            source=key,
            document_id=str(record.document_id),
            duplicate=duplicate,
            workflow_id=workflow_id,
        )
        return UploadOutcome(record, duplicate, workflow_id)

    def _start(self, workflow_id: str, record: RawDocumentRecord, duplicate: bool) -> None:
        with self._units() as unit:
            owner = unit.sources.get(record.source_key)
        regulator = (
            ""
            if owner is None
            else (self._types.describe(owner.adapter_type, owner.parameters).regulator)
        )
        self._starter.start(
            IngestStart(
                workflow_id=workflow_id,
                record=record,
                source_id=source_id_of(record.source_key),
                regulator=regulator,
                raw_uri=self._raw.uri(record.storage_key),
                duplicate=duplicate,
                knowledge=self._knowledge and bool(regulator),
            )
        )
