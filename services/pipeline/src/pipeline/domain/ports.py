"""What the pipeline needs from the services it hands work to, as protocols. The adapters live
in ``infrastructure`` (HTTP) and ``testing`` (memory)."""

from collections.abc import Mapping, Sequence
from typing import Protocol

from domain_kernel.documents import ParsedDocument
from domain_kernel.ids import ClauseId, DocumentId
from pipeline.domain.embedding import ClauseToEmbed, ClauseVector, EmbeddingBatch, EmbeddingsStored
from pipeline.domain.knowledge import (
    AlignmentReport,
    DocumentRecord,
    MentionSubmission,
    RegisteredDocument,
    RelationSubmission,
    RuleKey,
    StagingReport,
)


class KnowledgeSink(Protocol):
    """Where parsed regulator documents and the knowledge found in them go: the rulebook."""

    def register_document(self, record: DocumentRecord) -> RegisteredDocument:
        """Store the document and its clauses; idempotent for the same parse. Raises
        ``RulebookConflictError`` for a different parse of stored bytes."""
        ...

    def submit_mentions(self, submission: MentionSubmission) -> AlignmentReport:
        """Align the mentions; the ones that do not resolve go to the review queue."""
        ...

    def submit_relations(self, submission: RelationSubmission) -> StagingReport:
        """Stage the proposed relations as candidates for review; idempotent per proposal."""
        ...


class RulebookReader(Protocol):
    """What the extraction stages read back from the rulebook."""

    def parsed_document(self, document_id: DocumentId) -> ParsedDocument:
        """The stored document with its clauses, as the kernel's ``ParsedDocument``."""
        ...

    def known_rules(self) -> tuple[RuleKey, ...]:
        """The rules a relation may name as the one it affects."""
        ...


class Embedder(Protocol):
    """Vectors for texts, through the llm-gateway's retrieval feature."""

    def embed(
        self,
        inputs: Sequence[str],
        *,
        model: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> EmbeddingBatch:
        """One vector per input, in order. ``model`` overrides the gateway's retrieval route;
        ``metadata`` tags the call's trace."""
        ...


class ClauseIndexSink(Protocol):
    """The rulebook's clause search index, as far as the pipeline fills it."""

    def unembedded_clauses(
        self,
        model: str,
        *,
        document_id: DocumentId | None = None,
        limit: int = 64,
        after: ClauseId | None = None,
    ) -> tuple[ClauseToEmbed, ...]:
        """Stored clauses with no vector from ``model``, in clause id order after ``after``;
        of one document, or of every document."""
        ...

    def put_embeddings(
        self, model: str, dims: int, items: Sequence[ClauseVector]
    ) -> EmbeddingsStored:
        """Store the vectors under ``model``; a clause that has one from it keeps it."""
        ...
