"""Tenants and their users: sign-up and the signed-in user.

``CreateTenant`` is sign-up. A person signed in at the identity provider whose subject signs in
as nobody yet (the exchange answered identity-user-not-provisioned) creates a business or CA
firm tenant and becomes its first user with the kind's admin role. The tenant, the user, the
subject index entry and the two events (tenant.created, then user.role.changed with reason
created) commit together, and the answer carries a session. A CA firm's first user is a CA admin,
who signs in with a second factor, so that sign-up needs one too.

``CurrentUser`` answers the user and tenant a token names, after checking the session version.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from domain_kernel.access import Principal
from domain_kernel.errors import InvariantViolationError
from domain_kernel.events import utc_now
from domain_kernel.ids import TenantId
from identity.application.sessions import Session, check_session, user_principal
from identity.domain.errors import MfaRequiredError, SubjectRegisteredError
from identity.domain.events import RoleChangeReason, TenantCreated, UserRoleChanged, sorted_roles
from identity.domain.provider import IdentityProvider
from identity.domain.repository import UnitOfWorkFactory
from identity.domain.sessions import TokenMinter
from identity.domain.tenancy import FIRST_ROLE, SubjectEntry, Tenant, TenantKind, User, requires_mfa

SIGN_UP_KINDS = (TenantKind.BUSINESS, TenantKind.CA_FIRM)
"""Sign-up creates businesses and CA firms; an operator sets up the internal tenant."""


@dataclass(frozen=True, slots=True)
class CreatedTenant:
    tenant: Tenant
    user: User
    session: Session


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
