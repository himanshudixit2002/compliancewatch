"""A person's retry of a stored document (the ``document_retry`` table): an ingest of the stored
bytes again, from a stage, without a new fetch.

- ``parse``: the stored document's ingest as an upload's runs it: parse (by the chain, the
  transcript, or the parser that parsed it before), classify (a classification stands), register
  while knowledge is on, and extract a classified notification, circular or act amendment while
  the extraction is on. A document no parser read before is parsed again: a parser added since
  may read it, which closes its manual parse.
- ``classify``: the same, with the detector's classification read again (``fresh``): a document
  the detector set aside or held is read with today's detector. A person's decision stands.
- ``extract``: the same, for a document classified on its way to the extraction whose extraction
  failed or never started; the classification and the registration stand.

A ``doc_type`` a person gives reclassifies the document first, whatever the stage: relevant, of
that type, ``certain``, by the ``retry`` classifier (``classification.Classification.given``).
It beats the detector, and it is the way back for a document the detector set aside as
irrelevant, or whose triage was dismissed: a typed re-upload of the same bytes is a duplicate and
changes nothing.

Each retry has an attempt number per document, from 1, and its ingest a workflow id derived from
the document and the attempt (``retry_workflow_id``), so a request sent again under its
``Idempotency-Key`` finds its attempt and starts nothing twice. A retry is kept as written.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from domain_kernel._validation import require_aware, require_instance, require_int, require_text
from domain_kernel.documents import DocumentType
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import DocumentId, EntityId
from pipeline.domain.classification import extracts_rules

RETRY_PREFIX: Final = "pipeline-retry"
MIN_KEY_CHARS: Final = 8
MAX_KEY_CHARS: Final = 128
MAX_RETRY_REASON_CHARS: Final = 2_000
_FINGERPRINT = re.compile(r"[0-9a-f]{64}")


class RetryStage(StrEnum):
    """Where a retry starts the stored document's ingest again: its parse, its classification
    (read again by the detector), or its rule extraction."""

    PARSE = "parse"
    CLASSIFY = "classify"
    EXTRACT = "extract"


@dataclass(frozen=True, slots=True)
class RetryId(EntityId):
    """One retry of one document."""


def retry_workflow_id(document_id: DocumentId, attempt: int) -> str:
    """``pipeline-retry-<document>-<attempt>``: the ingest of one retry."""
    require_instance(document_id, DocumentId, "document_id")
    require_int(attempt, "attempt", minimum=1)
    return f"{RETRY_PREFIX}-{document_id.value.hex}-{attempt}"


@dataclass(frozen=True, slots=True)
class DocumentRetry:
    """One retry: the document, its attempt number, the stage and the type a person gave (None:
    the classification stands), why and by whom, when, the request's Idempotency-Key and the
    fingerprint of its body, and the ingest's workflow id."""

    id: RetryId
    document_id: DocumentId
    attempt: int
    stage: RetryStage
    reason: str
    requested_at: datetime
    idempotency_key: str
    fingerprint: str
    workflow_id: str
    doc_type: DocumentType | None = None
    requested_by: UUID | None = None

    def __post_init__(self) -> None:
        require_instance(self.id, RetryId, "id")
        require_instance(self.document_id, DocumentId, "document_id")
        require_int(self.attempt, "attempt", minimum=1)
        require_instance(self.stage, RetryStage, "stage")
        if len(require_text(self.reason, "reason")) > MAX_RETRY_REASON_CHARS:
            raise InvariantViolationError(
                f"reason must be at most {MAX_RETRY_REASON_CHARS} characters"
            )
        require_aware(self.requested_at, "requested_at")
        key = require_text(self.idempotency_key, "idempotency_key")
        if not MIN_KEY_CHARS <= len(key) <= MAX_KEY_CHARS:
            raise InvariantViolationError(
                f"an idempotency key has {MIN_KEY_CHARS} to {MAX_KEY_CHARS} characters"
            )
        if not _FINGERPRINT.fullmatch(require_instance(self.fingerprint, str, "fingerprint")):
            raise InvariantViolationError("fingerprint must be a SHA-256 in 64 lowercase hex")
        if self.workflow_id != retry_workflow_id(self.document_id, self.attempt):
            raise InvariantViolationError(
                f"workflow_id must be {retry_workflow_id(self.document_id, self.attempt)}"
            )
        if self.doc_type is not None:
            require_instance(self.doc_type, DocumentType, "doc_type")
            if self.stage is RetryStage.EXTRACT and not extracts_rules(self.doc_type):
                raise InvariantViolationError(
                    f"no rule is extracted from a {self.doc_type.value.replace('_', ' ')}"
                )
        if self.requested_by is not None:
            require_instance(self.requested_by, UUID, "requested_by")
