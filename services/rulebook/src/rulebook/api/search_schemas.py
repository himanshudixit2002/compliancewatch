"""Request and response bodies of the clause search routes."""

from datetime import date
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from domain_kernel.documents import DocumentType
from domain_kernel.ids import ClauseId
from domain_kernel.vectors import EMBEDDING_DIMS, ClauseFilter
from rulebook.application.search import MAX_EMBEDDINGS, StoreReport
from rulebook.domain.search import MAX_K, ClauseEmbedding, SearchHit, SearchQuery


class EmbeddingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clause_id: UUID
    vector: list[float] = Field(min_length=EMBEDDING_DIMS, max_length=EMBEDDING_DIMS)

    def to_embedding(self) -> ClauseEmbedding:
        return ClauseEmbedding(ClauseId(self.clause_id), tuple(self.vector))


class EmbeddingsIn(BaseModel):
    """Clause vectors from one model. ``dims`` must be the rulebook's 512: a model that serves
    another size is refused, because its vectors would not compare with the stored ones."""

    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1, max_length=120, examples=["voyage/voyage-3.5-lite"])
    dims: int = Field(examples=[EMBEDDING_DIMS])
    items: list[EmbeddingIn] = Field(min_length=1, max_length=MAX_EMBEDDINGS)


class EmbeddingsStoredOut(BaseModel):
    stored: int = Field(description="Embeddings stored now")
    unchanged: int = Field(description="Clauses that had an embedding from this model already")

    @classmethod
    def from_report(cls, report: StoreReport) -> Self:
        return cls(stored=report.stored, unchanged=report.unchanged)


class SearchIn(BaseModel):
    """A hybrid search. ``text`` feeds the lexical leg; ``vector``, the text's embedding from
    ``model``, feeds the vector leg. ``as_of`` keeps documents published on or before it."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=2_000)
    vector: list[float] | None = Field(
        default=None, min_length=EMBEDDING_DIMS, max_length=EMBEDDING_DIMS
    )
    model: str | None = Field(
        default=None, min_length=1, max_length=120, description="Required with a vector"
    )
    regulator: str | None = Field(default=None, min_length=1, max_length=40)
    doc_types: list[DocumentType] = Field(default_factory=list, max_length=len(DocumentType))
    as_of: date | None = None
    k: int = Field(default=8, ge=1, le=MAX_K)

    @model_validator(mode="after")
    def _vector_names_its_model(self) -> Self:
        if self.vector is not None and self.model is None:
            raise ValueError("a vector needs the model that embedded it")
        return self

    def to_query(self) -> SearchQuery:
        return SearchQuery(
            text=self.text,
            filters=ClauseFilter(
                regulator=self.regulator, doc_types=frozenset(self.doc_types), as_of=self.as_of
            ),
            vector=None if self.vector is None else tuple(self.vector),
            model=self.model,
            k=self.k,
        )


class SearchHitOut(BaseModel):
    clause_id: UUID
    document_id: UUID
    clause_ref: str
    text: str
    regulator: str
    doc_type: DocumentType
    external_ref: str = Field(description="The document's number, such as 01/2026-Central Tax")
    title: str
    published_at: date | None
    score: float = Field(description="Reciprocal rank fusion over the two legs")
    lexical_rank: int | None = Field(description="1-based rank in the lexical leg, if in it")
    vector_rank: int | None = Field(description="1-based rank in the vector leg, if in it")
    cited_by: list[UUID] = Field(
        description=(
            "Published or superseded rule versions citing the clause with a verified quote, "
            "in force on as_of when it is given"
        )
    )
    out_of_force: bool = Field(
        description=(
            "The clause is cited with a verified quote by a published, superseded or withdrawn "
            "version and none of them is in force on as_of; false without as_of or a citation"
        )
    )

    @classmethod
    def from_hit(cls, hit: SearchHit) -> Self:
        clause, document = hit.detail.clause, hit.detail.document
        return cls(
            clause_id=clause.clause_id.value,
            document_id=clause.document_id.value,
            clause_ref=clause.clause_ref,
            text=clause.text,
            regulator=document.regulator,
            doc_type=document.doc_type,
            external_ref=document.external_ref,
            title=document.title,
            published_at=document.published_at,
            score=hit.score,
            lexical_rank=hit.lexical_rank,
            vector_rank=hit.vector_rank,
            cited_by=[version.value for version in hit.cited_by],
            out_of_force=hit.out_of_force,
        )
