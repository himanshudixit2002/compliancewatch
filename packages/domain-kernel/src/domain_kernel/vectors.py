"""Embedded clauses and the shapes the vector store takes and returns."""

from dataclasses import dataclass
from datetime import date

from domain_kernel._validation import require_date, require_finite, require_instance, require_text
from domain_kernel.documents import DocumentType
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import ClauseId, DocumentId
from domain_kernel.periods import EffectivePeriod

type Vector = tuple[float, ...]


@dataclass(frozen=True, slots=True)
class EmbeddedClause:
    """A clause's embedding with the metadata retrieval filters on."""

    clause_id: ClauseId
    document_id: DocumentId
    vector: Vector
    model: str
    regulator: str
    doc_type: DocumentType
    effective: EffectivePeriod | None = None

    def __post_init__(self) -> None:
        require_instance(self.clause_id, ClauseId, "clause_id")
        require_instance(self.document_id, DocumentId, "document_id")
        vector = require_instance(self.vector, tuple, "vector")
        if not vector:
            raise InvariantViolationError("vector must not be empty")
        for index, component in enumerate(vector):
            require_finite(component, f"vector[{index}]")
        require_text(self.model, "model")
        require_text(self.regulator, "regulator")
        require_instance(self.doc_type, DocumentType, "doc_type")
        if self.effective is not None:
            require_instance(self.effective, EffectivePeriod, "effective")


@dataclass(frozen=True, slots=True)
class ClauseFilter:
    """Metadata filters applied before similarity ranking."""

    regulator: str | None = None
    doc_types: frozenset[DocumentType] = frozenset()
    as_of: date | None = None

    def __post_init__(self) -> None:
        if self.regulator is not None:
            require_text(self.regulator, "regulator")
        for doc_type in require_instance(self.doc_types, frozenset, "doc_types"):
            require_instance(doc_type, DocumentType, "doc_types")
        if self.as_of is not None:
            require_date(self.as_of, "as_of")


@dataclass(frozen=True, slots=True)
class ScoredClause:
    """A search hit."""

    clause_id: ClauseId
    score: float

    def __post_init__(self) -> None:
        require_instance(self.clause_id, ClauseId, "clause_id")
        require_finite(self.score, "score")
