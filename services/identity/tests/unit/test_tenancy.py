"""Tenants, users and roles: the rules of the domain and the memory unit of work."""

from datetime import UTC, datetime, timedelta

import pytest

from domain_kernel.access import Role
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import ConsentId, TenantId, UserId
from identity.domain.consent import ConsentPurpose, ConsentRecord, ConsentSource
from identity.domain.errors import (
    LastAdminError,
    RoleNotAllowedError,
    SubjectRegisteredError,
    UserDisabledError,
)
from identity.domain.events import RoleChangeReason, TenantCreated, UserRoleChanged, sorted_roles
from identity.domain.tenancy import (
    ADMIN_ROLES,
    ALLOWED_ROLES,
    FIRST_ROLE,
    Contact,
    SubjectEntry,
    Tenant,
    TenantKind,
    TenantStatus,
    User,
    UserStatus,
    allowed_roles,
    requires_mfa,
)
from identity.infrastructure.memory import MemoryStore, RowSecurityViolationError

NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
LATER = NOW + timedelta(hours=1)
PHONE = "+919876543210"


def tenant(kind: TenantKind = TenantKind.BUSINESS, name: str = "Acme Traders") -> Tenant:
    return Tenant(TenantId.new(), kind, name, NOW)


def user(owner: Tenant, *roles: Role, subject: str = "subject-1") -> User:
    return User.new(
        owner,
        provider="fake",
        provider_subject=subject,
        contact=Contact(phone=PHONE),
        roles=roles or (FIRST_ROLE[owner.kind],),
        at=NOW,
    )


# ---------------------------------------------------------------- roles by tenant kind


def test_each_kind_allows_its_own_roles_and_starts_with_its_admin() -> None:
    assert ALLOWED_ROLES[TenantKind.BUSINESS] == {Role.OWNER, Role.STAFF, Role.COMPLIANCE_LEAD}
    assert ALLOWED_ROLES[TenantKind.CA_FIRM] == {
        Role.CA_ADMIN,
        Role.CA_STAFF,
        Role.COMPLIANCE_LEAD,
    }
    assert ALLOWED_ROLES[TenantKind.INTERNAL] == {Role.ANALYST, Role.REVIEWER, Role.ADMIN}
    for kind in TenantKind:
        assert FIRST_ROLE[kind] in ADMIN_ROLES[kind]
        assert ADMIN_ROLES[kind] <= ALLOWED_ROLES[kind]
    assert ADMIN_ROLES[TenantKind.BUSINESS] == {Role.OWNER}
    assert ADMIN_ROLES[TenantKind.CA_FIRM] == {Role.CA_ADMIN}
    assert ADMIN_ROLES[TenantKind.INTERNAL] == {Role.ADMIN}


@pytest.mark.parametrize(
    ("kind", "roles", "refused"),
    [
        (TenantKind.BUSINESS, {Role.CA_ADMIN}, ("ca_admin",)),
        (TenantKind.CA_FIRM, {Role.OWNER, Role.CA_STAFF}, ("owner",)),
        (TenantKind.INTERNAL, {Role.STAFF, Role.ANALYST}, ("staff",)),
        (TenantKind.BUSINESS, set(), ()),
    ],
)
def test_a_role_the_kind_does_not_have_is_refused(
    kind: TenantKind, roles: set[Role], refused: tuple[str, ...]
) -> None:
    with pytest.raises(RoleNotAllowedError) as error:
        allowed_roles(kind, roles)
    assert error.value.refused == refused
    assert (error.value.kind in error.value.detail) is bool(refused)


def test_a_new_user_needs_roles_its_tenant_allows() -> None:
    with pytest.raises(RoleNotAllowedError):
        user(tenant(), Role.ANALYST)
    with pytest.raises(InvariantViolationError):
        allowed_roles(TenantKind.BUSINESS, ["owner"])  # type: ignore[list-item]


def test_mfa_is_required_for_the_regulatory_roles_and_ca_admins() -> None:
    assert requires_mfa([Role.CA_ADMIN])
    assert requires_mfa([Role.STAFF, Role.ANALYST])
    assert not requires_mfa([Role.OWNER, Role.STAFF, Role.COMPLIANCE_LEAD, Role.CA_STAFF])
    assert not requires_mfa([])
    assert user(tenant(TenantKind.CA_FIRM)).requires_mfa
    assert not user(tenant()).requires_mfa


# ---------------------------------------------------------------- tenants and users


def test_a_tenant_keeps_its_data_in_india_with_a_name() -> None:
    acme = tenant()
    assert (acme.region, acme.status, acme.is_active) == ("in", TenantStatus.ACTIVE, True)
    assert acme.admin_roles == {Role.OWNER}
    with pytest.raises(InvariantViolationError, match="region"):
        Tenant(TenantId.new(), TenantKind.BUSINESS, "Acme", NOW, region="eu")
    for name in ("", " Acme", "x" * 201):
        with pytest.raises(InvariantViolationError):
            tenant(name=name)
    with pytest.raises(InvariantViolationError):
        Tenant(TenantId.new(), TenantKind.BUSINESS, "Acme", datetime(2026, 10, 1))
    closing = Tenant(
        TenantId.new(), TenantKind.BUSINESS, "Acme", NOW, status=TenantStatus.DELETION_REQUESTED
    )
    assert not closing.is_active


def test_contact_needs_an_address_or_a_number_in_canonical_form() -> None:
    assert Contact.of(email=" Owner@Acme.Example ") == Contact(email="owner@acme.example")
    assert Contact.of(phone="91 98765 43210") == Contact(phone=PHONE)
    assert Contact.of(phone=PHONE, email="") == Contact(phone=PHONE)
    for bad in (
        {},
        {"email": "Owner@acme.example"},
        {"email": "no-at-sign"},
        {"email": "a@b"},
        {"email": "x" * 250 + "@a.in"},
        {"phone": "9876543210"},
        {"phone": "+0123456789"},
    ):
        with pytest.raises(InvariantViolationError):
            Contact(**bad)


def test_a_new_user_is_active_at_session_version_zero() -> None:
    acme = tenant()
    owner = User.new(
        acme,
        provider="fake",
        provider_subject="subject-1",
        contact=Contact(email="owner@acme.example"),
        roles=[Role.OWNER],
        at=NOW,
        display_name="  Asha  ",
    )
    assert owner.tenant_id == acme.id
    assert (owner.status, owner.session_version, owner.display_name) == (
        UserStatus.ACTIVE,
        0,
        "Asha",
    )
    assert owner.is_admin_of(acme)
    assert not owner.is_admin_of(tenant())
    assert SubjectEntry.of(owner) == SubjectEntry("fake", "subject-1", owner.id, acme.id)


@pytest.mark.parametrize(
    "changes",
    [
        {"provider": ""},
        {"provider": "p" * 33},
        {"provider_subject": " s"},
        {"provider_subject": "s" * 256},
        {"roles": frozenset()},
        {"roles": frozenset({"owner"})},
        {"display_name": "d" * 201},
        {"session_version": -1},
        {"created_at": datetime(2026, 10, 1)},
    ],
)
def test_user_invariants(changes: dict[str, object]) -> None:
    values: dict[str, object] = {
        "id": UserId.new(),
        "tenant_id": TenantId.new(),
        "provider": "fake",
        "provider_subject": "subject-1",
        "contact": Contact(phone=PHONE),
        "roles": frozenset({Role.OWNER}),
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(changes)
    with pytest.raises(InvariantViolationError):
        User(**values)  # type: ignore[arg-type]


# ---------------------------------------------------------------- role changes and disabling


def test_changing_roles_bumps_the_session_version_and_same_roles_change_nothing() -> None:
    acme = tenant()
    owner, staff = user(acme), user(acme, Role.STAFF, subject="subject-2")
    promoted = staff.with_roles(
        [Role.STAFF, Role.COMPLIANCE_LEAD], acme, colleagues=[owner], at=LATER
    )
    assert promoted.roles == {Role.STAFF, Role.COMPLIANCE_LEAD}
    assert (promoted.session_version, promoted.updated_at) == (1, LATER)
    assert promoted.with_roles(promoted.roles, acme, colleagues=[owner], at=NOW) is promoted
    with pytest.raises(RoleNotAllowedError):
        staff.with_roles([Role.CA_STAFF], acme, colleagues=[owner], at=LATER)


def test_the_last_admin_cannot_step_down_or_be_disabled() -> None:
    acme = tenant()
    owner = user(acme)
    staff = user(acme, Role.STAFF, subject="subject-2")
    with pytest.raises(LastAdminError):
        owner.with_roles([Role.STAFF], acme, colleagues=[owner, staff], at=LATER)
    with pytest.raises(LastAdminError):
        owner.disabled(acme, colleagues=[staff], at=LATER)
    second = staff.with_roles([Role.OWNER], acme, colleagues=[owner], at=LATER)
    stepped_down = owner.with_roles([Role.STAFF], acme, colleagues=[second], at=LATER)
    assert stepped_down.roles == {Role.STAFF}
    assert stepped_down.session_version == 1
    disabled_second = second.disabled(acme, colleagues=[owner], at=LATER)
    with pytest.raises(LastAdminError):
        owner.disabled(acme, colleagues=[disabled_second], at=LATER)


def test_an_admin_of_another_tenant_does_not_count() -> None:
    acme, other = tenant(), tenant(name="Other")
    owner = user(acme)
    with pytest.raises(LastAdminError):
        owner.disabled(acme, colleagues=[user(other, subject="subject-9")], at=LATER)


def test_only_the_users_own_tenant_changes_them() -> None:
    acme, other = tenant(), tenant(name="Other")
    owner = user(acme)
    with pytest.raises(InvariantViolationError, match="belongs to tenant"):
        owner.with_roles([Role.STAFF], other, colleagues=[], at=LATER)
    with pytest.raises(InvariantViolationError, match="belongs to tenant"):
        owner.disabled(other, colleagues=[], at=LATER)


def test_disabling_bumps_the_session_version_once_and_freezes_the_roles() -> None:
    acme = tenant()
    owner, staff = user(acme), user(acme, Role.STAFF, subject="subject-2")
    disabled = staff.disabled(acme, colleagues=[owner], at=LATER)
    assert (disabled.status, disabled.session_version, disabled.is_active) == (
        UserStatus.DISABLED,
        1,
        False,
    )
    assert disabled.disabled(acme, colleagues=[owner], at=LATER) is disabled
    with pytest.raises(UserDisabledError):
        disabled.with_roles([Role.OWNER], acme, colleagues=[owner], at=LATER)
    assert not disabled.is_admin_of(acme)


# ---------------------------------------------------------------- events


def test_events_name_their_tenant_and_carry_sorted_roles() -> None:
    acme = tenant()
    owner = user(acme, Role.OWNER, Role.COMPLIANCE_LEAD)
    created = TenantCreated(
        tenant_id=acme.id, kind=acme.kind, region="in", created_by=owner.id, created_at=NOW
    )
    assert created.topic == "tenant.created"
    changed = UserRoleChanged(
        tenant_id=acme.id,
        user_id=owner.id,
        roles=sorted_roles(owner.roles),
        previous_roles=(),
        reason=RoleChangeReason.CREATED,
        session_version=0,
        changed_by=owner.id,
    )
    assert changed.roles == (Role.COMPLIANCE_LEAD, Role.OWNER)
    with pytest.raises(InvariantViolationError):
        TenantCreated(kind=acme.kind, region="in", created_by=owner.id, created_at=NOW)
    with pytest.raises(InvariantViolationError):
        TenantCreated(
            tenant_id=acme.id, kind=acme.kind, region="eu", created_by=owner.id, created_at=NOW
        )
    with pytest.raises(InvariantViolationError):
        UserRoleChanged(
            user_id=owner.id,
            roles=(),
            previous_roles=(),
            reason=RoleChangeReason.DISABLED,
            session_version=1,
        )
    with pytest.raises(InvariantViolationError):
        UserRoleChanged(
            tenant_id=acme.id,
            user_id=owner.id,
            roles=(Role.OWNER, Role.OWNER),
            previous_roles=(),
            reason=RoleChangeReason.ROLES_CHANGED,
            session_version=1,
        )


# ---------------------------------------------------------------- the memory unit of work


def test_the_memory_store_mirrors_row_level_security() -> None:
    store = MemoryStore()
    acme, other = tenant(), tenant(name="Other")
    owner = user(acme)
    with store(acme.id) as uow:
        uow.tenants.add(acme)
        uow.users.add(owner)
        uow.subjects.add(SubjectEntry.of(owner))
    with store(other.id) as uow:
        uow.tenants.add(other)
        assert uow.tenants.get(acme.id) is None
        assert uow.users.get(owner.id) is None
        assert uow.users.list() == []
        with pytest.raises(RowSecurityViolationError):
            uow.users.add(user(acme, subject="subject-3"))
        with pytest.raises(RowSecurityViolationError):
            uow.tenants.add(acme)
    with store(None) as uow:
        assert uow.tenants.get(acme.id) is None
        assert uow.subjects.find("fake", "subject-1") == SubjectEntry.of(owner)
        assert uow.subjects.find("fake", "unknown") is None
        with pytest.raises(RowSecurityViolationError):
            uow.consents.add(
                ConsentRecord(
                    ConsentId.new(),
                    acme.id,
                    "u",
                    ConsentPurpose.TERMS,
                    False,
                    ConsentSource.API,
                    NOW,
                )
            )
    with store(acme.id) as uow:
        assert uow.tenants.get(acme.id) == acme
        assert uow.users.list() == [owner]
        uow.users.save(owner.with_roles([Role.OWNER, Role.STAFF], acme, colleagues=[], at=LATER))
    assert store.users[owner.id].session_version == 1


def test_the_memory_store_keeps_nothing_from_a_failed_unit_of_work() -> None:
    store = MemoryStore()
    acme = tenant()
    owner = user(acme)
    event = TenantCreated(
        tenant_id=acme.id, kind=acme.kind, region="in", created_by=owner.id, created_at=NOW
    )

    def sign_up_twice() -> None:
        with store(acme.id) as uow:
            uow.tenants.add(acme)
            uow.users.add(owner)
            uow.subjects.add(SubjectEntry.of(owner))
            uow.events.publish(event)
            uow.subjects.add(SubjectEntry.of(owner))

    with pytest.raises(SubjectRegisteredError):
        sign_up_twice()
    assert (store.tenants, store.users, store.subjects, store.events) == ({}, {}, {}, [])
    with store(acme.id) as uow:
        uow.tenants.add(acme)
        uow.events.publish(event)
    assert store.events == [event]
    assert store.ping()
