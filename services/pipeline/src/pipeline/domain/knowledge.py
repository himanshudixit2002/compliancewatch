"""Records the pipeline hands to the rulebook, which owns regulator documents and clauses."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from domain_kernel.documents import ParsedDocument
from domain_kernel.ids import ClauseId, DocumentId, SourceId


@dataclass(frozen=True, slots=True)
class DocumentRecord:
    """A parsed document plus where it came from. ``document`` carries the clauses, the title,
    the language, the publication date and the parser version."""

    document: ParsedDocument
    source_id: SourceId
    sha256: str
    regulator: str
    url: str
    media_type: str
    fetched_at: datetime
    external_ref: str = ""
    raw_uri: str | None = None


@dataclass(frozen=True, slots=True)
class RegisteredDocument:
    """The rulebook's answer: whether it stored the document now, and the id of each clause."""

    document_id: DocumentId
    created: bool
    clause_ids: Mapping[str, ClauseId] = field(default_factory=dict)
