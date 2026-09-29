"""Tenants, their users and the roles users hold (guide sections 6 and 10).

A tenant is a business, a CA firm, or the internal tenant of the regulatory team, and it keeps
its data in one region (India). A user belongs to one tenant and signs in through the identity
provider, which knows the user by a subject; the roles a user may hold depend on the tenant's
kind. The first user of a tenant gets the kind's admin role, and a tenant never loses its last
active admin, so someone can always manage its users.

Changing a user's roles and disabling a user each bump the user's session version. The identity
service refuses access tokens that carry an older version, so the change takes effect there at
once and in the other services when the token expires.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Self

from domain_kernel._validation import require_aware, require_instance, require_int, require_text
from domain_kernel.access import MFA_REQUIRED_ROLES, TENANT_ADMIN_ROLES, Role
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import TenantId, UserId
from identity.domain.errors import LastAdminError, RoleNotAllowedError, UserDisabledError

REGIONS: Final = ("in",)
"""Where a tenant's data may be kept: India only (the data residency rule of ADR-014)."""
DEFAULT_REGION: Final = "in"
MAX_NAME_CHARS: Final = 200
MAX_PROVIDER_CHARS: Final = 32
MAX_SUBJECT_CHARS: Final = 255
MAX_EMAIL_CHARS: Final = 254
PHONE: Final = re.compile(r"\+[1-9][0-9]{7,14}")
"""A phone number in E.164 form with its plus, as the identity provider reports it."""
EMAIL: Final = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
"""An address with one @ and a dot in its domain; the provider has verified it already."""


class TenantKind(StrEnum):
    BUSINESS = "business"
    CA_FIRM = "ca_firm"
    INTERNAL = "internal"
    """The regulatory team that curates the rulebook; there is one."""


class TenantStatus(StrEnum):
    ACTIVE = "active"
    DELETION_REQUESTED = "deletion_requested"
    ERASED = "erased"


class UserStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


ALLOWED_ROLES: Final[Mapping[TenantKind, frozenset[Role]]] = MappingProxyType(
    {
        TenantKind.BUSINESS: frozenset({Role.OWNER, Role.STAFF, Role.COMPLIANCE_LEAD}),
        TenantKind.CA_FIRM: frozenset({Role.CA_ADMIN, Role.CA_STAFF, Role.COMPLIANCE_LEAD}),
        TenantKind.INTERNAL: frozenset({Role.ANALYST, Role.REVIEWER, Role.ADMIN}),
    }
)
"""The roles a user of each kind of tenant may hold."""

FIRST_ROLE: Final[Mapping[TenantKind, Role]] = MappingProxyType(
    {
        TenantKind.BUSINESS: Role.OWNER,
        TenantKind.CA_FIRM: Role.CA_ADMIN,
        TenantKind.INTERNAL: Role.ADMIN,
    }
)
"""The role of a tenant's first user: the kind's admin role."""

ADMIN_ROLES: Final[Mapping[TenantKind, frozenset[Role]]] = MappingProxyType(
    {kind: roles & (TENANT_ADMIN_ROLES | {Role.ADMIN}) for kind, roles in ALLOWED_ROLES.items()}
)
"""The roles that manage a tenant's users: owner, CA admin, or admin in the internal tenant."""


def requires_mfa(roles: Iterable[Role]) -> bool:
    """Whether a user holding ``roles`` must sign in with a second factor."""
    return any(role in MFA_REQUIRED_ROLES for role in roles)


def allowed_roles(kind: TenantKind, roles: Iterable[Role]) -> frozenset[Role]:
    """``roles`` as a set, when a user of a ``kind`` tenant may hold them all and they are not
    empty; ``RoleNotAllowedError`` otherwise."""
    wanted = frozenset(roles)
    for role in wanted:
        require_instance(role, Role, "roles[]")
    if not wanted:
        raise RoleNotAllowedError(kind.value, ())
    refused = wanted - ALLOWED_ROLES[kind]
    if refused:
        raise RoleNotAllowedError(kind.value, tuple(sorted(role.value for role in refused)))
    return wanted


@dataclass(frozen=True, slots=True)
class Tenant:
    id: TenantId
    kind: TenantKind
    name: str
    created_at: datetime
    region: str = DEFAULT_REGION
    status: TenantStatus = TenantStatus.ACTIVE

    def __post_init__(self) -> None:
        require_instance(self.id, TenantId, "id")
        require_instance(self.kind, TenantKind, "kind")
        _require_name(self.name, "name")
        require_aware(self.created_at, "created_at")
        if self.region not in REGIONS:
            raise InvariantViolationError(
                f"region must be one of {', '.join(REGIONS)}, got {self.region!r}"
            )
        require_instance(self.status, TenantStatus, "status")

    @property
    def is_active(self) -> bool:
        return self.status is TenantStatus.ACTIVE

    @property
    def admin_roles(self) -> frozenset[Role]:
        return ADMIN_ROLES[self.kind]


@dataclass(frozen=True, slots=True)
class Contact:
    """How the provider reaches a person: an email address, a phone number, or both."""

    email: str = ""
    phone: str = ""

    def __post_init__(self) -> None:
        require_instance(self.email, str, "email")
        require_instance(self.phone, str, "phone")
        if not self.email and not self.phone:
            raise InvariantViolationError("a user needs an email address or a phone number")
        if self.email and (
            len(self.email) > MAX_EMAIL_CHARS
            or EMAIL.fullmatch(self.email) is None
            or self.email != self.email.lower()
        ):
            raise InvariantViolationError("email must be one lower-case address")
        if self.phone and PHONE.fullmatch(self.phone) is None:
            raise InvariantViolationError("phone must be a number in E.164 form with its plus")

    @classmethod
    def of(cls, *, email: str | None = None, phone: str | None = None) -> Self:
        """The contact from what a person typed: the email address lower-cased, the phone
        number without spaces and with its plus."""
        address = (email or "").strip().lower()
        number = "".join((phone or "").split())
        if number and not number.startswith("+"):
            number = "+" + number
        return cls(email=address, phone=number)


@dataclass(frozen=True, slots=True)
class User:
    """A person in one tenant, known to the identity provider as ``provider_subject``."""

    id: UserId
    tenant_id: TenantId
    provider: str
    provider_subject: str
    contact: Contact
    roles: frozenset[Role]
    created_at: datetime
    updated_at: datetime
    display_name: str = ""
    status: UserStatus = UserStatus.ACTIVE
    session_version: int = 0

    def __post_init__(self) -> None:
        require_instance(self.id, UserId, "id")
        require_instance(self.tenant_id, TenantId, "tenant_id")
        _require_short(self.provider, "provider", MAX_PROVIDER_CHARS)
        _require_short(self.provider_subject, "provider_subject", MAX_SUBJECT_CHARS)
        require_instance(self.contact, Contact, "contact")
        roles = require_instance(self.roles, frozenset, "roles")
        if not roles or not all(isinstance(role, Role) for role in roles):
            raise InvariantViolationError("a user holds at least one role, each a Role")
        require_aware(self.created_at, "created_at")
        require_aware(self.updated_at, "updated_at")
        require_instance(self.display_name, str, "display_name")
        if len(self.display_name) > MAX_NAME_CHARS:
            raise InvariantViolationError(f"display_name has at most {MAX_NAME_CHARS} characters")
        require_instance(self.status, UserStatus, "status")
        require_int(self.session_version, "session_version", minimum=0)

    @classmethod
    def new(
        cls,
        tenant: Tenant,
        *,
        provider: str,
        provider_subject: str,
        contact: Contact,
        roles: Iterable[Role],
        at: datetime,
        display_name: str = "",
        user_id: UserId | None = None,
    ) -> Self:
        """A new active user of ``tenant`` holding ``roles``, which its kind must allow."""
        return cls(
            id=user_id or UserId.new(),
            tenant_id=tenant.id,
            provider=provider,
            provider_subject=provider_subject,
            contact=contact,
            roles=allowed_roles(tenant.kind, roles),
            created_at=at,
            updated_at=at,
            display_name=display_name.strip(),
        )

    @property
    def is_active(self) -> bool:
        return self.status is UserStatus.ACTIVE

    @property
    def requires_mfa(self) -> bool:
        return requires_mfa(self.roles)

    def is_admin_of(self, tenant: Tenant) -> bool:
        """Whether this user is an active admin of ``tenant``."""
        return (
            self.tenant_id == tenant.id and self.is_active and bool(self.roles & tenant.admin_roles)
        )

    def with_roles(
        self, roles: Iterable[Role], tenant: Tenant, *, colleagues: Iterable["User"], at: datetime
    ) -> Self:
        """This user holding ``roles`` instead, with the session version bumped. The same roles
        again change nothing. ``tenant`` is the user's own; ``colleagues`` are the tenant's other
        users: the last active admin cannot give up the admin role."""
        self._require_own(tenant)
        wanted = allowed_roles(tenant.kind, roles)
        if not self.is_active:
            raise UserDisabledError()
        if wanted == self.roles:
            return self
        if not wanted & tenant.admin_roles:
            self._check_not_last_admin(tenant, colleagues)
        return replace(self, roles=wanted, session_version=self.session_version + 1, updated_at=at)

    def disabled(self, tenant: Tenant, *, colleagues: Iterable["User"], at: datetime) -> Self:
        """This user disabled, with the session version bumped; the last active admin of
        ``tenant``, the user's own, cannot be disabled. A disabled user stays disabled."""
        self._require_own(tenant)
        if not self.is_active:
            return self
        self._check_not_last_admin(tenant, colleagues)
        return replace(
            self,
            status=UserStatus.DISABLED,
            session_version=self.session_version + 1,
            updated_at=at,
        )

    def _require_own(self, tenant: Tenant) -> None:
        """Only the user's own tenant changes the user; any other would skip its admin checks."""
        if tenant.id != self.tenant_id:
            raise InvariantViolationError(
                f"user {self.id} belongs to tenant {self.tenant_id}, not {tenant.id}"
            )

    def _check_not_last_admin(self, tenant: Tenant, colleagues: Iterable["User"]) -> None:
        if not self.is_admin_of(tenant):
            return
        if any(other.id != self.id and other.is_admin_of(tenant) for other in colleagues):
            return
        raise LastAdminError()


@dataclass(frozen=True, slots=True)
class SubjectEntry:
    """Which user, in which tenant, a provider's subject signs in as. The session exchange looks
    the subject up before it knows the tenant, so the entry holds ids only."""

    provider: str
    provider_subject: str
    user_id: UserId
    tenant_id: TenantId

    def __post_init__(self) -> None:
        _require_short(self.provider, "provider", MAX_PROVIDER_CHARS)
        _require_short(self.provider_subject, "provider_subject", MAX_SUBJECT_CHARS)
        require_instance(self.user_id, UserId, "user_id")
        require_instance(self.tenant_id, TenantId, "tenant_id")

    @classmethod
    def of(cls, user: User) -> Self:
        return cls(user.provider, user.provider_subject, user.id, user.tenant_id)


def _require_name(value: object, name: str) -> str:
    text = require_text(value, name)
    if len(text) > MAX_NAME_CHARS:
        raise InvariantViolationError(f"{name} has at most {MAX_NAME_CHARS} characters")
    return text


def _require_short(value: object, name: str, limit: int) -> str:
    text = require_text(value, name)
    if len(text) > limit:
        raise InvariantViolationError(f"{name} has at most {limit} characters")
    return text
