"""In-memory preferences, sent log and event sink: tests, demos and the app before Postgres."""

from datetime import datetime

from domain_kernel.channels import Channel
from domain_kernel.dedupe import DedupeKey
from domain_kernel.events import DomainEvent
from notification.domain.preferences import ChannelPreference
from py_common.logging import get_logger

log = get_logger(__name__)


class MemoryPreferences:
    def __init__(self) -> None:
        self._items: dict[tuple[Channel, str], ChannelPreference] = {}

    def get(self, channel: Channel, recipient: str) -> ChannelPreference | None:
        return self._items.get((channel, recipient))

    def save(self, preference: ChannelPreference) -> None:
        self._items[(preference.channel, preference.recipient)] = preference

    def ping(self) -> bool:
        return True


class MemorySentLog:
    def __init__(self) -> None:
        self.sent: dict[DedupeKey, datetime] = {}

    def seen(self, dedupe_key: DedupeKey) -> bool:
        return dedupe_key in self.sent

    def record(self, dedupe_key: DedupeKey, at: datetime) -> None:
        self.sent[dedupe_key] = at


class LogEventSink:
    """Logs the event until the service writes to an outbox table (its migration is pending)."""

    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    def publish(self, event: DomainEvent) -> None:
        self.events.append(event)
        log.info("event.published", topic=type(event).topic, event_id=str(event.event_id))
