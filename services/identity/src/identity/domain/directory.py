"""The tenant directory: what the regulatory team's admin reads of every tenant at once.

Row-level security shows a unit of work one tenant. The admin tenant list
(``GET /v1/identity/admin/tenants``) reads across tenants through ``TenantDirectory`` instead: in
Postgres the SECURITY DEFINER function ``identity.tenant_directory()`` owned by the NOLOGIN role
``cw_identity_directory`` (``infra/dev/postgres/roles.sql``), which answers the columns of a
``TenantSummary`` and nothing else: never a token, an email address or a phone number. The users
of one tenant are read in a unit of work of that tenant, audited with a reason
(``identity.application.admin``), not through the directory.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol

from domain_kernel._validation import require_aware, require_instance, require_int
from domain_kernel.ids import TenantId
from identity.domain.billing import SubscriptionStatus
from identity.domain.tenancy import TenantKind, TenantStatus

MAX_QUERY_CHARS: Final = 200
"""The longest search text the list takes: a tenant's name is at most that long."""
MAX_PAGE: Final = 200
"""The most tenants one page lists (``py_common.pagination.MAX_LIMIT``)."""


@dataclass(frozen=True, slots=True)
class TenantSummary:
    """One tenant as the directory lists it: the tenant's own facts, the plan key and status of
    its newest subscription (None without one; what the plan entitles the tenant to is the
    entitlements route's business), and how many users it has, how many of them active."""

    id: TenantId
    kind: TenantKind
    name: str
    status: TenantStatus
    created_at: datetime
    plan_key: str | None
    subscription_status: SubscriptionStatus | None
    users: int
    active_users: int

    def __post_init__(self) -> None:
        require_instance(self.id, TenantId, "id")
        require_instance(self.kind, TenantKind, "kind")
        require_instance(self.name, str, "name")
        require_instance(self.status, TenantStatus, "status")
        require_aware(self.created_at, "created_at")
        if self.plan_key is not None:
            require_instance(self.plan_key, str, "plan_key")
        if self.subscription_status is not None:
            require_instance(self.subscription_status, SubscriptionStatus, "subscription_status")
        require_int(self.users, "users", minimum=0)
        require_int(self.active_users, "active_users", minimum=0)


class TenantDirectory(Protocol):
    def page(self, query: str, after: TenantId | None, limit: int) -> list[TenantSummary]:
        """At most ``limit`` tenants in the order of (name, id), after the tenant ``after``
        names (None: from the first). ``query`` keeps the tenants whose name contains it,
        ignoring case, or whose id is it; empty keeps every tenant. A cursor naming no tenant
        reads nothing."""
        ...

    def get(self, tenant_id: TenantId) -> TenantSummary | None:
        """One tenant, whatever its status; None when identity has none by that id."""
        ...
