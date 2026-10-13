"""Development personas: the people the development sign-in signs in as, made on request.

The web app's development sign-in (local and test only, ``CW_WEB_AUTH_PROVIDER=fake``) lets a
developer or a browser test pick a tenant kind, roles and a display name and sign in as that
person at once. Before identity issued sessions the web minted such a session by itself; now
the sign-in is real (the fake provider token is exchanged at ``POST /sessions`` like any other),
so the person has to exist first. ``ProvisionDevPersona`` makes them exist: the tenant (made
with the id the caller chose, or a new one; the one development internal tenant for the
regulatory roles), the user with the roles and the name, and the subject index entry the
exchange looks up. A persona that exists already is answered as it is, with its roles changed
when the caller asks for others (which bumps the session version, as a tenant admin's change
would). It runs only behind ``POST /dev/provider-tokens``, which answers only with the fake
provider in local and test.

Every change is audited by ``system:dev-sign-in`` and publishes the events a sign-up or an
invitation would, so the rest of the platform sees a persona as it sees any user.
"""

from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import NAMESPACE_URL, uuid5

from domain_kernel.access import Role
from domain_kernel.audit import AuditActor
from domain_kernel.errors import InvariantViolationError
from domain_kernel.events import utc_now
from domain_kernel.ids import TenantId
from identity.application.audit import audit_entry, sorted_role_names
from identity.application.tenancy import first_user_events, tenant_created_entry
from identity.domain.errors import (
    ProviderAccountExistsError,
    SubjectRegisteredError,
    TenantInactiveError,
)
from identity.domain.events import RoleChangeReason, UserRoleChanged, sorted_roles
from identity.domain.provider import DevIdentityProvider
from identity.domain.repository import UnitOfWork, UnitOfWorkFactory
from identity.domain.tenancy import (
    Contact,
    SubjectEntry,
    Tenant,
    TenantKind,
    User,
    allowed_roles,
)

DEV_ACTOR: Final = AuditActor.system("dev-sign-in")
"""The actor of what the development sign-in makes."""
DEV_INTERNAL_TENANT_ID: Final = TenantId(
    uuid5(NAMESPACE_URL, "urn:compliancewatch:dev:internal-tenant")
)
"""The one internal tenant of a development stack, where every regulatory persona works unless
the caller names a tenant. Fixed, so personas made by different processes and runs share it."""
DEV_TENANT_NAMES: Final = {
    TenantKind.BUSINESS: "Development business (synthetic)",
    TenantKind.CA_FIRM: "Development CA firm (synthetic)",
    TenantKind.INTERNAL: "Development regulatory team (synthetic)",
}


@dataclass(frozen=True, slots=True)
class DevPersona:
    """Who to sign in as: the contact the provider token will name, the tenant's kind, the
    roles and the display name; ``tenant_id`` names an existing tenant or the id a new one
    gets."""

    contact: Contact
    kind: TenantKind
    roles: frozenset[Role]
    display_name: str = ""
    tenant_id: TenantId | None = None
    tenant_name: str = ""


@dataclass(frozen=True, slots=True)
class ProvisionedPersona:
    tenant: Tenant
    user: User
    tenant_created: bool
    user_created: bool


class ProvisionDevPersona:
    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        provider: DevIdentityProvider,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._provider = provider
        self._clock = clock

    def run(self, persona: DevPersona) -> ProvisionedPersona:
        """The tenant and the user the persona signs in as, made or found.

        ``RoleNotAllowedError`` (422) for roles the kind lacks; ``SubjectRegisteredError`` (409)
        when the contact signs in to another tenant already; ``InvariantViolationError`` (422)
        when the named tenant is of another kind; ``TenantInactiveError`` (403) when it is not
        active; ``LastAdminError`` (409) when the roles asked for would leave the tenant without
        an admin."""
        roles = allowed_roles(persona.kind, persona.roles)
        subject = self._provider.subject_for(persona.contact)
        with self._unit_of_work(None) as uow:
            entry = uow.subjects.find(self._provider.name, subject)
        tenant_id = self._tenant_id_for(persona, entry.tenant_id if entry else None)
        at = self._clock()
        with self._unit_of_work(tenant_id) as uow:
            tenant, tenant_created = self._tenant(uow, tenant_id, persona, at)
            user = None if entry is None else uow.users.get(entry.user_id)
            if user is None:
                user = self._add_user(uow, tenant, persona, roles, subject, at, tenant_created)
                user_created = True
            else:
                user = self._with_roles(uow, tenant, user, roles, at)
                user_created = False
        with suppress(ProviderAccountExistsError):
            self._provider.provision(
                email=persona.contact.email,
                phone=persona.contact.phone,
                display_name=persona.display_name.strip(),
            )
        return ProvisionedPersona(tenant, user, tenant_created, user_created)

    @staticmethod
    def _tenant_id_for(persona: DevPersona, existing: TenantId | None) -> TenantId:
        """The tenant the persona lives in: the one it is in already (a persona never moves),
        else the one the caller named, else the development internal tenant for the regulatory
        roles, else a new one."""
        if existing is not None:
            if persona.tenant_id is not None and persona.tenant_id != existing:
                raise SubjectRegisteredError()
            return existing
        if persona.tenant_id is not None:
            return persona.tenant_id
        if persona.kind is TenantKind.INTERNAL:
            return DEV_INTERNAL_TENANT_ID
        return TenantId.new()

    @staticmethod
    def _tenant(
        uow: UnitOfWork, tenant_id: TenantId, persona: DevPersona, at: datetime
    ) -> tuple[Tenant, bool]:
        tenant = uow.tenants.get(tenant_id)
        if tenant is None:
            name = persona.tenant_name.strip() or DEV_TENANT_NAMES[persona.kind]
            tenant = Tenant(tenant_id, persona.kind, name, at)
            uow.tenants.add(tenant)
            return tenant, True
        if tenant.kind is not persona.kind:
            raise InvariantViolationError(
                f"tenant {tenant_id} is a {tenant.kind.value} tenant, not {persona.kind.value}"
            )
        if not tenant.is_active:
            raise TenantInactiveError()
        return tenant, False

    def _add_user(
        self,
        uow: UnitOfWork,
        tenant: Tenant,
        persona: DevPersona,
        roles: frozenset[Role],
        subject: str,
        at: datetime,
        tenant_created: bool,
    ) -> User:
        user = User.new(
            tenant,
            provider=self._provider.name,
            provider_subject=subject,
            contact=persona.contact,
            roles=roles,
            at=at,
            display_name=persona.display_name,
        )
        uow.users.add(user)
        uow.subjects.add(SubjectEntry.of(user))
        if tenant_created:
            for event in first_user_events(tenant, user, changed_by=None):
                uow.events.publish(event)
            uow.audit.write(tenant_created_entry(tenant, user, actor=DEV_ACTOR))
        else:
            uow.events.publish(
                UserRoleChanged(
                    tenant_id=tenant.id,
                    user_id=user.id,
                    roles=sorted_roles(user.roles),
                    previous_roles=(),
                    reason=RoleChangeReason.INVITED,
                    session_version=user.session_version,
                )
            )
        uow.audit.write(
            audit_entry(
                "user.invited",
                tenant_id=tenant.id,
                subject_type="user",
                subject_id=str(user.id),
                at=at,
                after={"roles": sorted_role_names(user.roles), "status": user.status.value},
                actor=DEV_ACTOR,
            )
        )
        return user

    @staticmethod
    def _with_roles(
        uow: UnitOfWork, tenant: Tenant, user: User, roles: frozenset[Role], at: datetime
    ) -> User:
        """The user holding ``roles``; a disabled persona stays disabled (signing in as it is
        then refused, as it would be for anyone)."""
        if not user.is_active or user.roles == roles:
            return user
        changed = user.with_roles(roles, tenant, colleagues=uow.users.list(), at=at)
        uow.users.save(changed)
        uow.events.publish(
            UserRoleChanged(
                tenant_id=tenant.id,
                user_id=user.id,
                roles=sorted_roles(changed.roles),
                previous_roles=sorted_roles(user.roles),
                reason=RoleChangeReason.ROLES_CHANGED,
                session_version=changed.session_version,
            )
        )
        uow.audit.write(
            audit_entry(
                "user.roles_changed",
                tenant_id=tenant.id,
                subject_type="user",
                subject_id=str(user.id),
                at=at,
                before={"roles": sorted_role_names(user.roles)},
                after={"roles": sorted_role_names(changed.roles)},
                actor=DEV_ACTOR,
            )
        )
        return changed
