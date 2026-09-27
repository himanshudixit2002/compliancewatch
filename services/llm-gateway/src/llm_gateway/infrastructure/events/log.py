"""Publish events as log lines. Kafka takes over once the first consumer exists."""

import dataclasses

from domain_kernel.events import DomainEvent
from py_common.logging import get_logger

log = get_logger(__name__)

ENVELOPE_FIELDS = frozenset(
    {"event_id", "occurred_at", "tenant_id", "correlation_id", "causation_id"}
)
"""What every event carries; the payload is everything else."""


class LogPublisher:
    def publish(self, event: DomainEvent) -> None:
        payload = {
            field.name: _stringify(getattr(event, field.name))
            for field in dataclasses.fields(event)
            if field.name not in ENVELOPE_FIELDS
        }
        log.info(
            "event.published",
            topic=type(event).topic,
            event_id=str(event.event_id),
            occurred_at=event.occurred_at.isoformat(),
            tenant_id=None if event.tenant_id is None else str(event.tenant_id),
            correlation_id=str(event.correlation_id),
            causation_id=None if event.causation_id is None else str(event.causation_id),
            payload=payload,
        )


def _stringify(value: object) -> object:
    """Strings for scalars; a nested dataclass (the ledger entry) becomes a dict of strings."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {field.name: str(getattr(value, field.name)) for field in dataclasses.fields(value)}
    return str(value)
