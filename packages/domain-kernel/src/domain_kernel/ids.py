"""Typed identifiers. Each kind is its own class so ids of different things cannot be mixed.

Most ids are random (``new``). An id that two services must compute independently for the same
thing, such as a clause's, is derived instead: ``derive_id`` hashes a namespace word and the
parts that name the thing with UUID version 5, so the same inputs give the same id everywhere.
"""

import json
from dataclasses import dataclass
from typing import Final, Self
from uuid import UUID, uuid4, uuid5

from domain_kernel._validation import require_instance
from domain_kernel.errors import InvariantViolationError

ID_NAMESPACE: Final = UUID("feaad2b1-5b8c-532f-aa9a-35fe8e6538fa")
"""The UUID version 5 namespace of every derived id: ``uuid5(NAMESPACE_URL,
"urn:compliancewatch:id")``. Changing it changes every derived id."""


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
class CanonicalEntityId(EntityId):
    """A canonical entity in the knowledge tables: what clause mentions are aligned to."""


@dataclass(frozen=True, slots=True)
class DecisionId(EntityId):
    """An applicability decision."""


@dataclass(frozen=True, slots=True)
class ObligationId(EntityId):
    """An obligation created for a business."""


@dataclass(frozen=True, slots=True)
class NotificationId(EntityId):
    """One notification about one obligation to one recipient on one channel."""


@dataclass(frozen=True, slots=True)
class ConsentId(EntityId):
    """One consent record: a grant or a withdrawal."""


@dataclass(frozen=True, slots=True)
class EventId(EntityId):
    """A domain event."""


@dataclass(frozen=True, slots=True)
class CorrelationId(EntityId):
    """Ties together everything one request or workflow caused."""


def derive_id[I: EntityId](kind: type[I], namespace: str, *parts: str) -> I:
    """The id of the thing ``namespace`` and ``parts`` name, the same on every call.

    The name hashed is the compact JSON array ``[namespace, *parts]``, so parts can hold any
    text without ambiguity about where one ends. The namespace word, not the class, keys the
    hash: callers pick one word per kind of thing ("clause") and never reuse it.
    """
    words = [require_instance(namespace, str, "namespace"), *parts]
    for index, word in enumerate(words):
        if not isinstance(word, str) or not word.strip():
            raise InvariantViolationError(
                f"derive_id needs non-blank text parts, got {word!r} at position {index}"
            )
    name = json.dumps(words, ensure_ascii=False, separators=(",", ":"))
    return kind(uuid5(ID_NAMESPACE, name))
