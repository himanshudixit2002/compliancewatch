"""Who is asking: the roles people hold, the scopes service clients hold, and the principal a
verified access token names.

A person belongs to one tenant and holds roles in it (guide sections 6 and 10). A service client,
such as the pipeline or the WhatsApp bot, holds scopes instead and belongs to no tenant; it acts
for one only with ``Scope.TENANT_ACT`` and the tenant named on the request. A request with no
verified token has the anonymous principal, which is what every request has while
``CW_AUTH_MODE`` is ``header``.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Self
from uuid import UUID

from domain_kernel._validation import require_bool, require_instance, require_int, require_text
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import TenantId, UserId

MAX_CLIENT_ID_CHARS: Final = 128
"""The longest service client id a principal carries."""


class Role(StrEnum):
    """What a person may do in their tenant. Business tenants have owners, staff and compliance
    leads; CA firms have CA admins, CA staff and compliance leads; the internal tenant has the
    regulatory analysts, reviewers and admins."""

    OWNER = "owner"
    STAFF = "staff"
    CA_ADMIN = "ca_admin"
    CA_STAFF = "ca_staff"
    COMPLIANCE_LEAD = "compliance_lead"
    ANALYST = "analyst"
    REVIEWER = "reviewer"
    ADMIN = "admin"


class Scope(StrEnum):
    """What a service client may do. Scopes are granted to clients, never to people."""

    TENANT_ACT = "tenant:act"
    """Act for the tenant named in ``x-tenant-id``."""
    RULEBOOK_WRITE = "rulebook:write"
    """Write what the pipeline extracted into the rulebook."""
    NOTIFICATION_SEND = "notification:send"
    """Ask the notification service to send a message."""
    NOTIFICATION_PREFERENCES = "notification:preferences"
    """Read and change a recipient's channel preferences."""
    NOTIFICATION_RECEIPTS = "notification:receipts"
    """Report delivery receipts from a channel."""
    LLM_CALL = "llm:call"
    """Call a model through the LLM gateway."""
    IDENTITY_CHANNEL_CONSENTS = "identity:channel-consents"
    """Record consents given on a messaging channel."""
    ENTITLEMENTS_READ = "entitlements:read"
    """Read what a tenant's plan entitles it to."""
    DATA_EXPORT = "data:export"
    """Read a tenant's data for an export or erasure request."""


class PrincipalKind(StrEnum):
    """Who a principal is: a signed-in person, a service client, or nobody verified."""

    USER = "user"
    SERVICE = "service"
    ANONYMOUS = "anonymous"


TENANT_MEMBER_ROLES: Final = frozenset(
    {Role.OWNER, Role.STAFF, Role.CA_ADMIN, Role.CA_STAFF, Role.COMPLIANCE_LEAD}
)
"""Roles of people in a customer tenant, a business or a CA firm."""
TENANT_ADMIN_ROLES: Final = frozenset({Role.OWNER, Role.CA_ADMIN})
"""Roles that manage a customer tenant's users."""
REGULATORY_ROLES: Final = frozenset({Role.ANALYST, Role.REVIEWER, Role.ADMIN})
"""Roles of the internal tenant, who curate the rulebook every tenant reads."""
MFA_REQUIRED_ROLES: Final = frozenset({Role.ANALYST, Role.REVIEWER, Role.ADMIN, Role.CA_ADMIN})
"""Roles that sign in only with a second factor."""


@dataclass(frozen=True, slots=True)
class Principal:
    """The caller of one request, as a verified access token names it.

    - A user has a user id as ``subject``, a tenant, roles and no scopes.
    - A service has its client id as ``subject``, scopes, no roles and no tenant.
    - The anonymous principal has nothing: no subject, tenant, roles or scopes.

    ``mfa`` says the person signed in with a second factor. ``session_version`` is the user's
    session version when the token was issued; changing the user's roles or disabling the user
    bumps it, which revokes older tokens where the version is checked.
    """

    kind: PrincipalKind
    subject: str = ""
    tenant_id: TenantId | None = None
    roles: frozenset[Role] = frozenset()
    scopes: frozenset[Scope] = frozenset()
    mfa: bool = False
    session_version: int = 0

    def __post_init__(self) -> None:
        require_instance(self.kind, PrincipalKind, "kind")
        require_instance(self.subject, str, "subject")
        if self.tenant_id is not None:
            require_instance(self.tenant_id, TenantId, "tenant_id")
        _require_members(self.roles, Role, "roles")
        _require_members(self.scopes, Scope, "scopes")
        require_bool(self.mfa, "mfa")
        require_int(self.session_version, "session_version", minimum=0)
        if self.kind is PrincipalKind.USER:
            self._check_user()
        elif self.kind is PrincipalKind.SERVICE:
            self._check_service()
        else:
            self._check_anonymous()

    def _check_user(self) -> None:
        _user_uuid(self.subject)
        if self.tenant_id is None:
            raise InvariantViolationError("a user principal belongs to a tenant")
        if self.scopes:
            raise InvariantViolationError("a user principal holds roles, not scopes")

    def _check_service(self) -> None:
        require_text(self.subject, "subject")
        if len(self.subject) > MAX_CLIENT_ID_CHARS:
            raise InvariantViolationError(
                f"a service client id has at most {MAX_CLIENT_ID_CHARS} characters"
            )
        if self.tenant_id is not None:
            raise InvariantViolationError(
                "a service principal belongs to no tenant; it acts for one with tenant:act"
            )
        if self.roles:
            raise InvariantViolationError("a service principal holds scopes, not roles")

    def _check_anonymous(self) -> None:
        if (
            self.subject
            or self.tenant_id is not None
            or self.roles
            or self.scopes
            or self.mfa
            or self.session_version
        ):
            raise InvariantViolationError(
                "the anonymous principal has no subject, tenant, roles, scopes or session"
            )

    @classmethod
    def user(
        cls,
        user_id: UserId,
        tenant_id: TenantId,
        roles: Iterable[Role],
        *,
        mfa: bool = False,
        session_version: int = 0,
    ) -> Self:
        """A person signed in to ``tenant_id``."""
        require_instance(user_id, UserId, "user_id")
        return cls(
            PrincipalKind.USER,
            subject=str(user_id),
            tenant_id=tenant_id,
            roles=frozenset(roles),
            mfa=mfa,
            session_version=session_version,
        )

    @classmethod
    def service(cls, client_id: str, scopes: Iterable[Scope]) -> Self:
        """A service client holding ``scopes``."""
        return cls(PrincipalKind.SERVICE, subject=client_id, scopes=frozenset(scopes))

    @property
    def is_authenticated(self) -> bool:
        """Whether a verified token named this caller."""
        return self.kind is not PrincipalKind.ANONYMOUS

    @property
    def user_id(self) -> UserId | None:
        """The user's id, for a user principal; None otherwise."""
        if self.kind is not PrincipalKind.USER:
            return None
        return UserId(_user_uuid(self.subject))

    def has_role(self, *roles: Role) -> bool:
        """Whether the principal holds any of ``roles``."""
        return any(role in self.roles for role in roles)

    def has_scope(self, scope: Scope) -> bool:
        return scope in self.scopes

    @property
    def actor_label(self) -> str:
        """Who acted, for logs and audit rows: ``user:<uuid>``, ``service:<client>`` or
        ``anonymous``."""
        if self.kind is PrincipalKind.ANONYMOUS:
            return PrincipalKind.ANONYMOUS.value
        return f"{self.kind.value}:{self.subject}"


def _require_members(value: object, kind: type[StrEnum], name: str) -> None:
    items = require_instance(value, frozenset, name)
    for item in items:
        if not isinstance(item, kind):
            raise InvariantViolationError(f"{name} must hold {kind.__name__} members, got {item!r}")


def _user_uuid(subject: str) -> UUID:
    """The user id a user principal's subject names, in its canonical text form."""
    text = require_text(subject, "subject")
    try:
        value = UUID(text)
    except ValueError:
        value = None
    if value is None or str(value) != text:
        raise InvariantViolationError(f"a user principal's subject is its user id, got {text!r}")
    return value


ANONYMOUS: Final = Principal(PrincipalKind.ANONYMOUS)
"""The caller of a request that carries no verified token."""
