"""In-memory stores: tests, demos and the app before Postgres.

``MemoryStore`` holds consents, tenants, users, the subject index, service clients and the
published events. A
unit of work keeps what it did only when it ends without an error, as a Postgres transaction
would, and it mirrors row-level security: it sees the rows of its own tenant, none when it has no
tenant, and refuses to write another tenant's rows.
"""

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager

from domain_kernel.events import DomainEvent
from domain_kernel.ids import TenantId, UserId
from identity.domain.channel_consent import (
    ChannelConsentRecord,
    ChannelUnitOfWork,
    ConsentChannel,
)
from identity.domain.consent import ConsentPurpose, ConsentRecord
from identity.domain.errors import InternalTenantExistsError, SubjectRegisteredError
from identity.domain.repository import UnitOfWork
from identity.domain.service_clients import ServiceClient
from identity.domain.tenancy import SubjectEntry, Tenant, TenantKind, User


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
        """``get``: memory units of work serve tests and demos, one at a time."""
        return self.get(tenant_id)


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
        self.consents = MemoryConsentRepository(self._records, tenant_id)
        self.tenants = MemoryTenantRepository(self._tenants, tenant_id)
        self.users = MemoryUserRepository(self._users, tenant_id)
        self.subjects = MemorySubjectIndex(self._subjects)
        self.service_clients = MemoryServiceClientRepository(self._clients)
        self.events = MemorySink()

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
        store.events.extend(self.events.pending)


class MemoryStore:
    def __init__(self) -> None:
        self.records: list[ConsentRecord] = []
        self.tenants: dict[TenantId, Tenant] = {}
        self.users: dict[UserId, User] = {}
        self.subjects: dict[tuple[str, str], SubjectEntry] = {}
        self.service_clients: dict[str, ServiceClient] = {}
        self.events: list[DomainEvent] = []

    def __call__(self, tenant_id: TenantId | None) -> AbstractContextManager[UnitOfWork]:
        return self._open(tenant_id)

    @contextmanager
    def _open(self, tenant_id: TenantId | None) -> Iterator[UnitOfWork]:
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
    without an error, as a Postgres transaction would."""

    def __init__(self) -> None:
        self.records: list[ChannelConsentRecord] = []

    def __call__(self) -> AbstractContextManager[ChannelUnitOfWork]:
        return self._open()

    @contextmanager
    def _open(self) -> Iterator[ChannelUnitOfWork]:
        pending = list(self.records)
        yield MemoryChannelUnitOfWork(pending)
        self.records[:] = pending
