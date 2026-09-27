"""The envelope every domain event carries. Concrete events live in the services."""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar

from domain_kernel._validation import require_aware, require_instance
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import CorrelationId, EventId, TenantId

TOPIC_PATTERN = re.compile(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+")
"""Topic names are ``object.verb`` in the past tense, such as ``obligation.closed``."""

SCHEMA_VERSION_PATTERN = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
"""Payload schema versions are semver; the schema files live in ``packages/contracts/events``."""


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True, kw_only=True)
class DomainEvent:
    """Base of every event. Subclasses set ``topic`` and add their payload fields.

    ``schema_version`` names the version of the payload schema the subclass follows; a producer
    bumps it when the contract changes. A subclass that defines its own ``__post_init__`` calls
    ``DomainEvent.__post_init__(self)`` by name: zero-argument ``super()`` does not work in
    slotted dataclass methods.
    """

    topic: ClassVar[str] = ""
    schema_version: ClassVar[str] = "1.0.0"

    event_id: EventId = field(default_factory=EventId.new)
    occurred_at: datetime = field(default_factory=utc_now)
    tenant_id: TenantId | None = None
    correlation_id: CorrelationId = field(default_factory=CorrelationId.new)
    causation_id: EventId | None = None

    def __post_init__(self) -> None:
        topic = type(self).topic
        if not TOPIC_PATTERN.fullmatch(topic):
            raise InvariantViolationError(
                f"{type(self).__name__}.topic must look like object.verb, got {topic!r}"
            )
        version = type(self).schema_version
        if not SCHEMA_VERSION_PATTERN.fullmatch(version):
            raise InvariantViolationError(
                f"{type(self).__name__}.schema_version must be semver, got {version!r}"
            )
        require_instance(self.event_id, EventId, "event_id")
        require_aware(self.occurred_at, "occurred_at")
        if self.tenant_id is not None:
            require_instance(self.tenant_id, TenantId, "tenant_id")
        require_instance(self.correlation_id, CorrelationId, "correlation_id")
        if self.causation_id is not None:
            require_instance(self.causation_id, EventId, "causation_id")
