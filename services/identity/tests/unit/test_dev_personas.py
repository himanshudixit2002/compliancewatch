"""The development personas the dev sign-in makes, through the use case on the memory store."""

from datetime import UTC, datetime, timedelta

import pytest

from domain_kernel.access import Role
from domain_kernel.ids import TenantId
from identity.application.dev_personas import (
    DEV_ACTOR,
    DEV_INTERNAL_TENANT_ID,
    DevPersona,
    ProvisionDevPersona,
)
from identity.domain.errors import LastAdminError, RoleNotAllowedError, SubjectRegisteredError
from identity.domain.events import RoleChangeReason, TenantCreated, UserRoleChanged
from identity.domain.tenancy import Contact, TenantKind
from identity.infrastructure.memory import MemoryStore
from identity.infrastructure.providers.fake import FakeIdentityProvider

NOW = datetime(2000, 4, 10, 5, 0, tzinfo=UTC)
LATER = NOW + timedelta(minutes=1)
OWNER = Contact(phone="+919876543210")
STAFF = Contact(email="staff@example.test")


def owner_persona(**fields: object) -> DevPersona:
    values: dict[str, object] = {
        "contact": OWNER,
        "kind": TenantKind.BUSINESS,
        "roles": frozenset({Role.OWNER}),
        "display_name": "Example owner",
    }
    values.update(fields)
    return DevPersona(**values)  # type: ignore[arg-type]


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


@pytest.fixture
def provider() -> FakeIdentityProvider:
    return FakeIdentityProvider()


def test_a_new_persona_gets_a_tenant_a_user_and_the_events_of_a_sign_up(
    store: MemoryStore, provider: FakeIdentityProvider
) -> None:
    made = ProvisionDevPersona(store, provider, clock=lambda: NOW).run(owner_persona())
    assert (made.tenant_created, made.user_created) == (True, True)
    assert (made.tenant.kind, made.tenant.name) == (
        TenantKind.BUSINESS,
        "Development business (synthetic)",
    )
    assert made.user.roles == frozenset({Role.OWNER})
    assert (made.user.display_name, made.user.contact) == ("Example owner", OWNER)
    assert made.user.provider_subject == provider.subject_for(OWNER)
    assert provider.lookup(made.user.provider_subject) is not None
    created, first = store.events
    assert isinstance(created, TenantCreated)
    assert created.tenant_id == made.tenant.id
    assert isinstance(first, UserRoleChanged)
    assert first.reason is RoleChangeReason.CREATED
    actions = [(entry.action, entry.actor) for entry in store.audit]
    assert actions == [("tenant.created", DEV_ACTOR), ("user.invited", DEV_ACTOR)]
    # The exchange finds the subject.
    with store(None) as uow:
        entry = uow.subjects.find(provider.name, made.user.provider_subject)
    assert entry is not None
    assert entry.user_id == made.user.id


def test_a_persona_again_is_the_same_user_and_other_roles_bump_the_version(
    store: MemoryStore, provider: FakeIdentityProvider
) -> None:
    personas = ProvisionDevPersona(store, provider, clock=lambda: NOW)
    first = personas.run(owner_persona())
    again = personas.run(owner_persona(display_name="Another name"))
    assert (again.tenant_created, again.user_created) == (False, False)
    assert again.user == first.user
    promoted = ProvisionDevPersona(store, provider, clock=lambda: LATER).run(
        owner_persona(roles=frozenset({Role.OWNER, Role.COMPLIANCE_LEAD}))
    )
    assert promoted.user.roles == frozenset({Role.OWNER, Role.COMPLIANCE_LEAD})
    assert (promoted.user.session_version, promoted.user.updated_at) == (1, LATER)
    changed = store.events[-1]
    assert isinstance(changed, UserRoleChanged)
    assert (changed.reason, changed.changed_by) == (RoleChangeReason.ROLES_CHANGED, None)
    assert store.audit[-1].action == "user.roles_changed"


def test_a_second_persona_joins_the_named_tenant_as_an_invitation_would(
    store: MemoryStore, provider: FakeIdentityProvider
) -> None:
    personas = ProvisionDevPersona(store, provider, clock=lambda: NOW)
    owner = personas.run(owner_persona(tenant_name="Example Traders"))
    staff = personas.run(
        DevPersona(STAFF, TenantKind.BUSINESS, frozenset({Role.STAFF}), tenant_id=owner.tenant.id)
    )
    assert (staff.tenant_created, staff.user_created) == (False, True)
    assert staff.tenant == owner.tenant
    assert staff.tenant.name == "Example Traders"
    invited = store.events[-1]
    assert isinstance(invited, UserRoleChanged)
    assert invited.reason is RoleChangeReason.INVITED
    with store(owner.tenant.id) as uow:
        assert {user.id for user in uow.users.list()} == {owner.user.id, staff.user.id}


def test_regulatory_personas_share_the_development_internal_tenant(
    store: MemoryStore, provider: FakeIdentityProvider
) -> None:
    personas = ProvisionDevPersona(store, provider, clock=lambda: NOW)
    admin = personas.run(DevPersona(OWNER, TenantKind.INTERNAL, frozenset({Role.ADMIN})))
    analyst = personas.run(DevPersona(STAFF, TenantKind.INTERNAL, frozenset({Role.ANALYST})))
    assert admin.tenant.id == analyst.tenant.id == DEV_INTERNAL_TENANT_ID
    assert admin.tenant.name == "Development regulatory team (synthetic)"


def test_a_persona_is_refused_where_a_tenant_admin_would_be(
    store: MemoryStore, provider: FakeIdentityProvider
) -> None:
    personas = ProvisionDevPersona(store, provider, clock=lambda: NOW)
    owner = personas.run(owner_persona())
    with pytest.raises(RoleNotAllowedError):
        personas.run(owner_persona(roles=frozenset({Role.ANALYST})))
    with pytest.raises(LastAdminError):
        personas.run(owner_persona(roles=frozenset({Role.STAFF})))
    with pytest.raises(SubjectRegisteredError):
        personas.run(owner_persona(tenant_id=TenantId.new()))
    # A disabled persona stays disabled: signing in as it is refused like anyone's.
    other = personas.run(
        DevPersona(STAFF, TenantKind.BUSINESS, frozenset({Role.OWNER}), tenant_id=owner.tenant.id)
    ).user
    with store(owner.tenant.id) as uow:
        user = uow.users.get(owner.user.id)
        tenant = uow.tenants.get(owner.tenant.id)
        assert user is not None
        assert tenant is not None
        uow.users.save(user.disabled(tenant, colleagues=[other], at=LATER))
    kept = personas.run(owner_persona(roles=frozenset({Role.STAFF})))
    assert kept.user.is_active is False
    assert kept.user.roles == frozenset({Role.OWNER})
