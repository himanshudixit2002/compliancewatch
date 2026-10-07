"""Who the rulebook's audit entries name: the request's verified user with their roles, a person
the use case names, a service client, or the rulebook itself; and the platform entry shape."""

from datetime import UTC, datetime
from uuid import UUID

import structlog

from domain_kernel.access import Principal, Role, Scope
from domain_kernel.audit import AuditActor
from domain_kernel.ids import TenantId, UserId
from domain_kernel.knowledge import EntityType
from py_common.audit import CORRELATION_FIELD
from py_common.auth.context import principal_bound
from rulebook.application.audit import actor_for, entry
from rulebook.application.review import group_key

ANALYST = UserId(UUID(int=71))
OTHER = UserId(UUID(int=72))
TENANT = TenantId(UUID(int=73))
AT = datetime(2000, 1, 3, 4, 30, tzinfo=UTC)


def test_the_bound_user_is_named_with_their_roles_when_they_act() -> None:
    principal = Principal.user(ANALYST, TENANT, [Role.ANALYST])
    with principal_bound(principal):
        assert actor_for(ANALYST) == AuditActor.user(ANALYST, [Role.ANALYST])
        assert actor_for(str(ANALYST)) == AuditActor.user(ANALYST, [Role.ANALYST])
        assert actor_for(OTHER) == AuditActor.user(OTHER), "another person: no roles known"
        assert actor_for(None) == AuditActor.user(ANALYST, [Role.ANALYST])


def test_without_a_user_the_service_client_or_the_rulebook_acts() -> None:
    assert actor_for(None) == AuditActor.system("rulebook")
    assert actor_for("analyst@example.invalid") == AuditActor.system("rulebook")
    assert actor_for(f"{{{OTHER}}}") == AuditActor.system("rulebook"), "not canonical"
    assert actor_for(OTHER) == AuditActor.user(OTHER)
    service = Principal.service("example-pipeline", [next(iter(Scope))])
    with principal_bound(service):
        assert actor_for("example-pipeline") == AuditActor.service("example-pipeline")


def test_an_entry_is_a_platform_row_with_the_requests_correlation_id() -> None:
    structlog.contextvars.bind_contextvars(**{CORRELATION_FIELD: "a" * 32})
    try:
        made = entry(
            "rule_version.approved",
            "rule_version",
            UUID(int=74),
            AuditActor.user(ANALYST),
            at=AT,
            before={"status": "in_review"},
            after={"status": "approved"},
            reason="Example note",
        )
    finally:
        structlog.contextvars.unbind_contextvars(CORRELATION_FIELD)
    assert (made.tenant_id, made.subject_id, made.correlation_id, made.occurred_at) == (
        None,
        str(UUID(int=74)),
        "a" * 32,
        AT,
    )
    assert made.reason == "Example note"


def test_a_group_key_fits_a_subject_id() -> None:
    assert group_key(EntityType.FORM, "example return") == "form:example return"
    long_key = group_key(EntityType.FORM, "x" * 400)
    assert long_key.startswith("form:sha256:")
    assert len(long_key) <= 200
