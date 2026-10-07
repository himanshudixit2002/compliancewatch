"""The identity service's unit of work: consents, tenants, users, the subject index, service
clients, the billing ledger, the data requests, the events and the audit entries, in one
transaction.

``UnitOfWorkFactory(tenant_id)`` opens a transaction for one tenant: row-level security admits
that tenant's rows only (and, on the tenant table, the tenant itself). ``tenant_id=None`` opens
one without a tenant, in which tenant rows are invisible and cannot be written; it serves the
subject index, which the session exchange reads before it knows the tenant, and the service
clients, which belong to no tenant.
"""

from contextlib import AbstractContextManager
from typing import Protocol

from domain_kernel.audit import AuditSink
from domain_kernel.events import DomainEvent
from domain_kernel.ids import TenantId, UserId
from identity.domain.billing import BillingRepository
from identity.domain.consent import ConsentRepository
from identity.domain.data_requests import DataRequestRepository
from identity.domain.service_clients import ServiceClientRepository
from identity.domain.tenancy import SubjectEntry, Tenant, User


class TenantRepository(Protocol):
    def add(self, tenant: Tenant) -> None: ...

    def get(self, tenant_id: TenantId) -> Tenant | None:
        """The unit of work's own tenant when it has this id; None for any other."""
        ...

    def lock(self, tenant_id: TenantId) -> Tenant | None:
        """``get``, with the tenant locked until the unit of work ends: a second unit of work
        locking it waits, then reads what the first committed."""
        ...


class UserRepository(Protocol):
    def add(self, user: User) -> None: ...

    def save(self, user: User) -> None:
        """Store the changed roles, status, display name and session version of ``user``."""
        ...

    def get(self, user_id: UserId) -> User | None:
        """The user with this id in the unit of work's tenant; None for another tenant's."""
        ...

    def list(self) -> list[User]:
        """The tenant's users, oldest first."""
        ...


class SubjectIndex(Protocol):
    def add(self, entry: SubjectEntry) -> None:
        """Record ``entry``; ``SubjectRegisteredError`` when the provider's subject is taken."""
        ...

    def find(self, provider: str, provider_subject: str) -> SubjectEntry | None: ...


class EventSink(Protocol):
    def publish(self, event: DomainEvent) -> None:
        """Write ``event`` to the outbox; it commits or rolls back with the unit of work."""
        ...


class UnitOfWork(Protocol):
    @property
    def consents(self) -> ConsentRepository: ...

    @property
    def tenants(self) -> TenantRepository: ...

    @property
    def users(self) -> UserRepository: ...

    @property
    def subjects(self) -> SubjectIndex: ...

    @property
    def service_clients(self) -> ServiceClientRepository: ...

    @property
    def billing(self) -> BillingRepository:
        """The tenant's billing ledger; with no tenant it holds nothing and refuses writes."""
        ...

    @property
    def data_requests(self) -> DataRequestRepository:
        """The tenant's data requests; with no tenant it holds nothing and refuses writes."""
        ...

    @property
    def events(self) -> EventSink: ...

    @property
    def audit(self) -> AuditSink:
        """Where the unit's audit entries go (``audit.event``): an entry of the unit's tenant,
        or of no tenant; they commit or roll back with the unit."""
        ...


class UnitOfWorkFactory(Protocol):
    def __call__(self, tenant_id: TenantId | None) -> AbstractContextManager[UnitOfWork]: ...
