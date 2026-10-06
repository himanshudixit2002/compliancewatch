"""Events the pipeline publishes; payload fields follow packages/contracts/events.

Document events are regulatory: they carry no tenant, and the outbox keys them by their source,
so one source's documents reach a consumer in the order they were stored.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import ClassVar

from domain_kernel._validation import (
    require_aware,
    require_date,
    require_instance,
    require_text,
)
from domain_kernel.documents import document_id_for
from domain_kernel.errors import InvariantViolationError
from domain_kernel.events import DomainEvent
from domain_kernel.ids import DocumentId, SourceId

_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True, kw_only=True)
class DocumentEvent(DomainEvent):
    """Base of the document events: the source and the document they are about."""

    source_id: SourceId
    document_id: DocumentId

    def __post_init__(self) -> None:
        DomainEvent.__post_init__(self)
        if self.tenant_id is not None:
            raise InvariantViolationError(f"{type(self).topic} is regulatory: no tenant")
        require_instance(self.source_id, SourceId, "source_id")
        require_instance(self.document_id, DocumentId, "document_id")

    @property
    def partition_key(self) -> str:
        return str(self.source_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class DocumentDiscovered(DocumentEvent):
    """The pipeline fetched a document whose bytes it had not stored and stored them."""

    topic: ClassVar[str] = "document.discovered"
    schema_version: ClassVar[str] = "1.0.0"

    regulator: str
    url: str
    external_ref: str
    title: str
    published_at: date | None
    sha256: str
    media_type: str
    fetched_at: datetime
    raw_uri: str

    def __post_init__(self) -> None:
        DocumentEvent.__post_init__(self)
        require_text(self.regulator, "regulator")
        require_text(self.url, "url")
        require_instance(self.external_ref, str, "external_ref")
        require_instance(self.title, str, "title")
        if self.published_at is not None:
            require_date(self.published_at, "published_at")
        digest = require_instance(self.sha256, str, "sha256")
        if not _SHA256.fullmatch(digest):
            raise InvariantViolationError(f"sha256 must be 64 lowercase hex digits, got {digest!r}")
        if document_id_for(digest) != self.document_id:
            raise InvariantViolationError("document_id must be the first half of sha256")
        require_text(self.media_type, "media_type")
        require_aware(self.fetched_at, "fetched_at")
        require_text(self.raw_uri, "raw_uri")
