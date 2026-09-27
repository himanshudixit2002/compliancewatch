"""Error types every domain layer raises. Each carries a stable problem type slug.

The slug becomes the ``type`` of a problem-details response; the title is its default message.
Errors that only one service can raise (supersession, citation, approver rules) live there.
"""

from typing import ClassVar

PROBLEM_TYPE_PREFIX = "urn:compliancewatch:problem:"


class DomainError(Exception):
    """Base of the kernel's errors."""

    type_slug: ClassVar[str] = "domain-error"
    title: ClassVar[str] = "Domain error"

    def __init__(self, detail: str = "") -> None:
        self.detail = detail or self.title
        super().__init__(self.detail)

    @property
    def type_uri(self) -> str:
        """Problem type URI: the shared prefix followed by the slug."""
        return PROBLEM_TYPE_PREFIX + self.type_slug


class InvariantViolationError(DomainError, ValueError):
    """A value object was given data that breaks one of its rules."""

    type_slug = "invariant-violation"
    title = "Invariant violation"


class OntologyDefinitionError(DomainError, ValueError):
    """An attribute definition or the ontology as a whole is malformed."""

    type_slug = "ontology-definition-invalid"
    title = "Ontology definition is invalid"


class UnknownAttributeError(DomainError, LookupError):
    """A predicate or profile names an attribute the ontology does not define."""

    type_slug = "unknown-attribute"
    title = "Unknown attribute"

    def __init__(self, attribute: str, detail: str = "") -> None:
        self.attribute = attribute
        super().__init__(detail or f"unknown attribute {attribute!r}")


class InvalidAttributeValueError(DomainError, ValueError):
    """A value does not fit the attribute's type, allowed values or bounds."""

    type_slug = "invalid-attribute-value"
    title = "Invalid attribute value"

    def __init__(self, attribute: str, detail: str) -> None:
        self.attribute = attribute
        self.reason = detail
        super().__init__(f"{attribute}: {detail}")


class InvalidOperatorError(DomainError, ValueError):
    """The operator cannot be applied to attributes of this type."""

    type_slug = "invalid-operator"
    title = "Invalid operator"

    def __init__(self, attribute: str, operator: str, attribute_type: str) -> None:
        self.attribute = attribute
        self.operator = operator
        self.attribute_type = attribute_type
        super().__init__(
            f"operator {operator!r} is not allowed on {attribute_type} attribute {attribute!r}"
        )


class InvalidTransitionError(DomainError):
    """A status change the transition table does not allow."""

    type_slug = "invalid-transition"
    title = "Invalid status transition"

    def __init__(self, current: str, new: str) -> None:
        self.current = current
        self.new = new
        super().__init__(f"cannot move from {current!r} to {new!r}")


class UnknownClosureReasonError(DomainError, ValueError):
    """A closure reason outside the ClosureReason enum."""

    type_slug = "unknown-closure-reason"
    title = "Unknown closure reason"

    def __init__(self, reason: object) -> None:
        self.reason = reason
        super().__init__(f"unknown closure reason {reason!r}")
