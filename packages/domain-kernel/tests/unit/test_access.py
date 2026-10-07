from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain_kernel.access import (
    ANONYMOUS,
    MAX_CLIENT_ID_CHARS,
    MFA_REQUIRED_ROLES,
    REGULATORY_ROLES,
    TENANT_ADMIN_ROLES,
    TENANT_MEMBER_ROLES,
    Principal,
    PrincipalKind,
    Role,
    Scope,
)
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import TenantId, UserId

_USER = UserId(UUID("11111111-1111-4111-8111-111111111111"))
_TENANT = TenantId(UUID("22222222-2222-4222-8222-222222222222"))


def _owner(**overrides: object) -> Principal:
    values: dict[str, object] = {
        "kind": PrincipalKind.USER,
        "subject": str(_USER),
        "tenant_id": _TENANT,
        "roles": frozenset({Role.OWNER}),
    }
    values.update(overrides)
    return Principal(**values)  # type: ignore[arg-type]


def test_role_and_scope_values_are_the_token_claim_values() -> None:
    assert [role.value for role in Role] == [
        "owner",
        "staff",
        "ca_admin",
        "ca_staff",
        "compliance_lead",
        "analyst",
        "reviewer",
        "admin",
    ]
    assert {scope.value for scope in Scope} == {
        "tenant:act",
        "rulebook:write",
        "notification:send",
        "notification:preferences",
        "notification:receipts",
        "llm:call",
        "identity:channel-consents",
        "entitlements:read",
        "data:export",
    }


def test_role_sets() -> None:
    assert {
        Role.OWNER,
        Role.STAFF,
        Role.CA_ADMIN,
        Role.CA_STAFF,
        Role.COMPLIANCE_LEAD,
    } == TENANT_MEMBER_ROLES
    assert {Role.OWNER, Role.CA_ADMIN} == TENANT_ADMIN_ROLES
    assert TENANT_ADMIN_ROLES <= TENANT_MEMBER_ROLES
    assert {Role.ANALYST, Role.REVIEWER, Role.ADMIN} == REGULATORY_ROLES
    assert not REGULATORY_ROLES & TENANT_MEMBER_ROLES
    assert set(Role) == TENANT_MEMBER_ROLES | REGULATORY_ROLES
    assert REGULATORY_ROLES | {Role.CA_ADMIN} == MFA_REQUIRED_ROLES


def test_a_user_principal() -> None:
    principal = Principal.user(
        _USER, _TENANT, [Role.CA_ADMIN, Role.COMPLIANCE_LEAD], mfa=True, session_version=3
    )
    assert principal.kind is PrincipalKind.USER
    assert principal.subject == str(_USER)
    assert principal.user_id == _USER
    assert principal.tenant_id == _TENANT
    assert principal.roles == {Role.CA_ADMIN, Role.COMPLIANCE_LEAD}
    assert principal.scopes == frozenset()
    assert principal.mfa is True
    assert principal.session_version == 3
    assert principal.is_authenticated
    assert principal.actor_label == f"user:{_USER}"


def test_a_service_principal() -> None:
    principal = Principal.service("pipeline", [Scope.RULEBOOK_WRITE, Scope.LLM_CALL])
    assert principal.kind is PrincipalKind.SERVICE
    assert principal.subject == "pipeline"
    assert principal.user_id is None
    assert principal.tenant_id is None
    assert principal.roles == frozenset()
    assert principal.scopes == {Scope.RULEBOOK_WRITE, Scope.LLM_CALL}
    assert principal.is_authenticated
    assert principal.actor_label == "service:pipeline"


def test_a_bound_service_principal() -> None:
    principal = Principal.service(
        "identity", [Scope.DATA_EXPORT], acts_for=_TENANT, audience="applicability-engine"
    )
    assert (principal.tenant_id, principal.acts_for) == (None, _TENANT)
    assert principal.audience == "applicability-engine"
    assert principal.actor_label == "service:identity"


def test_the_anonymous_principal() -> None:
    assert ANONYMOUS.kind is PrincipalKind.ANONYMOUS
    assert Principal(PrincipalKind.ANONYMOUS) == ANONYMOUS
    assert not ANONYMOUS.is_authenticated
    assert ANONYMOUS.user_id is None
    assert ANONYMOUS.actor_label == "anonymous"
    assert not ANONYMOUS.has_role(*Role)
    assert not any(ANONYMOUS.has_scope(scope) for scope in Scope)


def test_has_role_is_true_for_any_of_the_roles_given() -> None:
    principal = Principal.user(_USER, _TENANT, [Role.STAFF])
    assert principal.has_role(Role.STAFF)
    assert principal.has_role(Role.OWNER, Role.STAFF)
    assert not principal.has_role(Role.OWNER, Role.CA_ADMIN)
    assert not principal.has_role()


def test_has_scope() -> None:
    principal = Principal.service("whatsapp-bot", [Scope.NOTIFICATION_PREFERENCES])
    assert principal.has_scope(Scope.NOTIFICATION_PREFERENCES)
    assert not principal.has_scope(Scope.NOTIFICATION_SEND)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"tenant_id": None}, "belongs to a tenant"),
        ({"scopes": frozenset({Scope.TENANT_ACT})}, "roles, not scopes"),
        ({"subject": "not-a-uuid"}, "subject is its user id"),
        ({"subject": "11111111111141118111111111111111"}, "subject is its user id"),
        ({"subject": ""}, "must not be blank"),
        ({"roles": frozenset({"owner"})}, "Role members"),
        ({"roles": {Role.OWNER}}, "roles must be frozenset"),
        ({"tenant_id": UUID(int=5)}, "tenant_id must be TenantId"),
        ({"mfa": 1}, "mfa must be bool"),
        ({"session_version": -1}, "at least 0"),
        ({"kind": "user"}, "kind must be PrincipalKind"),
        ({"acts_for": _TENANT}, "only a service token is bound"),
        ({"audience": "profile"}, "only a service token is bound"),
    ],
)
def test_user_invariants(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(InvariantViolationError, match=message):
        _owner(**overrides)


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"subject": ""}, "must not be blank"),
        ({"subject": " pipeline"}, "leading or trailing whitespace"),
        ({"subject": "p" * (MAX_CLIENT_ID_CHARS + 1)}, "at most 128 characters"),
        ({"subject": "pipeline", "tenant_id": _TENANT}, "belongs to no tenant"),
        ({"subject": "pipeline", "roles": frozenset({Role.ADMIN})}, "scopes, not roles"),
        ({"subject": "pipeline", "scopes": frozenset({"llm:call"})}, "Scope members"),
        ({"subject": "identity", "acts_for": _TENANT}, "names both its tenant"),
        ({"subject": "identity", "audience": "profile"}, "names both its tenant"),
        ({"subject": "identity", "acts_for": UUID(int=5), "audience": "x"}, "must be TenantId"),
        ({"subject": "identity", "acts_for": _TENANT, "audience": "Profile"}, "service name"),
        ({"subject": "identity", "acts_for": _TENANT, "audience": "a b"}, "service name"),
        ({"subject": "identity", "acts_for": _TENANT, "audience": "p" * 65}, "service name"),
    ],
)
def test_service_invariants(values: dict[str, object], message: str) -> None:
    with pytest.raises(InvariantViolationError, match=message):
        Principal(PrincipalKind.SERVICE, **values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "values",
    [
        {"subject": "someone"},
        {"tenant_id": _TENANT},
        {"roles": frozenset({Role.STAFF})},
        {"scopes": frozenset({Scope.TENANT_ACT})},
        {"mfa": True},
        {"session_version": 1},
        {"acts_for": _TENANT},
        {"audience": "profile"},
    ],
)
def test_the_anonymous_principal_carries_nothing(values: dict[str, object]) -> None:
    with pytest.raises(InvariantViolationError, match="anonymous principal has no"):
        Principal(PrincipalKind.ANONYMOUS, **values)  # type: ignore[arg-type]


def test_user_needs_a_user_id() -> None:
    with pytest.raises(InvariantViolationError, match="user_id must be UserId"):
        Principal.user(_TENANT, _TENANT, [Role.OWNER])  # type: ignore[arg-type]


def test_principals_are_frozen_values() -> None:
    principal = Principal.service("qa", [Scope.LLM_CALL])
    assert principal == Principal.service("qa", {Scope.LLM_CALL})
    assert hash(principal) == hash(Principal.service("qa", {Scope.LLM_CALL}))
    with pytest.raises(AttributeError):
        principal.subject = "other"  # type: ignore[misc]


@given(
    held=st.frozensets(st.sampled_from(Role)),
    asked=st.lists(st.sampled_from(Role), max_size=4),
)
def test_has_role_matches_set_intersection(held: frozenset[Role], asked: list[Role]) -> None:
    principal = Principal.user(_USER, _TENANT, held)
    assert principal.has_role(*asked) == bool(held & set(asked))
