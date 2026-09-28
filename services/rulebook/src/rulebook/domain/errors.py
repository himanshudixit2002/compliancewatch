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


class UnknownClauseError(DomainError, ValueError):
    type_slug = "rulebook-clause-not-found"
    title = "Clause not in this document"


class MentionSpanMismatchError(DomainError, ValueError):
    """The mention's text is not what the clause holds at its span: the spans would point at
    the wrong characters, so the whole submission is refused."""

    type_slug = "rulebook-mention-span-mismatch"
    title = "Mention span does not match the clause text"


class NonCanonicalNameError(DomainError, ValueError):
    type_slug = "rulebook-name-not-canonical"
    title = "Entity name is not canonical"


class ReviewGroupNotFoundError(DomainError, LookupError):
    type_slug = "rulebook-review-group-not-found"
    title = "No open review items for this name"


class ReviewGroupClosedError(DomainError, ValueError):
    type_slug = "rulebook-review-group-closed"
    title = "Review items already decided"


class UnknownEntityError(DomainError, LookupError):
    type_slug = "rulebook-entity-not-found"
    title = "Canonical entity not found"


class EntityTypeMismatchError(DomainError, ValueError):
    type_slug = "rulebook-entity-type-mismatch"
    title = "Entity type does not match the mention"


class CandidateNotFoundError(DomainError, LookupError):
    type_slug = "rulebook-relation-candidate-not-found"
    title = "Relation candidate not found"


class CandidateClosedError(DomainError, ValueError):
    type_slug = "rulebook-relation-candidate-closed"
    title = "Relation candidate already decided"


class TargetUnresolvedError(DomainError, ValueError):
    """The candidate points at an entity that alignment has not resolved yet: decide the
    entity review for its name first, or name a target rule version."""

    type_slug = "rulebook-relation-target-unresolved"
    title = "Relation target not aligned to an entity"


class TargetVersionRequiredError(DomainError, ValueError):
    type_slug = "rulebook-target-version-required"
    title = "This relation needs a target rule version"


class UnknownRuleVersionError(DomainError, LookupError):
    type_slug = "rulebook-rule-version-not-found"
    title = "Rule version not found"


class RuleVersionNotEditableError(DomainError, ValueError):
    """Relations are approved together with the version they start from, before it is
    published; a published, superseded or withdrawn version does not change."""

    type_slug = "rulebook-rule-version-not-editable"
    title = "Rule version is past approval"


class SupersessionCycleError(DomainError, ValueError):
    type_slug = "rulebook-supersession-cycle"
    title = "Supersession would form a cycle"


class ClauseNotStoredError(DomainError, LookupError):
    """No clause has this id. ``UnknownClauseError`` is the other case: a clause ref that is
    not in the document a request names."""

    type_slug = "rulebook-clause-unknown"
    title = "Clause not stored"
