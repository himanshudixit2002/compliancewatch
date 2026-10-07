"""The in-memory store: every repository of the service for tests, demos and local runs.

``MemoryStore`` behaves like the Postgres units of work where the use cases can tell: a unit
works on a copy of the store and replaces it only when the block exits cleanly, so a failed unit
leaves nothing behind; a tenant unit sees only its tenant's recipients and notifications, as
row-level security would show them; dedupe keys and ids are unique across tenants; and events
are published only when their unit commits. Units run one at a time, which stands in for the
database's locks. Committed events go to ``LogEventSink``, which keeps and logs them, and committed
audit entries to ``MemoryStore.audit``.
"""

import threading
from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from uuid import UUID

from domain_kernel.audit import AuditEntry
from domain_kernel.channels import Channel
from domain_kernel.dedupe import DedupeKey
from domain_kernel.events import DomainEvent
from domain_kernel.ids import BusinessId, NotificationId, ObligationId, TenantId
from notification.domain.ids import DispatchId, RecipientId
from notification.domain.notification import DeliveryState, Notification
from notification.domain.policy import WORK_LEASE
from notification.domain.preferences import DEFAULT_QUIET_HOURS, ChannelPreference, Suppression
from notification.domain.recipients import Recipient, RecipientAddress
from notification.domain.repository import (
    DirectoryEntry,
    ExportAfter,
    PageAfter,
    PreferenceRecord,
    SharedUnitOfWork,
    UnitOfWork,
    WorkEntry,
)
from py_common.audit import MemoryAuditSink
from py_common.logging import get_logger

log = get_logger(__name__)

type AddressKey = tuple[Channel, str]
type DirectoryKey = tuple[Channel, str, TenantId, RecipientId]


class LogEventSink:
    """Keeps and logs every event it is given: the memory store's outbox."""

    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    def publish(self, event: DomainEvent) -> None:
        self.events.append(event)
        log.info("event.published", topic=type(event).topic, event_id=str(event.event_id))


@dataclass(frozen=True, slots=True)
class WorkRow:
    entry: WorkEntry
    status: str = "pending"
    lease_until: datetime | None = None
    provider_message_id: str = ""


@dataclass(slots=True)
class MemoryState:
    """Everything the store holds; a unit works on a copy."""

    preferences: dict[AddressKey, ChannelPreference] = field(default_factory=dict)
    inbound: dict[AddressKey, datetime] = field(default_factory=dict)
    suppressions: dict[AddressKey, Suppression] = field(default_factory=dict)
    notifications: dict[NotificationId, Notification] = field(default_factory=dict)
    work: dict[NotificationId, WorkRow] = field(default_factory=dict)
    recipients: dict[tuple[TenantId, RecipientId], Recipient] = field(default_factory=dict)
    directory: set[DirectoryKey] = field(default_factory=set)

    def copy(self) -> "MemoryState":
        return MemoryState(
            preferences=dict(self.preferences),
            inbound=dict(self.inbound),
            suppressions=dict(self.suppressions),
            notifications=dict(self.notifications),
            work=dict(self.work),
            recipients=dict(self.recipients),
            directory=set(self.directory),
        )


class MemoryPreferenceRepository:
    def __init__(self, state: MemoryState) -> None:
        self._state = state

    def get(self, channel: Channel, address: str) -> ChannelPreference | None:
        return self._state.preferences.get((channel, address))

    def save(self, preference: ChannelPreference) -> None:
        self._state.preferences[(preference.channel, preference.address)] = preference

    def last_inbound_at(self, channel: Channel, address: str) -> datetime | None:
        return self._state.inbound.get((channel, address))

    def record_inbound(self, channel: Channel, address: str, at: datetime) -> None:
        known = self._state.inbound.get((channel, address))
        self._state.inbound[(channel, address)] = at if known is None else max(known, at)


class MemorySuppressionRepository:
    def __init__(self, state: MemoryState) -> None:
        self._state = state

    def get(self, channel: Channel, address: str) -> Suppression | None:
        return self._state.suppressions.get((channel, address))

    def add(self, suppression: Suppression) -> None:
        self._state.suppressions[(suppression.channel, suppression.address)] = suppression

    def remove(self, channel: Channel, address: str) -> bool:
        return self._state.suppressions.pop((channel, address), None) is not None


class MemoryRecipientRepository:
    def __init__(self, state: MemoryState, tenant_id: TenantId) -> None:
        self._state = state
        self._tenant_id = tenant_id

    def get(self, recipient_id: RecipientId) -> Recipient | None:
        return self._state.recipients.get((self._tenant_id, recipient_id))

    def save(self, recipient: Recipient) -> None:
        if recipient.tenant_id != self._tenant_id:
            raise ValueError(f"recipient {recipient.id} belongs to another tenant")
        self._state.recipients[(self._tenant_id, recipient.id)] = recipient

    def delete(self, recipient_id: RecipientId) -> bool:
        return self._state.recipients.pop((self._tenant_id, recipient_id), None) is not None

    def for_business(self, business_id: BusinessId) -> Sequence[Recipient]:
        found = [
            recipient
            for (tenant_id, _), recipient in self._state.recipients.items()
            if tenant_id == self._tenant_id and recipient.follows(business_id)
        ]
        return sorted(found, key=lambda recipient: recipient.id.value)

    def page(
        self, business_id: BusinessId, *, limit: int, after: RecipientId | None = None
    ) -> Sequence[Recipient]:
        found = self.for_business(business_id)
        if after is not None:
            found = [recipient for recipient in found if recipient.id.value > after.value]
        return found[:limit]

    def _mine(self) -> list[Recipient]:
        return [
            recipient
            for (tenant_id, _), recipient in self._state.recipients.items()
            if tenant_id == self._tenant_id
        ]

    def export_recipients(self, after: ExportAfter | None, limit: int) -> Sequence[Recipient]:
        found = sorted(self._mine(), key=_created_key)
        if after is not None:
            found = [r for r in found if _created_key(r) > (after.created_at, after.id)]
        return found[:limit]

    def export_preferences(
        self, after: tuple[Channel, str] | None, limit: int
    ) -> Sequence[PreferenceRecord]:
        held = {
            (address.channel, address.address)
            for recipient in self._mine()
            for address in recipient.addresses
        }
        keys = sorted(
            (key for key in held if key in self._state.preferences or key in self._state.inbound),
            key=_address_key,
        )
        if after is not None:
            keys = [key for key in keys if _address_key(key) > _address_key(after)]
        return [self._record(key) for key in keys[:limit]]

    def _record(self, key: AddressKey) -> PreferenceRecord:
        preference = self._state.preferences.get(key)
        return PreferenceRecord(
            channel=key[0],
            address=key[1],
            opted_in=None if preference is None else preference.opted_in,
            source=None if preference is None else preference.source,
            language="en" if preference is None else preference.language,
            quiet_hours=DEFAULT_QUIET_HOURS if preference is None else preference.quiet_hours,
            updated_at=None if preference is None else preference.updated_at,
            last_inbound_at=self._state.inbound.get(key),
        )


def _created_key(recipient: Recipient) -> tuple[datetime, UUID]:
    return (recipient.created_at, recipient.id.value)


def _address_key(key: AddressKey) -> tuple[str, str]:
    """Channel by its value, then address: the order Postgres reads them in."""
    return (key[0].value, key[1])


class MemoryAddressDirectory:
    def __init__(self, state: MemoryState) -> None:
        self._state = state

    def replace(
        self, tenant_id: TenantId, recipient_id: RecipientId, addresses: Sequence[RecipientAddress]
    ) -> None:
        self.remove(tenant_id, recipient_id)
        for address in addresses:
            self._state.directory.add((address.channel, address.address, tenant_id, recipient_id))

    def remove(self, tenant_id: TenantId, recipient_id: RecipientId) -> None:
        self._state.directory -= {
            key for key in self._state.directory if key[2:] == (tenant_id, recipient_id)
        }

    def lookup(self, channel: Channel, address: str) -> Sequence[DirectoryEntry]:
        found = [
            DirectoryEntry(tenant_id, recipient_id)
            for (key_channel, key_address, tenant_id, recipient_id) in self._state.directory
            if key_channel is channel and key_address == address
        ]
        return sorted(found, key=lambda entry: (entry.tenant_id.value, entry.recipient_id.value))


class MemoryNotificationRepository:
    def __init__(self, state: MemoryState, tenant_id: TenantId) -> None:
        self._state = state
        self._tenant_id = tenant_id

    def _mine(self) -> list[Notification]:
        return [n for n in self._state.notifications.values() if n.tenant_id == self._tenant_id]

    def add_if_absent(self, notification: Notification) -> bool:
        if notification.tenant_id != self._tenant_id:
            raise ValueError(f"notification {notification.id} belongs to another tenant")
        taken = notification.id in self._state.notifications or any(
            n.dedupe_key == notification.dedupe_key for n in self._state.notifications.values()
        )
        if taken:
            return False
        self._state.notifications[notification.id] = notification
        return True

    def get(self, notification_id: NotificationId) -> Notification | None:
        found = self._state.notifications.get(notification_id)
        return found if found is not None and found.tenant_id == self._tenant_id else None

    def by_dedupe_key(self, dedupe_key: DedupeKey) -> Notification | None:
        return next((n for n in self._mine() if n.dedupe_key == dedupe_key), None)

    def save(self, notification: Notification) -> None:
        if self.get(notification.id) is None:
            return
        self._state.notifications[notification.id] = notification

    def due_for(
        self, recipient_id: RecipientId, channel: Channel, now: datetime
    ) -> Sequence[Notification]:
        due = [
            n
            for n in self._mine()
            if n.recipient_id == recipient_id
            and n.channel is channel
            and n.is_pending
            and n.available_at <= now
        ]
        return sorted(due, key=lambda n: (n.available_at, n.created_at, n.id.value))

    def by_dispatch(self, dispatch_id: DispatchId) -> Sequence[Notification]:
        return _oldest_first(n for n in self._mine() if n.dispatch_id == dispatch_id)

    def by_provider_message(self, provider_message_id: str) -> Sequence[Notification]:
        if not provider_message_id:
            return []
        return _oldest_first(
            n for n in self._mine() if n.provider_message_id == provider_message_id
        )

    def latest_params(self, obligation_id: ObligationId) -> Mapping[str, object] | None:
        found = [n for n in self._mine() if n.obligation_id == obligation_id and n.params]
        if not found:
            return None
        return max(found, key=_newest_key).params

    def page(
        self,
        business_id: BusinessId,
        *,
        state: DeliveryState | None = None,
        limit: int,
        after: PageAfter | None = None,
    ) -> Sequence[Notification]:
        found = [
            n
            for n in self._mine()
            if n.business_id == business_id
            and (state is None or n.state is state)
            and (after is None or _newest_key(n) < (after.created_at, after.notification_id.value))
        ]
        return sorted(found, key=_newest_key, reverse=True)[:limit]

    def export_notifications(self, after: ExportAfter | None, limit: int) -> Sequence[Notification]:
        found = _oldest_first(
            n
            for n in self._mine()
            if after is None or _newest_key(n) > (after.created_at, after.id)
        )
        return found[:limit]

    def purge(self, before: datetime) -> int:
        old = [n.id for n in self._mine() if n.created_at < before]
        for notification_id in old:
            del self._state.notifications[notification_id]
            self._state.work.pop(notification_id, None)
        return len(old)

    def strip_params(self, before: datetime) -> int:
        stripped = [
            n for n in self._mine() if n.created_at < before and n.params and not n.is_pending
        ]
        for notification in stripped:
            self._state.notifications[notification.id] = replace(notification, params={})
        return len(stripped)


def _newest_key(notification: Notification) -> tuple[datetime, UUID]:
    return (notification.created_at, notification.id.value)


def _oldest_first(found: Iterator[Notification]) -> list[Notification]:
    return sorted(found, key=_newest_key)


class MemoryWorkQueue:
    def __init__(self, state: MemoryState, tenant_id: TenantId) -> None:
        self._state = state
        self._tenant_id = tenant_id

    def add(self, entry: WorkEntry) -> None:
        if entry.tenant_id != self._tenant_id:
            raise ValueError(f"work entry {entry.id} belongs to another tenant")
        if entry.id not in self._state.notifications:
            raise ValueError(f"work entry {entry.id} has no notification")
        if entry.id in self._state.work:
            raise ValueError(f"duplicate work entry {entry.id}")
        self._state.work[entry.id] = WorkRow(
            replace(entry, lease_until=None), lease_until=entry.lease_until
        )

    def complete(self, notification_id: NotificationId, *, provider_message_id: str = "") -> None:
        row = self._state.work.get(notification_id)
        if row is not None:
            self._state.work[notification_id] = replace(
                row, status="done", lease_until=None, provider_message_id=provider_message_id
            )

    def reschedule(
        self, notification_id: NotificationId, available_at: datetime, *, delay: bool = False
    ) -> None:
        row = self._state.work.get(notification_id)
        if row is not None:
            planned_at = row.entry.planned_at if delay else available_at
            self._state.work[notification_id] = replace(
                row,
                entry=replace(row.entry, available_at=available_at, planned_at=planned_at),
                status="pending",
                lease_until=None,
            )


class MemoryEventSink:
    """Events of one unit, published by the store when the unit commits."""

    def __init__(self) -> None:
        self.pending: list[DomainEvent] = []

    def publish(self, event: DomainEvent) -> None:
        self.pending.append(event)


class MemorySharedUnitOfWork:
    def __init__(self, state: MemoryState) -> None:
        self.preferences = MemoryPreferenceRepository(state)
        self.suppressions = MemorySuppressionRepository(state)
        self.directory = MemoryAddressDirectory(state)


class MemoryUnitOfWork(MemorySharedUnitOfWork):
    def __init__(
        self, state: MemoryState, tenant_id: TenantId, audit: list[AuditEntry] | None = None
    ) -> None:
        super().__init__(state)
        self.tenant_id = tenant_id
        self.recipients = MemoryRecipientRepository(state, tenant_id)
        self.notifications = MemoryNotificationRepository(state, tenant_id)
        self.work = MemoryWorkQueue(state, tenant_id)
        self.events = MemoryEventSink()
        self.audit = MemoryAuditSink([] if audit is None else audit, tenant_id=tenant_id)


class MemoryWorkIndex:
    def __init__(self, store: "MemoryStore") -> None:
        self._store = store

    def claim(
        self, *, limit: int, now: datetime, lease: timedelta = WORK_LEASE
    ) -> Sequence[WorkEntry]:
        if limit < 1:
            raise ValueError(f"limit must be at least 1, got {limit}")
        with self._store.lock:
            work = self._store.state.work
            due = sorted(
                (
                    row
                    for row in work.values()
                    if row.status == "pending"
                    and row.entry.available_at <= now
                    and (row.lease_until is None or row.lease_until <= now)
                ),
                key=lambda row: (row.entry.available_at, row.entry.id.value),
            )[:limit]
            lease_until = now + lease
            for row in due:
                work[row.entry.id] = replace(row, lease_until=lease_until)
            return [replace(row.entry, lease_until=lease_until) for row in due]

    def renew(
        self, entries: Sequence[WorkEntry], *, now: datetime, lease: timedelta
    ) -> Sequence[WorkEntry] | None:
        with self._store.lock:
            work = self._store.state.work
            for entry in entries:
                row = work.get(entry.id)
                if (
                    row is None
                    or row.status != "pending"
                    or entry.lease_until is None
                    or row.lease_until != entry.lease_until
                ):
                    return None
            renewed = [replace(entry, lease_until=now + lease) for entry in entries]
            for entry in renewed:
                work[entry.id] = replace(work[entry.id], lease_until=entry.lease_until)
            return renewed

    def tenant_for_provider_message(self, provider_message_id: str) -> TenantId | None:
        if not provider_message_id:
            return None
        with self._store.lock:
            return next(
                (
                    row.entry.tenant_id
                    for row in self._store.state.work.values()
                    if row.provider_message_id == provider_message_id
                ),
                None,
            )

    def oldest_due(self, now: datetime) -> datetime | None:
        with self._store.lock:
            return min(
                (
                    row.entry.planned_at
                    for row in self._store.state.work.values()
                    if row.status == "pending" and row.entry.planned_at <= now
                ),
                default=None,
            )

    def tenants(self) -> Sequence[TenantId]:
        with self._store.lock:
            state = self._store.state
            found = {row.entry.tenant_id for row in state.work.values()}
            found |= {tenant_id for (_, _, tenant_id, _) in state.directory}
        return sorted(found, key=lambda tenant: tenant.value)


class MemoryStore:
    """Holds every tenant's data and the published events; makes units of work."""

    def __init__(self, *, sink: LogEventSink | None = None) -> None:
        self.state = MemoryState()
        self.lock = threading.RLock()
        self.sink = sink or LogEventSink()
        self.work_index = MemoryWorkIndex(self)
        self.audit: list[AuditEntry] = []

    @property
    def events(self) -> list[DomainEvent]:
        """Every event a committed unit published, in order."""
        return self.sink.events

    def ping(self) -> bool:
        return True

    def __call__(self, tenant_id: TenantId) -> AbstractContextManager[UnitOfWork]:
        return self._unit(tenant_id)

    def shared(self) -> AbstractContextManager[SharedUnitOfWork]:
        return self._shared()

    @contextmanager
    def _unit(self, tenant_id: TenantId) -> Iterator[UnitOfWork]:
        with self.lock:
            working = self.state.copy()
            unit = MemoryUnitOfWork(working, tenant_id, self.audit)
            yield unit
            self.state = working
            unit.audit.commit()
            for event in unit.events.pending:
                self.sink.publish(event)

    @contextmanager
    def _shared(self) -> Iterator[SharedUnitOfWork]:
        with self.lock:
            working = self.state.copy()
            yield MemorySharedUnitOfWork(working)
            self.state = working

    def notifications_of(self, tenant_id: TenantId) -> list[Notification]:
        """The tenant's notifications, oldest first: a read for tests and demos."""
        return _oldest_first(
            n for n in self.state.notifications.values() if n.tenant_id == tenant_id
        )

    def work_row(self, notification_id: NotificationId) -> WorkRow | None:
        return self.state.work.get(notification_id)
