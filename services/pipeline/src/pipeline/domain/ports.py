"""What the pipeline needs from the services it hands work to, as protocols. The adapters live
in ``infrastructure`` (HTTP) and ``testing`` (memory)."""

from typing import Protocol

from domain_kernel.documents import ParsedDocument
from domain_kernel.ids import DocumentId
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
