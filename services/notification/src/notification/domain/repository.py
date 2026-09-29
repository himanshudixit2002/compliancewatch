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
  lease, then handles each in a unit of work of the entry's tenant, where it completes or
  reschedules the entry together with the notification.
"""

from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

from domain_kernel._validation import require_aware, require_instance
from domain_kernel.channels import Channel
from domain_kernel.dedupe import DedupeKey
from domain_kernel.events import DomainEvent
from domain_kernel.ids import BusinessId, NotificationId, ObligationId, TenantId
from notification.domain.ids import DispatchId, RecipientId
from notification.domain.notification import DeliveryState, Notification
from notification.domain.preferences import ChannelPreference, Suppression
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

    def purge(self, before: datetime) -> int:
        """Delete the notifications created before ``before``; returns how many."""
        ...

    def strip_params(self, before: datetime) -> int:
        """Empty the template values of notifications created before ``before``; returns how
        many had values."""
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

    def __post_init__(self) -> None:
        require_instance(self.id, NotificationId, "id")
        require_instance(self.tenant_id, TenantId, "tenant_id")
        require_instance(self.kind, WorkKind, "kind")
        require_aware(self.available_at, "available_at")

    @classmethod
    def of(cls, notification: Notification) -> "WorkEntry":
        """The entry of a pending notification."""
        kind = (
            WorkKind.DIGEST_ITEM
            if notification.state is DeliveryState.DIGEST_PENDING
            else WorkKind.ITEM
        )
        return cls(notification.id, notification.tenant_id, kind, notification.available_at)


class WorkQueue(Protocol):
    """The work queue entries of the unit of work's notifications, written in its transaction."""

    def add(self, entry: WorkEntry) -> None: ...

    def complete(self, notification_id: NotificationId, *, provider_message_id: str = "") -> None:
        """Nothing more to do; the provider's message id stays to route its receipts."""
        ...

    def reschedule(self, notification_id: NotificationId, available_at: datetime) -> None:
        """Due again at ``available_at``; the lease ends."""
        ...


class WorkIndex(Protocol):
    """The work queue across tenants; each call is a transaction of its own."""

    def claim(self, *, limit: int, now: datetime, lease: timedelta) -> Sequence[WorkEntry]:
        """Lease at most ``limit`` pending entries due at ``now``, oldest first, for ``lease``.
        Concurrent claims never return one entry twice; an entry whose lease ran out without
        being completed or rescheduled can be claimed again."""
        ...

    def tenant_for_provider_message(self, provider_message_id: str) -> TenantId | None: ...

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
    """One transaction of one tenant."""

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


class UnitOfWorkFactory(Protocol):
    def __call__(self, tenant_id: TenantId) -> AbstractContextManager[UnitOfWork]: ...

    def shared(self) -> AbstractContextManager[SharedUnitOfWork]: ...
