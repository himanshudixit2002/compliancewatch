"""Events the pipeline publishes; payload fields follow packages/contracts/events.

Document events are regulatory: they carry no tenant, and the outbox keys them by their source,
so one source's documents reach a consumer in the order they were stored. The rule candidates
extracted from a document are keyed the same way.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import ClassVar
from uuid import UUID

from domain_kernel._validation import (
    freeze_mapping,
    require_aware,
    require_date,
    require_finite,
    require_instance,
    require_int,
    require_text,
)
from domain_kernel.documents import PARSER_VERSION_PATTERN, DocumentType, document_id_for
from domain_kernel.errors import InvariantViolationError
from domain_kernel.events import DomainEvent
from domain_kernel.ids import CandidateId, ClauseId, DocumentId, SourceId
from pipeline.domain.classification import (
    Classification,
    Relevance,
    TypeConfidence,
    extracts_rules,
)
from pipeline.domain.issues import Issue
from pipeline.domain.tasks import TaskId

_SHA256 = re.compile(r"[0-9a-f]{64}")
_PARSER_VERSION = re.compile(PARSER_VERSION_PATTERN)


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


@dataclass(frozen=True, slots=True, kw_only=True)
class DocumentParsed(DocumentEvent):
    """The pipeline parsed a stored document into clauses, the first time or with another
    parser. The clause text is not in the event: it is read from the rulebook once the document
    is registered (``GET /v1/rulebook/documents/{document_id}``)."""

    topic: ClassVar[str] = "document.parsed"
    schema_version: ClassVar[str] = "1.1.0"

    doc_type: DocumentType
    title: str
    language: str
    published_at: date | None
    clause_count: int
    clause_refs: tuple[str, ...]
    parser_version: str

    def __post_init__(self) -> None:
        DocumentEvent.__post_init__(self)
        require_instance(self.doc_type, DocumentType, "doc_type")
        require_text(self.title, "title")
        require_text(self.language, "language")
        if self.published_at is not None:
            require_date(self.published_at, "published_at")
        refs = require_instance(self.clause_refs, tuple, "clause_refs")
        if not refs or len(set(refs)) != len(refs):
            raise InvariantViolationError("clause_refs must be unique and at least one")
        if self.clause_count != len(refs):
            raise InvariantViolationError("clause_count must count clause_refs")
        if not _PARSER_VERSION.fullmatch(require_instance(self.parser_version, str, "parser")):
            raise InvariantViolationError("parser_version must look like 'pdf@1'")


@dataclass(frozen=True, slots=True, kw_only=True)
class DocumentClassified(DocumentEvent):
    """The pipeline classified a parsed document (``domain.classification``): by the detector
    after its parse, or by a person's triage of a conflict."""

    topic: ClassVar[str] = "document.classified"
    schema_version: ClassVar[str] = "1.0.0"

    source_key: str
    doc_type: DocumentType
    relevance: Relevance
    confidence: TypeConfidence
    reasons: tuple[str, ...]
    classifier: str
    task_id: TaskId | None = None
    decided_by: UUID | None = None

    def __post_init__(self) -> None:
        DocumentEvent.__post_init__(self)
        require_text(self.source_key, "source_key")
        require_instance(self.doc_type, DocumentType, "doc_type")
        require_instance(self.relevance, Relevance, "relevance")
        require_instance(self.confidence, TypeConfidence, "confidence")
        reasons = require_instance(self.reasons, tuple, "reasons")
        if not reasons:
            raise InvariantViolationError("a classification gives its reasons")
        require_text(self.classifier, "classifier")

    @classmethod
    def of(
        cls, classification: Classification, *, source_id: SourceId, source_key: str
    ) -> "DocumentClassified":
        return cls(
            source_id=source_id,
            document_id=classification.document_id,
            source_key=source_key,
            doc_type=classification.doc_type,
            relevance=classification.relevance,
            confidence=classification.confidence,
            reasons=classification.reasons,
            classifier=classification.classifier,
            task_id=classification.task_id,
            decided_by=classification.decided_by,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class RuleCandidateCreated(DocumentEvent):
    """The rule extraction stored a document's candidate (``domain.extraction``): written in the
    transaction that stores the extraction. ``candidate`` is the model's answer in the
    extraction schema's shape, None when it was not a candidate (``outcome`` unparseable)."""

    topic: ClassVar[str] = "rule.candidate.created"
    schema_version: ClassVar[str] = "1.1.1"

    candidate_id: CandidateId
    regulator: str
    model: str
    prompt_version: str
    confidence: float
    citation_count: int
    needs_review: bool
    source_key: str
    doc_type: DocumentType
    outcome: str
    candidate: Mapping[str, object] | None = field(default=None, hash=False)
    issues: tuple[Issue, ...] = ()
    suggested_rule_key: str | None = None
    clause_ids: tuple[ClauseId, ...] = ()
    ontology_version: str

    def __post_init__(self) -> None:
        DocumentEvent.__post_init__(self)
        require_instance(self.candidate_id, CandidateId, "candidate_id")
        for name in ("regulator", "model", "prompt_version", "source_key", "outcome"):
            require_text(getattr(self, name), name)
        require_text(self.ontology_version, "ontology_version")
        confidence = require_finite(self.confidence, "confidence")
        if not 0 <= confidence <= 1:
            raise InvariantViolationError(f"confidence must be within [0, 1], got {confidence}")
        require_int(self.citation_count, "citation_count", minimum=0)
        require_instance(self.needs_review, bool, "needs_review")
        require_instance(self.doc_type, DocumentType, "doc_type")
        if not extracts_rules(self.doc_type):
            raise InvariantViolationError(f"no rule is extracted from a {self.doc_type.value}")
        if self.candidate is not None:
            object.__setattr__(self, "candidate", freeze_mapping(self.candidate, "candidate"))
        ids = require_instance(self.clause_ids, tuple, "clause_ids")
        if len(set(ids)) != len(ids):
            raise InvariantViolationError("clause_ids must be unique")
