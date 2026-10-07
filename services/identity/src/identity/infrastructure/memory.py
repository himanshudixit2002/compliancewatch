"""In-memory stores: tests, demos and the app before Postgres.

``MemoryStore`` holds consents, tenants, users, the subject index, service clients, the billing
ledger (``billing``), the data requests (``data_requests``), the published events and the audit log
(``audit``, masked as ``audit.event`` keeps it). A unit of work keeps what it did only when it ends
without an error, as a Postgres transaction would, and it mirrors row-level security: it sees the
rows of its own tenant, none when it has no tenant, and refuses to write another tenant's rows (an
audit entry of no tenant is allowed). A unit works on a copy of the store, so units run one at a
time (a store-level lock held from open to commit or rollback): two overlapping requests, of one
tenant or of two, cannot both start from the same copy and lose each other's writes.
``MemoryChannelStore`` does the same for channel consents, and ``MemoryDataRequestDirectory``
counts every tenant's open data requests as ``identity.data_requests_open()`` does.
"""

import threading
from collections.abc import Callable, Iterable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import replace
from datetime import datetime
from uuid import UUID

from domain_kernel.audit import AuditEntry
from domain_kernel.events import DomainEvent
from domain_kernel.ids import TenantId, UserId
from identity.domain.audit import AuditQuery, AuditScope, newest_first_key, readable
from identity.domain.billing import Customer, StartAttempt, StoredBillingEvent, Subscription
from identity.domain.channel_consent import (
    ChannelConsentRecord,
    ChannelUnitOfWork,
    ConsentChannel,
)
from identity.domain.consent import ConsentPurpose, ConsentRecord
from identity.domain.data_requests import (
    DataRequest,
    DataRequestId,
    DataRequestKind,
    OpenRequests,
    counts_by_kind,
)
from identity.domain.errors import InternalTenantExistsError, SubjectRegisteredError
from identity.domain.pages import ExportAfter
from identity.domain.repository import UnitOfWork
from identity.domain.service_clients import ServiceClient
from identity.domain.tenancy import SubjectEntry, Tenant, TenantKind, User
from py_common.audit import MemoryAuditSink


class RowSecurityViolationError(RuntimeError):
    """A unit of work wrote a row of a tenant other than its own, which Postgres refuses."""


def _require_tenant(own: TenantId | None, row_tenant: TenantId) -> None:
    if own != row_tenant:
        raise RowSecurityViolationError(
            f"a unit of work for tenant {own} cannot write a row of tenant {row_tenant}"
        )


class MemoryConsentRepository:
    def __init__(self, records: list[ConsentRecord], tenant_id: TenantId | None) -> None:
        self._records = records
        self._tenant = tenant_id

    def add(self, record: ConsentRecord) -> None:
        _require_tenant(self._tenant, record.tenant_id)
        self._records.append(record)

    def history(self, subject: str, purpose: ConsentPurpose | None = None) -> list[ConsentRecord]:
        return [
            r
            for r in self._records
            if r.tenant_id == self._tenant
            and r.subject == subject
            and (purpose is None or r.purpose is purpose)
        ]

    def page(self, after: ExportAfter | None, limit: int) -> list[ConsentRecord]:
        mine = [r for r in self._records if r.tenant_id == self._tenant]
        return _page(mine, lambda r: (r.recorded_at, r.id.value), after, limit)


class MemoryDataRequestRepository:
    def __init__(
        self, requests: dict[DataRequestId, DataRequest], tenant_id: TenantId | None
    ) -> None:
        self._requests = requests
        self._tenant = tenant_id

    def add(self, request: DataRequest) -> None:
        _require_tenant(self._tenant, request.tenant_id)
        if request.id in self._requests:
            raise RowSecurityViolationError(f"data request {request.id} exists already")
        self._requests[request.id] = request

    def save(self, request: DataRequest) -> None:
        _require_tenant(self._tenant, request.tenant_id)
        self._requests[request.id] = request

    def get(self, request_id: DataRequestId) -> DataRequest | None:
        found = self._requests.get(request_id)
        return found if found is not None and found.tenant_id == self._tenant else None

    def page(self, after: ExportAfter | None, limit: int) -> list[DataRequest]:
        return _page(self.list(), lambda r: (r.requested_at, r.id.value), after, limit)

    def lock(self, request_id: DataRequestId) -> DataRequest | None:
        """``get``: memory units of work run one at a time, so the row is already locked."""
        return self.get(request_id)

    def list(self) -> list[DataRequest]:
        mine = [r for r in self._requests.values() if r.tenant_id == self._tenant]
        return sorted(mine, key=lambda r: (r.requested_at, r.id.value), reverse=True)

    def open_deletion(self) -> DataRequest | None:
        """The newest deletion request not completed; already locked, as ``lock`` is."""
        for request in self.list():
            if request.is_deletion and not request.is_completed:
                return request
        return None


def _page[T](
    rows: Iterable[T],
    key: Callable[[T], tuple[datetime, UUID]],
    after: ExportAfter | None,
    limit: int,
) -> list[T]:
    """Up to ``limit`` of ``rows`` oldest first by ``key``, after ``after``: as Postgres pages."""
    ordered = sorted(rows, key=key)
    if after is not None:
        ordered = [row for row in ordered if key(row) > (after.at, after.id)]
    return ordered[:limit]


class MemoryTenantRepository:
    def __init__(self, tenants: dict[TenantId, Tenant], tenant_id: TenantId | None) -> None:
        self._tenants = tenants
        self._tenant = tenant_id

    def add(self, tenant: Tenant) -> None:
        _require_tenant(self._tenant, tenant.id)
        if tenant.id in self._tenants:
            raise RowSecurityViolationError(f"tenant {tenant.id} exists already")
        if tenant.kind is TenantKind.INTERNAL and any(
            other.kind is TenantKind.INTERNAL for other in self._tenants.values()
        ):
            raise InternalTenantExistsError()
        self._tenants[tenant.id] = tenant

    def get(self, tenant_id: TenantId) -> Tenant | None:
        return self._tenants.get(tenant_id) if tenant_id == self._tenant else None

    def lock(self, tenant_id: TenantId) -> Tenant | None:
        """``get``: memory units of work run one at a time, so the row is already locked."""
        return self.get(tenant_id)

    def save(self, tenant: Tenant) -> None:
        if tenant.id == self._tenant and tenant.id in self._tenants:
            self._tenants[tenant.id] = tenant


class MemoryUserRepository:
    def __init__(self, users: dict[UserId, User], tenant_id: TenantId | None) -> None:
        self._users = users
        self._tenant = tenant_id

    def add(self, user: User) -> None:
        _require_tenant(self._tenant, user.tenant_id)
        self._users[user.id] = user

    def save(self, user: User) -> None:
        self.add(user)

    def get(self, user_id: UserId) -> User | None:
        user = self._users.get(user_id)
        return user if user is not None and user.tenant_id == self._tenant else None

    def page(self, after: ExportAfter | None, limit: int) -> list[User]:
        return _page(self.list(), lambda user: (user.created_at, user.id.value), after, limit)

    def list(self) -> list[User]:
        mine = [user for user in self._users.values() if user.tenant_id == self._tenant]
        return sorted(mine, key=lambda user: (user.created_at, user.id.value))


class MemorySubjectIndex:
    def __init__(self, entries: dict[tuple[str, str], SubjectEntry]) -> None:
        self._entries = entries

    def add(self, entry: SubjectEntry) -> None:
        key = (entry.provider, entry.provider_subject)
        if key in self._entries:
            raise SubjectRegisteredError()
        self._entries[key] = entry

    def find(self, provider: str, provider_subject: str) -> SubjectEntry | None:
        return self._entries.get((provider, provider_subject))


class MemoryServiceClientRepository:
    def __init__(self, clients: dict[str, ServiceClient]) -> None:
        self._clients = clients

    def add(self, client: ServiceClient) -> None:
        if client.client_id in self._clients:
            raise RowSecurityViolationError(f"service client {client.client_id} exists already")
        self._clients[client.client_id] = client

    def save(self, client: ServiceClient) -> None:
        self._clients[client.client_id] = client

    def get(self, client_id: str) -> ServiceClient | None:
        return self._clients.get(client_id)

    def list(self) -> list[ServiceClient]:
        return [self._clients[client_id] for client_id in sorted(self._clients)]


class MemoryBillingLedger:
    """What ``MemoryStore.billing`` holds: every tenant's customers, subscriptions and events."""

    def __init__(self) -> None:
        self.customers: dict[TenantId, tuple[Customer, str, datetime]] = {}
        self.subscriptions: dict[str, Subscription] = {}
        self.events: list[StoredBillingEvent] = []
        self.starts: dict[tuple[TenantId, str], StartAttempt] = {}

    def copy(self) -> "MemoryBillingLedger":
        other = MemoryBillingLedger()
        other.customers = dict(self.customers)
        other.subscriptions = dict(self.subscriptions)
        other.events = list(self.events)
        other.starts = dict(self.starts)
        return other


class MemoryBillingRepository:
    def __init__(self, ledger: MemoryBillingLedger, tenant_id: TenantId | None) -> None:
        self._ledger = ledger
        self._tenant = tenant_id

    def customer(self) -> Customer | None:
        found = None if self._tenant is None else self._ledger.customers.get(self._tenant)
        return None if found is None else found[0]

    def add_customer(self, customer: Customer, *, provider: str, at: datetime) -> bool:
        _require_tenant(self._tenant, customer.tenant_id)
        if customer.tenant_id in self._ledger.customers:
            return False
        self._ledger.customers[customer.tenant_id] = (customer, provider, at)
        return True

    def subscription(self, provider_subscription_id: str) -> Subscription | None:
        found = self._ledger.subscriptions.get(provider_subscription_id)
        return found if found is not None and found.tenant_id == self._tenant else None

    def subscriptions(self) -> list[Subscription]:
        mine = [s for s in self._ledger.subscriptions.values() if s.tenant_id == self._tenant]
        return sorted(mine, key=lambda s: (s.started_at, s.provider_subscription_id), reverse=True)

    def add_subscription(self, subscription: Subscription) -> bool:
        _require_tenant(self._tenant, subscription.tenant_id)
        if subscription.provider_subscription_id in self._ledger.subscriptions:
            return False
        self._ledger.subscriptions[subscription.provider_subscription_id] = subscription
        return True

    def update_subscription(self, subscription: Subscription) -> None:
        _require_tenant(self._tenant, subscription.tenant_id)
        held = self._ledger.subscriptions.get(subscription.provider_subscription_id)
        if held is not None and held.tenant_id == subscription.tenant_id:
            self._ledger.subscriptions[subscription.provider_subscription_id] = subscription

    def start_attempt(self, key: str) -> StartAttempt | None:
        return None if self._tenant is None else self._ledger.starts.get((self._tenant, key))

    def claim_start(self, attempt: StartAttempt) -> bool:
        _require_tenant(self._tenant, attempt.tenant_id)
        if (attempt.tenant_id, attempt.key) in self._ledger.starts:
            return False
        self._ledger.starts[(attempt.tenant_id, attempt.key)] = attempt
        return True

    def record_started(
        self, key: str, *, provider_subscription_id: str, checkout_url: str, at: datetime
    ) -> None:
        held = self.start_attempt(key)
        if held is not None:
            self._ledger.starts[(held.tenant_id, key)] = replace(
                held,
                provider_subscription_id=provider_subscription_id,
                checkout_url=checkout_url,
                recorded_at=at,
            )

    def release_start(self, key: str) -> None:
        if self._tenant is not None:
            self._ledger.starts.pop((self._tenant, key), None)

    def append_event(self, event: StoredBillingEvent) -> bool:
        _require_tenant(self._tenant, event.tenant_id)
        if any(
            held.tenant_id == event.tenant_id and held.body_sha256 == event.body_sha256
            for held in self._ledger.events
        ):
            return False
        self._ledger.events.append(event)
        return True

    def events_page(self, after: ExportAfter | None, limit: int) -> list[StoredBillingEvent]:
        mine = [e for e in self._ledger.events if e.tenant_id == self._tenant]
        return _page(mine, lambda e: (e.received_at, e.id), after, limit)


class MemorySink:
    def __init__(self) -> None:
        self.pending: list[DomainEvent] = []

    def publish(self, event: DomainEvent) -> None:
        self.pending.append(event)


class MemoryUnitOfWork:
    def __init__(self, store: "MemoryStore", tenant_id: TenantId | None) -> None:
        self._records = list(store.records)
        self._tenants = dict(store.tenants)
        self._users = dict(store.users)
        self._subjects = dict(store.subjects)
        self._clients = dict(store.service_clients)
        self._billing = store.billing.copy()
        self._data_requests = dict(store.data_requests)
        self.consents = MemoryConsentRepository(self._records, tenant_id)
        self.tenants = MemoryTenantRepository(self._tenants, tenant_id)
        self.users = MemoryUserRepository(self._users, tenant_id)
        self.subjects = MemorySubjectIndex(self._subjects)
        self.service_clients = MemoryServiceClientRepository(self._clients)
        self.billing = MemoryBillingRepository(self._billing, tenant_id)
        self.data_requests = MemoryDataRequestRepository(self._data_requests, tenant_id)
        self.events = MemorySink()
        self.audit = MemoryAuditSink(store.audit, tenant_id=tenant_id)

    def commit(self, store: "MemoryStore") -> None:
        store.records[:] = self._records
        store.tenants.clear()
        store.tenants.update(self._tenants)
        store.users.clear()
        store.users.update(self._users)
        store.subjects.clear()
        store.subjects.update(self._subjects)
        store.service_clients.clear()
        store.service_clients.update(self._clients)
        store.billing = self._billing
        store.data_requests.clear()
        store.data_requests.update(self._data_requests)
        store.events.extend(self.events.pending)
        self.audit.commit()


class MemoryStore:
    def __init__(self) -> None:
        self.records: list[ConsentRecord] = []
        self.tenants: dict[TenantId, Tenant] = {}
        self.users: dict[UserId, User] = {}
        self.subjects: dict[tuple[str, str], SubjectEntry] = {}
        self.service_clients: dict[str, ServiceClient] = {}
        self.billing = MemoryBillingLedger()
        self.data_requests: dict[DataRequestId, DataRequest] = {}
        self.events: list[DomainEvent] = []
        self.audit: list[AuditEntry] = []
        self._lock = threading.Lock()

    def __call__(self, tenant_id: TenantId | None) -> AbstractContextManager[UnitOfWork]:
        return self._open(tenant_id)

    @property
    def lock(self) -> threading.Lock:
        """What a unit of work holds from open to commit; an eraser holds it too."""
        return self._lock

    @contextmanager
    def _open(self, tenant_id: TenantId | None) -> Iterator[UnitOfWork]:
        with self._lock:
            uow = MemoryUnitOfWork(self, tenant_id)
            yield uow
            uow.commit(self)

    def ping(self) -> bool:
        return True


class MemoryChannelConsentRepository:
    def __init__(self, records: list[ChannelConsentRecord]) -> None:
        self._records = records

    def add(self, record: ChannelConsentRecord) -> ChannelConsentRecord:
        existing = self.by_message(record.channel, record.message_id)
        if existing is not None:
            return existing
        self._records.append(record)
        return record

    def by_message(self, channel: ConsentChannel, message_id: str) -> ChannelConsentRecord | None:
        if not message_id:
            return None
        return next(
            (r for r in self._records if r.channel is channel and r.message_id == message_id),
            None,
        )

    def history(
        self, channel: ConsentChannel, subject: str, purpose: ConsentPurpose | None = None
    ) -> list[ChannelConsentRecord]:
        return [
            r
            for r in self._records
            if r.channel is channel
            and r.subject == subject
            and (purpose is None or r.purpose is purpose)
        ]


class MemoryChannelUnitOfWork:
    def __init__(self, records: list[ChannelConsentRecord]) -> None:
        self.channel_consents = MemoryChannelConsentRepository(records)


class MemoryChannelStore:
    """Channel consents without a tenant. Records are kept only when the unit of work ends
    without an error, as a Postgres transaction would, and units run one at a time."""

    def __init__(self) -> None:
        self.records: list[ChannelConsentRecord] = []
        self._lock = threading.Lock()

    def __call__(self) -> AbstractContextManager[ChannelUnitOfWork]:
        return self._open()

    @contextmanager
    def _open(self) -> Iterator[ChannelUnitOfWork]:
        with self._lock:
            pending = list(self.records)
            yield MemoryChannelUnitOfWork(pending)
            self.records[:] = pending


class MemoryAuditReader:
    """``AuditReader`` over a ``MemoryStore``'s audit log, with the scopes the Postgres policies
    hold (``identity.domain.audit.readable``)."""

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    def page(
        self, scope: AuditScope, tenant_id: TenantId | None, query: AuditQuery
    ) -> list[AuditEntry]:
        found = [
            entry
            for entry in list(self._store.audit)
            if readable(scope, tenant_id, entry) and query.matches(entry)
        ]
        found.sort(key=newest_first_key, reverse=True)
        return found[: query.limit + 1]

    def export(self, since: datetime, until: datetime) -> Iterator[AuditEntry]:
        found = [entry for entry in list(self._store.audit) if since <= entry.occurred_at < until]
        yield from sorted(found, key=newest_first_key)


class MemoryDataRequestDirectory:
    """``DataRequestDirectory`` over a ``MemoryStore``: every tenant's requests, counted at
    ``clock()`` as ``identity.data_requests_open()`` counts them at ``now()``."""

    def __init__(self, store: MemoryStore, clock: Callable[[], datetime]) -> None:
        self._store = store
        self._clock = clock

    def open_counts(self) -> list[OpenRequests]:
        now = self._clock()
        found: dict[DataRequestKind, tuple[int, int]] = {}
        for request in list(self._store.data_requests.values()):
            if not request.is_open(now):
                continue
            open_, overdue = found.get(request.kind, (0, 0))
            found[request.kind] = (open_ + 1, overdue + int(request.is_overdue(now)))
        return counts_by_kind(
            OpenRequests(kind, open_, overdue) for kind, (open_, overdue) in found.items()
        )
