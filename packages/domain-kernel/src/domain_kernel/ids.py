"""Typed identifiers. Each kind is its own class so ids of different things cannot be mixed."""

from dataclasses import dataclass
from typing import Self
from uuid import UUID, uuid4

from domain_kernel._validation import require_instance
from domain_kernel.errors import InvariantViolationError


@dataclass(frozen=True, slots=True)
class EntityId:
    """A UUID wrapped in the class of the thing it identifies."""

    value: UUID

    def __post_init__(self) -> None:
        require_instance(self.value, UUID, f"{self.__class__.__name__}.value")

    @classmethod
    def new(cls) -> Self:
        """A fresh random id."""
        return cls(uuid4())

    @classmethod
    def parse(cls, text: str) -> Self:
        """Build the id from its string form."""
        try:
            return cls(UUID(text))
        except ValueError as exc:
            raise InvariantViolationError(f"{cls.__name__} must be a UUID, got {text!r}") from exc

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class TenantId(EntityId):
    """A tenant: the unit of data isolation."""


@dataclass(frozen=True, slots=True)
class UserId(EntityId):
    """A person who signs in."""


@dataclass(frozen=True, slots=True)
class BusinessId(EntityId):
    """A business whose profile rules are evaluated against."""


@dataclass(frozen=True, slots=True)
class SourceId(EntityId):
    """A regulatory source the pipeline watches."""


@dataclass(frozen=True, slots=True)
class DocumentId(EntityId):
    """A document fetched from a source."""


@dataclass(frozen=True, slots=True)
class ClauseId(EntityId):
    """A clause inside a parsed document."""


@dataclass(frozen=True, slots=True)
class CandidateId(EntityId):
    """A rule candidate the extractor produced."""


@dataclass(frozen=True, slots=True)
class RuleId(EntityId):
    """A rule: the aggregate that owns its versions."""


@dataclass(frozen=True, slots=True)
class RuleVersionId(EntityId):
    """One version of a rule."""


@dataclass(frozen=True, slots=True)
class DecisionId(EntityId):
    """An applicability decision."""


@dataclass(frozen=True, slots=True)
class ObligationId(EntityId):
    """An obligation created for a business."""


@dataclass(frozen=True, slots=True)
class EventId(EntityId):
    """A domain event."""


@dataclass(frozen=True, slots=True)
class CorrelationId(EntityId):
    """Ties together everything one request or workflow caused."""
