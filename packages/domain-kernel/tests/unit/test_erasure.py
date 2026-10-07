"""What one service's erasure says it did, the event that carries it and its audit entry."""

from datetime import UTC, datetime, timedelta

import pytest

from domain_kernel.audit import AuditActorKind
from domain_kernel.erasure import (
    ERASED_ACTION,
    ERASURE_REFUSED_ACTION,
    DeletionRequest,
    Erased,
    ErasureCheck,
    Retained,
    TenantDataErased,
    counts,
    erasure_audit_entry,
    erasure_group,
    erasure_refusal,
    refusal_audit_entry,
    retained,
)
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import CorrelationId, EventId, TenantId

AT = datetime(2000, 1, 12, 4, 30, tzinfo=UTC)
TENANT = TenantId.new()


def request() -> DeletionRequest:
    return DeletionRequest(
        event_id=EventId.new(),
        tenant_id=TENANT,
        correlation_id=CorrelationId.new(),
        requested_at=AT - timedelta(days=1),
        deadline_at=AT + timedelta(days=29),
    )


def test_erased_keeps_its_counts_read_only_and_adds_them_up() -> None:
    erased = Erased({"profile_node": 3, "profile_version": 0}, retained(("outbox_event", "relay")))
    assert erased.rows == 3
    assert dict(erased.tables) == {"profile_node": 3, "profile_version": 0}
    with pytest.raises(TypeError):
        erased.tables["profile_node"] = 1  # type: ignore[index]


@pytest.mark.parametrize("rows", [-1, True, 1.5])
def test_a_count_is_a_whole_number(rows: object) -> None:
    with pytest.raises(InvariantViolationError):
        Erased({"profile_node": rows})  # type: ignore[dict-item]


def test_a_retained_table_is_named_once_with_a_reason() -> None:
    with pytest.raises(InvariantViolationError, match="once"):
        Erased({}, retained(("review_task", "regulatory"), ("review_task", "again")))
    with pytest.raises(InvariantViolationError):
        Retained("review_task", " ")
    with pytest.raises(InvariantViolationError):
        Retained("Review Task", "regulatory")


def test_the_event_answers_the_request_it_was_caused_by() -> None:
    asked = request()
    erased = Erased({"obligation": 2}, retained(("rule_version_ref", "rule-level")))
    event = TenantDataErased.answering(asked, "obligation", erased, AT)
    assert event.tenant_id == TENANT
    assert event.causation_id == asked.event_id
    assert event.deletion_event_id == asked.event_id
    assert event.correlation_id == asked.correlation_id
    assert (event.erased_at, event.occurred_at) == (AT, AT)
    assert dict(event.tables) == {"obligation": 2}
    assert event.retained == erased.retained


def test_the_event_names_a_tenant_and_a_service() -> None:
    with pytest.raises(InvariantViolationError, match="tenant"):
        TenantDataErased(service="profile", deletion_event_id=EventId.new(), erased_at=AT)
    with pytest.raises(InvariantViolationError, match="service"):
        TenantDataErased(
            tenant_id=TENANT, service="Profile", deletion_event_id=EventId.new(), erased_at=AT
        )


def test_the_audit_entry_is_the_service_s_own_with_the_counts() -> None:
    event = TenantDataErased.answering(
        request(), "notification", Erased({"recipient": 1}, retained(("suppression", "x"))), AT
    )
    entry = erasure_audit_entry(event)
    assert entry.action == ERASED_ACTION
    assert (entry.tenant_id, entry.subject_type, entry.subject_id) == (
        TENANT,
        "tenant",
        str(TENANT),
    )
    assert (entry.actor.kind, entry.actor.label) == (AuditActorKind.SYSTEM, "system:notification")
    assert entry.after is not None
    assert entry.after["tables"] == {"recipient": 1}
    assert entry.after["retained"] == ("suppression",)
    assert entry.correlation_id == str(event.correlation_id)
    assert entry.occurred_at == AT


def test_groups_and_counts() -> None:
    assert erasure_group("applicability-engine") == "applicability-engine.erasure"
    assert counts([("a", 1), ("b", 2), ("a", 3)]) == {"a": 4, "b": 2}


def test_an_erasure_runs_only_for_the_event_identity_sent_for_a_tenant_being_deleted() -> None:
    asked = request()
    sent = ErasureCheck(TENANT, "deletion_requested", deletion_event_id=asked.event_id)
    assert erasure_refusal(sent, asked) is None
    erased = ErasureCheck(TENANT, "erased", deletion_event_id=asked.event_id)
    assert erasure_refusal(erased, asked) is None, "another service's erasure, or a second pass"
    refused = {
        "another tenant": ErasureCheck(TenantId.new(), "deletion_requested"),
        "unknown": ErasureCheck(TENANT, None),
        "internal": ErasureCheck(
            TENANT, "deletion_requested", internal=True, deletion_event_id=asked.event_id
        ),
        "active": ErasureCheck(TENANT, "active", deletion_event_id=asked.event_id),
        "no request": ErasureCheck(TENANT, "deletion_requested"),
        "other event": ErasureCheck(TENANT, "deletion_requested", deletion_event_id=EventId.new()),
    }
    reasons = {name: erasure_refusal(check, asked) for name, check in refused.items()}
    assert reasons == {
        "another tenant": "identity answered for another tenant",
        "unknown": "identity holds no such tenant",
        "internal": "the internal tenant is never erased",
        "active": "the tenant is active, not being deleted",
        "no request": "the tenant has no open deletion request",
        "other event": (
            "the event is not the one identity sent for the tenant's open deletion request"
        ),
    }
    with pytest.raises(InvariantViolationError):
        ErasureCheck(TENANT, "", deletion_event_id=asked.event_id)


def test_a_refusal_is_audited_by_the_service_with_the_event_and_why() -> None:
    asked = request()
    entry = refusal_audit_entry("profile", asked, "the tenant is active, not being deleted", AT)
    assert (entry.action, entry.tenant_id, entry.subject_id) == (
        ERASURE_REFUSED_ACTION,
        TENANT,
        str(TENANT),
    )
    assert entry.actor.label == "system:profile"
    assert entry.after == {
        "service": "profile",
        "deletion_event_id": str(asked.event_id),
        "refused": "the tenant is active, not being deleted",
    }
    assert entry.correlation_id == str(asked.correlation_id)


def test_the_erased_entry_carries_a_service_s_details() -> None:
    event = TenantDataErased.answering(request(), "identity", Erased({"app_user": 1}), AT)
    entry = erasure_audit_entry(event, details={"other_provider_accounts": []})
    assert entry.after is not None
    assert entry.after["other_provider_accounts"] == ()
    assert entry.after["tables"] == {"app_user": 1}
