"""Tenants and their users: sign-up, the signed-in user, and what tenant admins do.

``CreateTenant`` is sign-up. A person signed in at the identity provider whose subject signs in
as nobody yet (the exchange answered identity-user-not-provisioned) creates a business or CA
firm tenant and becomes its first user with the kind's admin role. The tenant, the user, the
subject index entry and the two events (tenant.created, then user.role.changed with reason
created) commit together, and the answer carries a session. A CA firm's first user is a CA admin,
who signs in with a second factor, so that sign-up needs one too.

``CurrentUser`` answers the user and tenant a token names, after checking the session version.

A tenant admin (an owner, a CA admin, or an admin of the internal tenant) lists the tenant's users,
invites one, changes a user's roles or disables one. When a verified token names the caller, its
session version is checked against the store first, so an admin whose roles changed a moment ago
is refused at once, and the caller is ``changed_by`` on the event. Without a token (header mode;
the routes refuse a request without one in dual mode) the tenant header names the tenant as it
does on every tenant route, and ``changed_by`` is empty. Such an anonymous caller grants no admin
or regulatory role (``SIGNED_IN_GRANTS``): identity would put the role in the tokens it signs,
which the other services trust. ``InviteUser`` creates the person's account at the identity provider
inside the unit of work that stores the user, after the plan's seat check passed with the tenant
locked, and removes it again when the user cannot be stored. A change of roles and disabling each
bump the user's session version; every change publishes user.role.changed. The last active admin
of a tenant can be neither demoted nor disabled, and changes and disables in one tenant run one at
a time (``admin_context`` locks the tenant), so two of them at once cannot both pass that check.

Each change writes its audit entry in the unit of work of the change (``application.audit``):
``tenant.created`` by the person signing up, ``user.invited``, ``user.roles_changed`` and
``user.disabled`` by the admin a verified token names (else the system, in header mode). An entry
holds roles and status, never a contact detail.
"""

from collections.abc import Callable, Iterable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Protocol

from domain_kernel.access import REGULATORY_ROLES, TENANT_ADMIN_ROLES, Principal, Role
from domain_kernel.audit import AuditActor, AuditEntry
from domain_kernel.errors import InvariantViolationError
from domain_kernel.events import utc_now
from domain_kernel.ids import TenantId, UserId
from identity.application.audit import audit_entry, sorted_role_names
from identity.application.sessions import Session, check_session, user_principal
from identity.domain.errors import (
    MfaRequiredError,
    ProviderUnavailableError,
    SubjectRegisteredError,
    TenantNotFoundError,
    UserNotFoundError,
)
from identity.domain.events import RoleChangeReason, TenantCreated, UserRoleChanged, sorted_roles
from identity.domain.provider import IdentityProvider
from identity.domain.repository import UnitOfWork, UnitOfWorkFactory
from identity.domain.sessions import TokenMinter
from identity.domain.tenancy import (
    FIRST_ROLE,
    Contact,
    SubjectEntry,
    Tenant,
    TenantKind,
    User,
    allowed_roles,
    requires_mfa,
)
from py_common.auth.errors import AuthForbiddenError

SIGN_UP_KINDS = (TenantKind.BUSINESS, TenantKind.CA_FIRM)
"""Sign-up creates businesses and CA firms; an operator sets up the internal tenant."""
SIGNED_IN_GRANTS: Final = TENANT_ADMIN_ROLES | REGULATORY_ROLES
"""Roles only an admin a verified token names may grant: those that manage a tenant's users and
those that curate the rulebook."""


class SeatCheck(Protocol):
    def __call__(self, uow: UnitOfWork, tenant_id: TenantId) -> None:
        """Raise when the tenant has no seat left for one more user."""
        ...


@dataclass(frozen=True, slots=True)
class CreatedTenant:
    tenant: Tenant
    user: User
    session: Session


def tenant_created_entry(tenant: Tenant, user: User, *, actor: AuditActor) -> AuditEntry:
    """The ``tenant.created`` entry of a new tenant and its first user."""
    return audit_entry(
        "tenant.created",
        tenant_id=tenant.id,
        subject_type="tenant",
        subject_id=str(tenant.id),
        at=tenant.created_at,
        after={
            "kind": tenant.kind.value,
            "region": tenant.region,
            "status": tenant.status.value,
            "first_user_id": str(user.id),
            "first_user_roles": sorted_role_names(user.roles),
        },
        actor=actor,
    )


def first_user_events(
    tenant: Tenant, user: User, *, changed_by: User | None
) -> tuple[TenantCreated, UserRoleChanged]:
    """What a new tenant publishes: tenant.created, then its first user's user.role.changed."""
    created = TenantCreated(
        tenant_id=tenant.id,
        kind=tenant.kind,
        region=tenant.region,
        created_by=user.id,
        created_at=tenant.created_at,
    )
    first = UserRoleChanged(
        tenant_id=tenant.id,
        user_id=user.id,
        roles=sorted_roles(user.roles),
        previous_roles=(),
        reason=RoleChangeReason.CREATED,
        session_version=user.session_version,
        changed_by=None if changed_by is None else changed_by.id,
    )
    return created, first


class CreateTenant:
    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        provider: IdentityProvider,
        minter: TokenMinter,
        *,
        ttl: timedelta,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._provider = provider
        self._minter = minter
        self._ttl = ttl
        self._clock = clock

    def run(
        self, provider_token: str, kind: TenantKind, name: str, *, display_name: str = ""
    ) -> CreatedTenant:
        if kind not in SIGN_UP_KINDS:
            raise InvariantViolationError(
                "sign-up creates a business or a CA firm; an operator sets up the internal tenant"
            )
        identity = self._provider.verify(provider_token)
        with self._unit_of_work(None) as uow:
            if uow.subjects.find(self._provider.name, identity.subject) is not None:
                raise SubjectRegisteredError()
        role = FIRST_ROLE[kind]
        if requires_mfa([role]) and not identity.mfa:
            raise MfaRequiredError()
        at = self._clock()
        tenant = Tenant(TenantId.new(), kind, name.strip(), at)
        user = User.new(
            tenant,
            provider=self._provider.name,
            provider_subject=identity.subject,
            contact=identity.contact,
            roles=[role],
            at=at,
            display_name=display_name,
        )
        with self._unit_of_work(tenant.id) as uow:
            uow.tenants.add(tenant)
            uow.users.add(user)
            uow.subjects.add(SubjectEntry.of(user))
            for event in first_user_events(tenant, user, changed_by=user):
                uow.events.publish(event)
            uow.audit.write(
                tenant_created_entry(tenant, user, actor=AuditActor.user(user.id, user.roles))
            )
        principal = user_principal(user, mfa=identity.mfa)
        session = Session(self._minter.mint(principal, self._ttl), principal, tenant, user)
        return CreatedTenant(tenant, user, session)


class CurrentUser:
    """The signed-in user a token names, re-checked against the store."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self, principal: Principal) -> tuple[Tenant, User]:
        with self._unit_of_work(principal.tenant_id) as uow:
            return check_session(uow, principal)


def admin_context(
    uow: UnitOfWork, tenant_id: TenantId, actor: Principal, *, lock: bool = False
) -> tuple[Tenant, User | None]:
    """The tenant, and the admin acting in it when a verified token names them. The actor's
    session version is checked against the store and the actor must be an active admin of the
    tenant.

    With ``lock`` the tenant stays locked until the unit of work ends, and it is taken before
    anything else is read. Changes that could take away the tenant's last admin then run one at
    a time, each reading the admins as the one before it left them: two owners demoting each
    other at once leave one owner, not none."""
    tenant = uow.tenants.lock(tenant_id) if lock else uow.tenants.get(tenant_id)
    if tenant is None:
        raise TenantNotFoundError()
    if not actor.is_authenticated:
        return tenant, None
    _, admin = check_session(uow, actor)
    if not admin.is_admin_of(tenant):
        raise AuthForbiddenError("managing users needs a tenant admin role")
    return tenant, admin


def _changed_by(admin: User | None) -> UserId | None:
    return None if admin is None else admin.id


def member(uow: UnitOfWork, tenant: Tenant, user_id: UserId) -> User:
    """The user of ``tenant`` with this id. A user of another tenant is not found either: the
    store scopes its reads to the tenant, and this check keeps holding where row-level security
    does not apply (a database role that bypasses it)."""
    user = uow.users.get(user_id)
    if user is None or user.tenant_id != tenant.id:
        raise UserNotFoundError(str(user_id))
    return user


def check_grant(actor: Principal, granted: Iterable[Role]) -> None:
    """Refuse an anonymous ``actor`` granting any of ``SIGNED_IN_GRANTS``."""
    refused = sorted(role.value for role in SIGNED_IN_GRANTS.intersection(granted))
    if refused and not actor.is_authenticated:
        raise AuthForbiddenError(
            f"granting {', '.join(refused)} needs a tenant admin's access token, which identity "
            "reads only when CW_AUTH_MODE is dual or token"
        )


class ListUsers:
    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self, tenant_id: TenantId, actor: Principal) -> list[User]:
        with self._unit_of_work(tenant_id) as uow:
            admin_context(uow, tenant_id, actor)
            return [user for user in uow.users.list() if user.tenant_id == tenant_id]


class ReadMembership:
    """Whether a user belongs to a tenant, for a service acting for it (the obligation service
    checks an assignee this way): the tenant's user with this id, active or disabled.
    ``TenantNotFoundError`` and ``UserNotFoundError`` when there is no such tenant or user; a user
    of another tenant is not found either. The route admits only a service with tenant:act, or in
    header mode the tenant the header names, so no admin is checked here."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self, tenant_id: TenantId, user_id: UserId) -> User:
        with self._unit_of_work(tenant_id) as uow:
            tenant = uow.tenants.get(tenant_id)
            if tenant is None:
                raise TenantNotFoundError()
            return member(uow, tenant, user_id)


class InviteUser:
    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        provider: IdentityProvider,
        *,
        clock: Callable[[], datetime] = utc_now,
        seats: SeatCheck | None = None,
    ) -> None:
        """``seats`` refuses a user past the tenant's plan (``SeatLimitReachedError``, 402). It
        runs once early, and again with the tenant locked; only after that second check passes is
        the provider's account made, inside the same locked unit of work, so two invitations at
        once cannot both take the last seat and a refusal leaves no account at the provider."""
        self._unit_of_work = unit_of_work
        self._provider = provider
        self._clock = clock
        self._seats = seats

    def run(
        self,
        tenant_id: TenantId,
        actor: Principal,
        *,
        contact: Contact,
        roles: Iterable[Role],
        display_name: str = "",
    ) -> User:
        with self._unit_of_work(tenant_id) as uow:
            tenant, _ = admin_context(uow, tenant_id, actor)
            if self._seats is not None:
                self._seats(uow, tenant_id)
        wanted = allowed_roles(tenant.kind, roles)
        check_grant(actor, wanted)
        subject: str | None = None
        try:
            with self._unit_of_work(tenant.id) as uow:
                tenant, admin = admin_context(uow, tenant.id, actor, lock=self._seats is not None)
                if self._seats is not None:
                    self._seats(uow, tenant.id)
                subject = self._provider.provision(
                    email=contact.email, phone=contact.phone, display_name=display_name.strip()
                )
                return self._add(uow, tenant, admin, actor, subject, contact, wanted, display_name)
        except Exception:
            # The account is new and nobody can sign in with it; a provider that cannot remove it
            # now leaves an orphan account, never a user.
            if subject is not None:
                with suppress(ProviderUnavailableError):
                    self._provider.delete(subject)
            raise

    def _add(
        self,
        uow: UnitOfWork,
        tenant: Tenant,
        admin: User | None,
        actor: Principal,
        subject: str,
        contact: Contact,
        roles: frozenset[Role],
        display_name: str,
    ) -> User:
        user = User.new(
            tenant,
            provider=self._provider.name,
            provider_subject=subject,
            contact=contact,
            roles=roles,
            at=self._clock(),
            display_name=display_name,
        )
        uow.users.add(user)
        uow.subjects.add(SubjectEntry.of(user))
        uow.events.publish(
            UserRoleChanged(
                tenant_id=tenant.id,
                user_id=user.id,
                roles=sorted_roles(user.roles),
                previous_roles=(),
                reason=RoleChangeReason.INVITED,
                session_version=user.session_version,
                changed_by=_changed_by(admin),
            )
        )
        uow.audit.write(
            _user_entry(
                "user.invited",
                user,
                actor,
                before=None,
                after={"roles": sorted_role_names(user.roles), "status": user.status.value},
            )
        )
        return user


class ChangeRoles:
    def __init__(
        self, unit_of_work: UnitOfWorkFactory, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run(
        self, tenant_id: TenantId, actor: Principal, user_id: UserId, roles: Iterable[Role]
    ) -> User:
        """The user with ``roles``; the same roles again change nothing and publish nothing."""
        wanted = frozenset(roles)
        with self._unit_of_work(tenant_id) as uow:
            tenant, admin = admin_context(uow, tenant_id, actor, lock=True)
            user = member(uow, tenant, user_id)
            check_grant(actor, wanted - user.roles)
            changed = user.with_roles(wanted, tenant, colleagues=uow.users.list(), at=self._clock())
            if changed is user:
                return user
            uow.users.save(changed)
            uow.events.publish(
                UserRoleChanged(
                    tenant_id=tenant.id,
                    user_id=user.id,
                    roles=sorted_roles(changed.roles),
                    previous_roles=sorted_roles(user.roles),
                    reason=RoleChangeReason.ROLES_CHANGED,
                    session_version=changed.session_version,
                    changed_by=_changed_by(admin),
                )
            )
            uow.audit.write(
                _user_entry(
                    "user.roles_changed",
                    changed,
                    actor,
                    before={"roles": sorted_role_names(user.roles)},
                    after={"roles": sorted_role_names(changed.roles)},
                )
            )
        return changed


class DisableUser:
    def __init__(
        self, unit_of_work: UnitOfWorkFactory, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run(self, tenant_id: TenantId, actor: Principal, user_id: UserId) -> User:
        """The user, disabled; a disabled user stays as it is and publishes nothing."""
        with self._unit_of_work(tenant_id) as uow:
            tenant, admin = admin_context(uow, tenant_id, actor, lock=True)
            user = member(uow, tenant, user_id)
            disabled = user.disabled(tenant, colleagues=uow.users.list(), at=self._clock())
            if disabled is user:
                return user
            uow.users.save(disabled)
            uow.events.publish(
                UserRoleChanged(
                    tenant_id=tenant.id,
                    user_id=user.id,
                    roles=(),
                    previous_roles=sorted_roles(user.roles),
                    reason=RoleChangeReason.DISABLED,
                    session_version=disabled.session_version,
                    changed_by=_changed_by(admin),
                )
            )
            uow.audit.write(
                _user_entry(
                    "user.disabled",
                    disabled,
                    actor,
                    before={"status": user.status.value},
                    after={"status": disabled.status.value},
                )
            )
        return disabled


def _user_entry(
    action: str,
    user: User,
    actor: Principal,
    *,
    before: dict[str, object] | None,
    after: dict[str, object] | None,
) -> AuditEntry:
    """An admin's change to ``user``, by the admin a verified token names (else the system)."""
    return audit_entry(
        action,
        tenant_id=user.tenant_id,
        subject_type="user",
        subject_id=str(user.id),
        at=user.updated_at,
        before=before,
        after=after,
        principal=actor,
    )
