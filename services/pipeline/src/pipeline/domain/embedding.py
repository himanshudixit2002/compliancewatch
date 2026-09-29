"""The text the pipeline embeds for a clause, and the records an embedding run passes around.

A clause on its own rarely says what it belongs to ("the said date is extended till ..."), so
``embedding_text`` puts a one-line header before it: the regulator, the document type, the
document's number (or its title when it has none), its publication date and the clause's own
reference. The vector then carries that context, and a question naming the notification or the
regulator lands near its clauses. Whitespace runs in the clause text collapse to one space; the
result is cut at ``max_chars``, well inside what the gateway accepts per text.
"""

from dataclasses import dataclass
from datetime import date
from typing import Final

from domain_kernel.documents import DocumentType
from domain_kernel.ids import ClauseId, DocumentId
from domain_kernel.vectors import Vector

MAX_EMBEDDING_CHARS: Final = 6_000


@dataclass(frozen=True, slots=True)
class ClauseToEmbed:
    """A stored clause without a vector from the run's model, with the document metadata the
    header needs."""

    clause_id: ClauseId
    document_id: DocumentId
    clause_ref: str
    text: str
    regulator: str
    doc_type: DocumentType
    external_ref: str = ""
    title: str = ""
    published_at: date | None = None


@dataclass(frozen=True, slots=True)
class EmbeddingBatch:
    """The gateway's answer to one call: the model that served it, the vector length it reports
    and one vector per text, in order."""

    model: str
    dims: int
    vectors: tuple[Vector, ...]
    input_tokens: int = 0
    trace_id: str = ""


@dataclass(frozen=True, slots=True)
class ClauseVector:
    clause_id: ClauseId
    vector: Vector


@dataclass(frozen=True, slots=True)
class EmbeddingsStored:
    """The rulebook's answer: vectors stored now, and clauses that had one from the model."""

    stored: int
    unchanged: int


def embedding_header(clause: ClauseToEmbed) -> str:
    parts = [clause.regulator.strip(), clause.doc_type.value.replace("_", " ")]
    reference = clause.external_ref.strip() or " ".join(clause.title.split())
    if reference:
        parts.append(reference)
    if clause.published_at is not None:
        parts.append(clause.published_at.isoformat())
    parts.append(f"clause {clause.clause_ref}")
    return " | ".join(part for part in parts if part)


def embedding_text(clause: ClauseToEmbed, max_chars: int = MAX_EMBEDDING_CHARS) -> str:
    """The header, a newline and the clause text, cut to ``max_chars``."""
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    text = f"{embedding_header(clause)}\n{' '.join(clause.text.split())}"
    return text[:max_chars].rstrip()
