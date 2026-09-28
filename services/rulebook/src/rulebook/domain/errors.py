"""Errors of the rulebook service, with stable problem type slugs."""

from domain_kernel.errors import DomainError


class DocumentIdMismatchError(DomainError, ValueError):
    type_slug = "rulebook-document-id-mismatch"
    title = "Document id does not match its digest"


class DocumentConflictError(DomainError, ValueError):
    """The document is stored already, and the clauses submitted now differ from the stored
    ones. Documents are append-only, so the new parse is refused, never applied."""

    type_slug = "rulebook-document-conflict"
    title = "Document already stored with different clauses"


class UnknownDocumentError(DomainError, LookupError):
    type_slug = "rulebook-document-not-found"
    title = "Regulator document not found"

    def __init__(self, document_id: str) -> None:
        super().__init__(f"document {document_id} is not stored")
        self.document_id = document_id


class WriteTokenInvalidError(DomainError, PermissionError):
    type_slug = "rulebook-write-token-invalid"
    title = "Write token missing or wrong"

    def __init__(self) -> None:
        super().__init__("rulebook writes need the x-cw-write-token header with the right token")


class WritesDisabledError(DomainError, PermissionError):
    """No write token is configured, so writes are refused: the rulebook fails closed."""

    type_slug = "rulebook-writes-disabled"
    title = "Rulebook writes are not configured"

    def __init__(self) -> None:
        super().__init__("set CW_RULEBOOK_WRITE_TOKEN to accept writes")
