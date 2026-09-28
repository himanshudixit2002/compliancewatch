"""Request and response bodies of the rulebook API."""

from datetime import date
from typing import Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from domain_kernel.documents import PARSER_VERSION_PATTERN, Clause, DocumentType
from domain_kernel.ids import DocumentId, SourceId
from rulebook.application.documents import Registration
from rulebook.domain.documents import CLAUSE_REF_PATTERN, StoredClause, StoredDocument

SHA256_PATTERN = r"^[0-9a-f]{64}$"


class ClauseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clause_ref: str = Field(pattern=CLAUSE_REF_PATTERN, examples=["en.p3"])
    text: str = Field(min_length=1, max_length=50_000)
    page: int | None = Field(default=None, ge=1)

    def to_clause(self) -> Clause:
        return Clause(clause_ref=self.clause_ref, text=self.text, page=self.page)


class DocumentIn(BaseModel):
    """A parsed regulator document. The id in the path must be the first half of ``sha256``."""

    model_config = ConfigDict(extra="forbid")

    source_id: UUID
    sha256: str = Field(pattern=SHA256_PATTERN)
    regulator: str = Field(min_length=1, max_length=40, examples=["CBIC"])
    doc_type: DocumentType
    external_ref: str = Field(default="", max_length=200, examples=["01/2026-Central Tax"])
    url: str = Field(min_length=1, max_length=2_000)
    title: str = Field(default="", max_length=2_000)
    language: str = Field(min_length=1, max_length=8, examples=["en"])
    media_type: str = Field(min_length=1, max_length=80, examples=["application/pdf"])
    parser_version: str = Field(pattern=PARSER_VERSION_PATTERN, max_length=40, examples=["pdf@1"])
    published_at: date | None = None
    fetched_at: AwareDatetime
    raw_uri: str | None = Field(default=None, max_length=2_000)
    clauses: list[ClauseIn] = Field(min_length=1, max_length=2_000)

    def to_document(self, document_id: UUID) -> StoredDocument:
        return StoredDocument(
            document_id=DocumentId(document_id),
            source_id=SourceId(self.source_id),
            sha256=self.sha256,
            regulator=self.regulator,
            doc_type=self.doc_type,
            url=self.url,
            language=self.language,
            media_type=self.media_type,
            parser_version=self.parser_version,
            fetched_at=self.fetched_at,
            external_ref=self.external_ref,
            title=self.title,
            published_at=self.published_at,
            raw_uri=self.raw_uri,
        )


class RegisteredOut(BaseModel):
    document_id: UUID
    created: bool
    clause_ids: dict[str, UUID] = Field(description="Clause ref to the id every service derives")
    metadata_differs: list[str] = Field(
        description="Fields whose submitted value differs from the stored one; the stored wins"
    )

    @classmethod
    def from_registration(cls, registration: Registration) -> Self:
        return cls(
            document_id=registration.document_id.value,
            created=registration.created,
            clause_ids={ref: clause_id.value for ref, clause_id in registration.clause_ids.items()},
            metadata_differs=list(registration.metadata_differs),
        )


class ClauseOut(BaseModel):
    clause_id: UUID
    clause_ref: str
    ordinal: int
    page: int | None
    text: str

    @classmethod
    def from_clause(cls, clause: StoredClause) -> Self:
        return cls(
            clause_id=clause.clause_id.value,
            clause_ref=clause.clause_ref,
            ordinal=clause.ordinal,
            page=clause.page,
            text=clause.text,
        )


class DocumentOut(BaseModel):
    document_id: UUID
    source_id: UUID
    sha256: str
    regulator: str
    doc_type: DocumentType
    external_ref: str
    url: str
    title: str
    language: str
    media_type: str
    parser_version: str
    published_at: date | None
    clauses: list[ClauseOut]

    @classmethod
    def from_stored(cls, document: StoredDocument, clauses: tuple[StoredClause, ...]) -> Self:
        return cls(
            document_id=document.document_id.value,
            source_id=document.source_id.value,
            sha256=document.sha256,
            regulator=document.regulator,
            doc_type=document.doc_type,
            external_ref=document.external_ref,
            url=document.url,
            title=document.title,
            language=document.language,
            media_type=document.media_type,
            parser_version=document.parser_version,
            published_at=document.published_at,
            clauses=[ClauseOut.from_clause(clause) for clause in clauses],
        )
