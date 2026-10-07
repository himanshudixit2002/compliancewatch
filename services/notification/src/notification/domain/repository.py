"""What the application layer needs from persistence, as protocols the infrastructure implements.

Two kinds of data live side by side. Consents and suppressions are keyed by address and belong
to no tenant: an opt-out typed on WhatsApp arrives before anyone knows which tenant the number
belongs to, and must be honoured for all of them. Notifications belong to one tenant, and the
unit of work of that tenant sees only its own (row-level security in Postgres).

- ``UnitOfWorkFactory(tenant_id)`` opens one transaction for a tenant: its recipients and
  notifications, the work queue entries of those notifications, the event sink (the outbox),
  and the consents, suppressions and directory entries of every address. Leaving the block
  cleanly commits; an exception rolls back.
- ``UnitOfWorkFactory.shared()`` opens one transaction with no tenant, for consents,
  suppressions and the address directory only.
- The address directory routes an address to the tenants and recipients that registered it.
  Registering a recipient replaces its entries in the same transaction as the recipient.
- ``WorkIndex`` is the queue of work across tenants: the dispatcher claims due entries with a
  lease, renews the lease just before each message it sends, and handles each entry in a unit
  of work of the entry's tenant, where it completes or reschedules the entry together with the
  notification. Each entry keeps the moment it was planned to go out (``planned_at``), which a
  retry or a rulebook outage does not move, so how long pending work has waited past it can be
  read across tenants (``WorkIndex.oldest_due``).
- A tenant's data export reads its recipients, its notifications and the preferences of the
  addresses its recipients hold, each a page at a time (``export_*``), in a tenant unit.
"""

from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from domain_kernel._validation import require_aware, require_instance, require_text
from domain_kernel.audit import AuditSink
from domain_kernel.channels import Channel
from domain_kernel.dedupe import DedupeKey
from domain_kernel.events import DomainEvent
from domain_kernel.ids import BusinessId, NotificationId, ObligationId, TenantId
from notification.domain.ids import DispatchId, RecipientId
from notification.domain.notification import DeliveryState, Notification
from notification.domain.preferences import (
    ChannelPreference,
    ConsentSource,
    QuietHours,
    Suppression,
)
from notification.domain.recipients import Recipient, RecipientAddress


class EventSink(Protocol):
    """Where events go inside the transaction: the outbox."""

    def publish(self, event: DomainEvent) -> None: ...


class PreferenceRepository(Protocol):
    """Consent per channel and normalised address, and when the address last wrote to us."""

    def get(self, channel: Channel, address: str) -> ChannelPreference | None:
        """The recorded opt-in or opt-out; None when the address never gave either."""
        ...

    def save(self, preference: ChannelPreference) -> None:
        """Record the consent, keeping the last inbound time."""
        ...

    def last_inbound_at(self, channel: Channel, address: str) -> datetime | None:
        """When the address last wrote to us: WhatsApp's 24-hour customer service window
        opens then."""
        ...

    def record_inbound(self, channel: Channel, address: str, at: datetime) -> None:
        """The address wrote to us at ``at``; an older time than the one recorded is ignored."""
        ...


class SuppressionRepository(Protocol):
    def get(self, channel: Channel, address: str) -> Suppression | None: ...

    def add(self, suppression: Suppression) -> None:
        """Close the address; a second suppression of it replaces the first."""
        ...

    def remove(self, channel: Channel, address: str) -> bool:
        """Lift the suppression; False when there was none."""
        ...


@dataclass(frozen=True, slots=True)
class PageAfter:
    """Where a page of notifications starts: after this one, newest first."""

    created_at: datetime
    notification_id: NotificationId

    def __post_init__(self) -> None:
        require_aware(self.created_at, "created_at")
        require_instance(self.notification_id, NotificationId, "notification_id")


@dataclass(frozen=True, slots=True)
class ExportAfter:
    """Where a page of a data export starts: after the row created at ``created_at`` with the id
    ``id``, oldest first."""

    created_at: datetime
    id: UUID

    def __post_init__(self) -> None:
        require_aware(self.created_at, "created_at")
        require_instance(self.id, UUID, "id")


@dataclass(frozen=True, slots=True)
class PreferenceRecord:
    """A channel_preference row as a data export shows it: the consent, when one was given
    (``opted_in``, ``source`` and ``updated_at`` are None for an address that only wrote to us),
    and when the address last wrote to us."""

    channel: Channel
    address: str
    opted_in: bool | None
    source: ConsentSource | None
    language: str
    quiet_hours: QuietHours
    updated_at: datetime | None
    last_inbound_at: datetime | None

    def __post_init__(self) -> None:
        require_instance(self.channel, Channel, "channel")
        require_text(self.address, "address")
        if self.source is not None:
            require_instance(self.source, ConsentSource, "source")
        require_text(self.language, "language")
        require_instance(self.quiet_hours, QuietHours, "quiet_hours")
        for name in ("updated_at", "last_inbound_at"):
            moment = getattr(self, name)
            if moment is not None:
                require_aware(moment, name)

    @property
    def key(self) -> tuple[Channel, str]:
        """Where the next page starts: preferences are read by channel, then address."""
        return (self.channel, self.address)


class NotificationRepository(Protocol):
    """The notifications of the unit of work's tenant."""

    def add_if_absent(self, notification: Notification) -> bool:
        """Insert unless a notification with its id or its dedupe key exists (of any tenant);
        False means nothing was written. Two units racing with one key write one row."""
        ...

    def get(self, notification_id: NotificationId) -> Notification | None: ...

    def by_dedupe_key(self, dedupe_key: DedupeKey) -> Notification | None: ...

    def save(self, notification: Notification) -> None:
        """Write the changed notification over the stored one."""
        ...

    def due_for(
        self, recipient_id: RecipientId, channel: Channel, now: datetime
    ) -> Sequence[Notification]:
        """The recipient's pending notifications on ``channel`` available at ``now``, oldest
        first: what one dispatch may coalesce."""
        ...

    def by_dispatch(self, dispatch_id: DispatchId) -> Sequence[Notification]:
        """The notifications one delivery carried."""
        ...

    def by_provider_message(self, provider_message_id: str) -> Sequence[Notification]:
        """The notifications the provider's message carried."""
        ...

    def latest_params(self, obligation_id: ObligationId) -> Mapping[str, object] | None:
        """The template values of the obligation's newest notification that still has them."""
        ...

    def page(
        self,
        business_id: BusinessId,
        *,
        state: DeliveryState | None = None,
        limit: int,
        after: PageAfter | None = None,
    ) -> Sequence[Notification]:
        """The business's notifications, newest first (by creation, then id), at most
        ``limit``, starting after ``after``."""
        ...

    def export_notifications(self, after: ExportAfter | None, limit: int) -> Sequence[Notification]:
        """The tenant's notifications oldest first (by creation, then id), at most ``limit``,
        starting after ``after``: a page of its data export."""
        ...

    def purge(self, before: datetime) -> int:
        """Delete the notifications created before ``before``; returns how many."""
        ...

    def strip_params(self, before: datetime) -> int:
        """Empty the template values of notifications created before ``before`` that are no
        longer pending; returns how many had values. A pending notification keeps them, since it
        cannot go out without them."""
        ...


class RecipientRepository(Protocol):
    """The recipients of the unit of work's tenant."""

    def get(self, recipient_id: RecipientId) -> Recipient | None: ...

    def save(self, recipient: Recipient) -> None:
        """Insert the recipient or write it over the stored one, its addresses and business
        links included."""
        ...

    def delete(self, recipient_id: RecipientId) -> bool:
        """Remove the recipient with its addresses and links; False when there was none."""
        ...

    def for_business(self, business_id: BusinessId) -> Sequence[Recipient]:
        """The recipients that follow the business, by id."""
        ...

    def page(
        self, business_id: BusinessId, *, limit: int, after: RecipientId | None = None
    ) -> Sequence[Recipient]:
        """The recipients that follow the business, by id, at most ``limit``, starting after
        the id ``after`` (a recipient removed since still marks the place)."""
        ...

    def export_recipients(self, after: ExportAfter | None, limit: int) -> Sequence[Recipient]:
        """The tenant's recipients oldest first (by creation, then id), with their addresses and
        businesses, at most ``limit``, starting after ``after``: a page of its data export."""
        ...

    def export_preferences(
        self, after: tuple[Channel, str] | None, limit: int
    ) -> Sequence[PreferenceRecord]:
        """The preferences of the addresses the tenant's recipients hold, by channel and
        address, at most ``limit``, starting after the key ``after``. Preferences belong to no
        tenant, so they are selected by those addresses; no other address's is read."""
        ...


@dataclass(frozen=True, slots=True)
class DirectoryEntry:
    """One tenant's recipient at an address."""

    tenant_id: TenantId
    recipient_id: RecipientId

    def __post_init__(self) -> None:
        require_instance(self.tenant_id, TenantId, "tenant_id")
        require_instance(self.recipient_id, RecipientId, "recipient_id")


class AddressDirectory(Protocol):
    """Which tenants' recipients registered an address, across tenants."""

    def replace(
        self, tenant_id: TenantId, recipient_id: RecipientId, addresses: Sequence[RecipientAddress]
    ) -> None:
        """The recipient's entries become exactly ``addresses``."""
        ...

    def remove(self, tenant_id: TenantId, recipient_id: RecipientId) -> None: ...

    def lookup(self, channel: Channel, address: str) -> Sequence[DirectoryEntry]:
        """Every recipient at the normalised address, by tenant and recipient id."""
        ...


class WorkKind(StrEnum):
    ITEM = "item"
    """A notification that goes out on its own or in a batch."""
    DIGEST_ITEM = "digest_item"
    """A notification that goes out in the recipient's digest."""


@dataclass(frozen=True, slots=True)
class WorkEntry:
    """A notification's place in the work queue."""

    id: NotificationId
    """The notification's id."""
    tenant_id: TenantId
    kind: WorkKind
    available_at: datetime
    """When a dispatcher may take it next."""
    planned_at: datetime
    """When it was planned to go out: when it was queued to go (after the batching window, at
    the digest time) or when quiet hours ended. A retry's backoff and a rulebook outage put
    ``available_at`` back but leave this, so the time the notification waits past it is delay:
    the delivery lag and the age of the oldest pending work count from it."""
    lease_until: datetime | None = None
    """The end of the lease its holder took it under (a claim, or a send that queued it leased
    to itself); None for an entry nobody holds. A holder proves the entry is still its own by
    this value (``WorkIndex.renew``)."""

    def __post_init__(self) -> None:
        require_instance(self.id, NotificationId, "id")
        require_instance(self.tenant_id, TenantId, "tenant_id")
        require_instance(self.kind, WorkKind, "kind")
        require_aware(self.available_at, "available_at")
        require_aware(self.planned_at, "planned_at")
        if self.lease_until is not None:
            require_aware(self.lease_until, "lease_until")

    @classmethod
    def of(cls, notification: Notification, *, lease_until: datetime | None = None) -> "WorkEntry":
        """The entry of a pending notification, planned for its ``available_at`` and leased to
        the caller until ``lease_until``."""
        kind = (
            WorkKind.DIGEST_ITEM
            if notification.state is DeliveryState.DIGEST_PENDING
            else WorkKind.ITEM
        )
        return cls(
            notification.id,
            notification.tenant_id,
            kind,
            notification.available_at,
            notification.available_at,
            lease_until,
        )


class WorkQueue(Protocol):
    """The work queue entries of the unit of work's notifications, written in its transaction."""

    def add(self, entry: WorkEntry) -> None:
        """Queue the entry; one with a ``lease_until`` is leased to the caller until then, as a
        claim would lease it, so that no dispatcher takes it meanwhile."""
        ...

    def complete(self, notification_id: NotificationId, *, provider_message_id: str = "") -> None:
        """Nothing more to do; the provider's message id stays to route its receipts."""
        ...

    def reschedule(
        self, notification_id: NotificationId, available_at: datetime, *, delay: bool = False
    ) -> None:
        """Due again at ``available_at``; the lease ends. With ``delay`` the entry waits because
        an attempt failed or the rulebook could not answer, and keeps its ``planned_at``;
        otherwise (quiet hours, a resend) ``available_at`` becomes its planned moment too."""
        ...


class WorkIndex(Protocol):
    """The work queue across tenants; each call is a transaction of its own."""

    def claim(self, *, limit: int, now: datetime, lease: timedelta) -> Sequence[WorkEntry]:
        """Lease at most ``limit`` pending entries due at ``now``, oldest first, for ``lease``;
        each comes back with the end of its lease. Concurrent claims never return one entry
        twice; an entry whose lease ran out without being completed or rescheduled can be
        claimed again."""
        ...

    def renew(
        self, entries: Sequence[WorkEntry], *, now: datetime, lease: timedelta
    ) -> Sequence[WorkEntry] | None:
        """Extend the lease of ``entries`` to ``now + lease`` when the caller still holds every
        one of them: each is pending under the lease it came with (``lease_until``). Returns
        them, in order, under the new lease. None, changing nothing, when one was claimed by
        another dispatcher since, completed, rescheduled or deleted. A lease the caller let run
        out is renewed as long as no other dispatcher claimed the entry meanwhile."""
        ...

    def tenant_for_provider_message(self, provider_message_id: str) -> TenantId | None: ...

    def oldest_due(self, now: datetime) -> datetime | None:
        """The earliest ``planned_at`` at or before ``now`` among pending entries: the moment
        the pending work that has waited longest was planned to go out. None when no pending
        entry's moment has come."""
        ...

    def tenants(self) -> Sequence[TenantId]:
        """Every tenant with work entries or registered addresses."""
        ...


class SharedUnitOfWork(Protocol):
    """One transaction without a tenant: consents, suppressions and the address directory."""

    @property
    def preferences(self) -> PreferenceRepository: ...

    @property
    def suppressions(self) -> SuppressionRepository: ...

    @property
    def directory(self) -> AddressDirectory: ...


class UnitOfWork(SharedUnitOfWork, Protocol):
    """One transaction of one tenant; its audit entries (``audit.event``) commit or roll back
    with the rest."""

    @property
    def tenant_id(self) -> TenantId: ...

    @property
    def recipients(self) -> RecipientRepository: ...

    @property
    def notifications(self) -> NotificationRepository: ...

    @property
    def work(self) -> WorkQueue: ...

    @property
    def events(self) -> EventSink: ...

    @property
    def audit(self) -> AuditSink: ...


class UnitOfWorkFactory(Protocol):
    def __call__(self, tenant_id: TenantId) -> AbstractContextManager[UnitOfWork]: ...

    def shared(self) -> AbstractContextManager[SharedUnitOfWork]: ...
