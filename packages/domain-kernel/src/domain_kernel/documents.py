"""Documents on their way through the pipeline: discovered, fetched, parsed, extracted."""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Self

from domain_kernel._validation import (
    freeze_mapping,
    require_aware,
    require_date,
    require_finite,
    require_instance,
    require_int,
    require_text,
)
from domain_kernel.confidence import Confidence
from domain_kernel.errors import InvariantViolationError
from domain_kernel.events import utc_now
from domain_kernel.ids import CandidateId, DocumentId, SourceId


class DocumentType(StrEnum):
    NOTIFICATION = "notification"
    CIRCULAR = "circular"
    PRESS_RELEASE = "press_release"
    ACT_AMENDMENT = "act_amendment"


@dataclass(frozen=True, slots=True)
class DocumentRef:
    """Where a document lives at its source."""

    source_id: SourceId
    url: str
    external_ref: str = ""

    def __post_init__(self) -> None:
        require_instance(self.source_id, SourceId, "source_id")
        require_text(self.url, "url")
        require_instance(self.external_ref, str, "external_ref")


@dataclass(frozen=True, slots=True)
class DiscoveredDocument:
    """A document a source adapter listed but has not fetched."""

    ref: DocumentRef
    title: str = ""
    published_at: date | None = None

    def __post_init__(self) -> None:
        require_instance(self.ref, DocumentRef, "ref")
        require_instance(self.title, str, "title")
        if self.published_at is not None:
            require_date(self.published_at, "published_at")


@dataclass(frozen=True, slots=True)
class RawDocument:
    """Fetched bytes with their digest. ``sha256`` must match ``content``."""

    ref: DocumentRef
    content: bytes
    media_type: str
    sha256: str
    fetched_at: datetime

    def __post_init__(self) -> None:
        require_instance(self.ref, DocumentRef, "ref")
        content = require_instance(self.content, bytes, "content")
        if not content:
            raise InvariantViolationError("content must not be empty")
        require_text(self.media_type, "media_type")
        digest = require_instance(self.sha256, str, "sha256")
        if digest != hashlib.sha256(content).hexdigest():
            raise InvariantViolationError("sha256 does not match content")
        require_aware(self.fetched_at, "fetched_at")

    @classmethod
    def from_bytes(
        cls, ref: DocumentRef, content: bytes, media_type: str, fetched_at: datetime | None = None
    ) -> Self:
        """Build with the digest computed; ``fetched_at`` defaults to now."""
        return cls(
            ref=ref,
            content=content,
            media_type=media_type,
            sha256=hashlib.sha256(content).hexdigest(),
            fetched_at=utc_now() if fetched_at is None else fetched_at,
        )


@dataclass(frozen=True, slots=True)
class BBox:
    """Bounding box on a page, in the parser's units."""

    x0: float
    y0: float
    x1: float
    y1: float

    def __post_init__(self) -> None:
        for name in ("x0", "y0", "x1", "y1"):
            require_finite(getattr(self, name), name)
        if self.x0 > self.x1 or self.y0 > self.y1:
            raise InvariantViolationError("bbox corners must be ordered: x0 <= x1 and y0 <= y1")


@dataclass(frozen=True, slots=True)
class Clause:
    """A unit of text with a reference stable across re-parses of the same document."""

    clause_ref: str
    text: str
    page: int | None = None
    bbox: BBox | None = None

    def __post_init__(self) -> None:
        require_text(self.clause_ref, "clause_ref")
        require_text(self.text, "text", strip=False)
        if self.page is not None:
            require_int(self.page, "page", minimum=1)
        if self.bbox is not None:
            require_instance(self.bbox, BBox, "bbox")


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    """A document split into clauses with unique references."""

    document_id: DocumentId
    doc_type: DocumentType
    title: str
    clauses: tuple[Clause, ...]
    published_at: date | None = None
    language: str = "en"

    def __post_init__(self) -> None:
        require_instance(self.document_id, DocumentId, "document_id")
        require_instance(self.doc_type, DocumentType, "doc_type")
        require_instance(self.title, str, "title")
        clauses = require_instance(self.clauses, tuple, "clauses")
        if not clauses:
            raise InvariantViolationError("clauses must not be empty")
        refs: set[str] = set()
        for index, clause in enumerate(clauses):
            ref = require_instance(clause, Clause, f"clauses[{index}]").clause_ref
            if ref in refs:
                raise InvariantViolationError(f"duplicate clause_ref {ref!r}")
            refs.add(ref)
        if self.published_at is not None:
            require_date(self.published_at, "published_at")
        require_text(self.language, "language")

    def find_clause(self, clause_ref: str) -> Clause | None:
        return next((clause for clause in self.clauses if clause.clause_ref == clause_ref), None)


@dataclass(frozen=True, slots=True)
class ExtractionContext:
    """What the extractor was asked to do and with which versions."""

    regulator: str
    prompt_version: str
    model: str
    ontology_version: str

    def __post_init__(self) -> None:
        require_text(self.regulator, "regulator")
        require_text(self.prompt_version, "prompt_version")
        require_text(self.model, "model")
        require_text(self.ontology_version, "ontology_version")


@dataclass(frozen=True, slots=True)
class RuleCandidate:
    """Extractor output before review. ``payload`` follows the contracts schema."""

    candidate_id: CandidateId
    document_id: DocumentId
    payload: Mapping[str, object] = field(hash=False)
    model: str
    prompt_version: str
    confidence: Confidence

    def __post_init__(self) -> None:
        require_instance(self.candidate_id, CandidateId, "candidate_id")
        require_instance(self.document_id, DocumentId, "document_id")
        object.__setattr__(self, "payload", freeze_mapping(self.payload, "payload"))
        require_text(self.model, "model")
        require_text(self.prompt_version, "prompt_version")
        require_instance(self.confidence, Confidence, "confidence")
