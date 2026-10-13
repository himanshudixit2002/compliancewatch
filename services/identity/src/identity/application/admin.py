"""The regulatory team's admin reads of other tenants: the tenant list, one tenant, and a
tenant's users, which need a reason and are audited.

Every tenant's data belongs to that tenant, and row-level security shows a unit of work one
tenant. An admin of the internal tenant reads across them in two ways:

- ``ListTenants`` and ``ReadTenant`` answer ``TenantSummary`` rows through the ``TenantDirectory``
  (``identity.domain.directory``), which names no person: the tenant, its plan and its counts.
- ``ReadTenantUsers`` opens a unit of work of the tenant asked about, reads its users with their
  roles and writes ``tenant.users_read`` to that tenant's audit trail in the same unit, with the
  reason the admin gave, the tenant id, the admin as the actor and how many users were read:
  no name, address or number. The tenant's owners see the read in their trail
  (``GET /v1/identity/audit``), as they see every actor on their data. A read without a reason
  never gets here: the route refuses it (422).

The caller is checked as the support requests are checked (``internal_admin``): a verified token
naming an active admin of the internal tenant whose session is current. The anonymous caller of
header mode passes, as it does on every route (nothing is verified in header mode); outside
header mode the routes refuse a request without a token.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Final

from domain_kernel.access import Principal, PrincipalKind, Role
from domain_kernel.audit import AuditEntry
from domain_kernel.events import utc_now
from domain_kernel.ids import TenantId
from identity.application.audit import audit_entry
from identity.application.sessions import check_session
from identity.domain.directory import MAX_PAGE, TenantDirectory, TenantSummary
from identity.domain.errors import TenantNotFoundError
from identity.domain.repository import UnitOfWork, UnitOfWorkFactory
from identity.domain.tenancy import TenantKind, User
from py_common.auth.errors import AuthForbiddenError

USERS_READ: Final = "tenant.users_read"
"""The audit action of an admin's read of a tenant's users."""


def internal_admin(uow: UnitOfWork, actor: Principal) -> User | None:
    """The admin of the internal tenant a verified token names, with a current session; None
    for the anonymous caller of header mode. Anyone else is refused (403)."""
    if not actor.is_authenticated:
        return None
    if actor.kind is not PrincipalKind.USER or actor.tenant_id is None:
        raise AuthForbiddenError("the admin reads answer for the regulatory team's admin")
    tenant, user = check_session(uow, actor)
    if tenant.kind is not TenantKind.INTERNAL or Role.ADMIN not in user.roles:
        raise AuthForbiddenError("the admin reads answer for the regulatory team's admin")
    return user


class ListTenants:
    def __init__(self, unit_of_work: UnitOfWorkFactory, directory: TenantDirectory) -> None:
        self._unit_of_work = unit_of_work
        self._directory = directory

    def run(
        self, actor: Principal, *, query: str = "", after: TenantId | None = None, limit: int
    ) -> list[TenantSummary]:
        """At most ``limit`` tenants (up to ``MAX_PAGE``) after ``after``, matching ``query``."""
        if not 1 <= limit <= MAX_PAGE:
            raise ValueError(f"limit must be 1 to {MAX_PAGE}, got {limit}")
        with self._unit_of_work(actor.tenant_id) as uow:
            internal_admin(uow, actor)
        return self._directory.page(query, after, limit)


class ReadTenant:
    def __init__(self, unit_of_work: UnitOfWorkFactory, directory: TenantDirectory) -> None:
        self._unit_of_work = unit_of_work
        self._directory = directory

    def run(self, actor: Principal, tenant_id: TenantId) -> TenantSummary:
        """One tenant's summary; ``TenantNotFoundError`` when identity has none by that id."""
        with self._unit_of_work(actor.tenant_id) as uow:
            internal_admin(uow, actor)
        found = self._directory.get(tenant_id)
        if found is None:
            raise TenantNotFoundError()
        return found


class ReadTenantUsers:
    def __init__(
        self, unit_of_work: UnitOfWorkFactory, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run(self, actor: Principal, tenant_id: TenantId, *, reason: str) -> list[User]:
        """The users of ``tenant_id`` with their roles, oldest first, and the ``tenant.users_read``
        entry in that tenant's trail. ``TenantNotFoundError`` when identity has no such tenant;
        a reason is required."""
        if not reason.strip():
            raise ValueError("reading a tenant's users needs a reason")
        with self._unit_of_work(actor.tenant_id) as uow:
            internal_admin(uow, actor)
        with self._unit_of_work(tenant_id) as uow:
            tenant = uow.tenants.get(tenant_id)
            if tenant is None:
                raise TenantNotFoundError()
            users = [user for user in uow.users.list() if user.tenant_id == tenant_id]
            uow.audit.write(_users_read_entry(tenant_id, actor, reason, len(users), self._clock()))
        return users


def _users_read_entry(
    tenant_id: TenantId, actor: Principal, reason: str, count: int, at: datetime
) -> AuditEntry:
    """The read, in the trail of the tenant whose users were read: who, why and how many, and
    nothing of the users themselves."""
    return audit_entry(
        USERS_READ,
        tenant_id=tenant_id,
        subject_type="tenant",
        subject_id=str(tenant_id),
        at=at,
        after={"users": count},
        reason=reason,
        principal=actor,
    )
