"""Fetched regulator files as the pipeline records them (the ``raw_document`` table).

A record is keyed by its content: its id is the kernel's ``document_id_for`` of the SHA-256 of the
bytes, so the same bytes are one record however often, and from wherever, they are fetched. The
bytes themselves are in the raw store under ``storage_key``. Only ``status`` ever changes: the
parse, or a person, moves a discovered document on.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Final

from domain_kernel._validation import (
    require_aware,
    require_date,
    require_instance,
    require_int,
    require_text,
)
from domain_kernel.documents import document_id_for
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import DocumentId
from pipeline.domain.sources import require_source_key

MAX_STORAGE_KEY_CHARS: Final = 1_024
"""S3's limit on an object key, in bytes; keys here are ASCII."""
MAX_CONTENT_TYPE_CHARS: Final = 255

_SHA256 = re.compile(r"[0-9a-f]{64}")


class DocumentStatus(StrEnum):
    """Where a stored document stands: just discovered, parsed into clauses, failed to parse,
    or set aside as not a regulatory document (a user manual listed among notifications)."""

    DISCOVERED = "discovered"
    PARSED = "parsed"
    FAILED = "failed"
    IRRELEVANT = "irrelevant"


@dataclass(frozen=True, slots=True)
class RawDocumentRecord:
    """One fetched file. ``source_url``, ``external_ref``, ``title`` and ``published_on`` are
    what the source listed when the file was first stored; ``fetched_at`` is that first fetch."""

    document_id: DocumentId
    source_key: str
    source_url: str
    fetched_at: datetime
    content_type: str
    size: int
    sha256: str
    storage_key: str
    external_ref: str = ""
    title: str = ""
    published_on: date | None = None
    status: DocumentStatus = DocumentStatus.DISCOVERED

    def __post_init__(self) -> None:
        require_instance(self.document_id, DocumentId, "document_id")
        require_source_key(self.source_key)
        require_text(self.source_url, "source_url")
        require_aware(self.fetched_at, "fetched_at")
        content_type = require_text(self.content_type, "content_type")
        if len(content_type) > MAX_CONTENT_TYPE_CHARS:
            raise InvariantViolationError("content_type is too long")
        require_int(self.size, "size", minimum=1)
        digest = require_instance(self.sha256, str, "sha256")
        if not _SHA256.fullmatch(digest):
            raise InvariantViolationError(f"sha256 must be 64 lowercase hex digits, got {digest!r}")
        if document_id_for(digest) != self.document_id:
            raise InvariantViolationError(
                f"document_id {self.document_id} is not the first half of sha256 {digest}"
            )
        key = require_text(self.storage_key, "storage_key")
        if len(key) > MAX_STORAGE_KEY_CHARS:
            raise InvariantViolationError("storage_key is too long")
        require_instance(self.external_ref, str, "external_ref")
        require_instance(self.title, str, "title")
        if self.published_on is not None:
            require_date(self.published_on, "published_on")
        require_instance(self.status, DocumentStatus, "status")
