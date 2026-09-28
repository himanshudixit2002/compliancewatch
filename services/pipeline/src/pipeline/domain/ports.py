"""What the pipeline needs from the services it hands work to, as protocols. The adapters live
in ``infrastructure`` (HTTP) and ``testing`` (memory)."""

from typing import Protocol

from pipeline.domain.knowledge import DocumentRecord, RegisteredDocument


class KnowledgeSink(Protocol):
    """Where parsed regulator documents go: the rulebook."""

    def register_document(self, record: DocumentRecord) -> RegisteredDocument:
        """Store the document and its clauses; idempotent for the same parse. Raises
        ``RulebookConflictError`` for a different parse of stored bytes."""
        ...
