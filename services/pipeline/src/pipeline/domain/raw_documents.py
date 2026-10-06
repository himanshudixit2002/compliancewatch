"""Fetched regulator files as the pipeline records them (the ``raw_document`` table).

A record is keyed by its content: its id is the kernel's ``document_id_for`` of the SHA-256 of the
bytes, so the same bytes are one record however often, and from wherever, they are fetched (or
uploaded). The bytes themselves are in the raw store under ``storage_key``. What the source listed
and the bytes never change; only how the document stands does: its ``status``, moved on by the
parse or a person, and the parse itself (``parser_version``, and ``transcript_key`` once an analyst
transcribed it). ``doc_type`` is the type an uploader gave, set once; None means its source's.
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
from domain_kernel.documents import PARSER_VERSION_PATTERN, DocumentType, document_id_for
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import DocumentId
from pipeline.domain.sources import require_source_key

MAX_STORAGE_KEY_CHARS: Final = 1_024
"""S3's limit on an object key, in bytes; keys here are ASCII."""
MAX_CONTENT_TYPE_CHARS: Final = 255

_SHA256 = re.compile(r"[0-9a-f]{64}")
_PARSER_VERSION = re.compile(PARSER_VERSION_PATTERN)


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
    what the source listed when the file was first stored (or what its uploader gave);
    ``fetched_at`` is that first fetch. ``parser_version`` names the parser of its last parse,
    empty before one; ``transcript_key`` is where the raw store keeps the analyst's transcript it
    is parsed from (``manual@1``), empty for a document no one transcribed."""

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
    parser_version: str = ""
    doc_type: DocumentType | None = None
    transcript_key: str = ""

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
        version = require_instance(self.parser_version, str, "parser_version")
        if version and not _PARSER_VERSION.fullmatch(version):
            raise InvariantViolationError(f"parser_version must look like 'pdf@1', got {version!r}")
        if self.doc_type is not None:
            require_instance(self.doc_type, DocumentType, "doc_type")
        transcript = require_instance(self.transcript_key, str, "transcript_key")
        if len(transcript) > MAX_STORAGE_KEY_CHARS:
            raise InvariantViolationError("transcript_key is too long")
