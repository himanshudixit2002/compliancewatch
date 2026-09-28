"""The service's events serialise to messages the published event schemas accept."""

from datetime import UTC, datetime

from cw_contracts.events import TOPICS, EventEnvelopeV1
from domain_kernel.ids import BusinessId, DecisionId, ObligationId, RuleVersionId, TenantId, UserId
from domain_kernel.status import ClosureReason, ObligationStatus
from obligation.domain.events import (
    ObligationClosed,
    ObligationCreated,
    ObligationRescheduled,
    RescheduleReason,
)
from py_common.events import decode, encode, to_message

NOW = datetime(2026, 10, 1, 2, 31, 5, tzinfo=UTC)
TENANT = TenantId.new()


def check(event: object) -> None:
    message = decode(encode(to_message(event)))  # type: ignore[arg-type]
    EventEnvelopeV1.model_validate(message.model_dump(mode="json"))
    spec = TOPICS[message.topic]
    assert message.schema_version == spec.version
    assert spec.tenant_scoped
    assert message.tenant_id == TENANT.value
    spec.model.model_validate(message.payload)


def test_obligation_created_matches_its_schema() -> None:
    check(
        ObligationCreated(
            tenant_id=TENANT,
            obligation_id=ObligationId.new(),
            business_id=BusinessId.new(),
            rule_version_id=RuleVersionId.new(),
            decision_id=DecisionId.new(),
            title="File GSTR-3B (2026-09)",
            steps=("Reconcile", "File"),
            due_at=NOW,
            evidence_type="filing_acknowledgement",
        )
    )
    check(
        ObligationCreated(
            tenant_id=TENANT,
            obligation_id=ObligationId.new(),
            business_id=BusinessId.new(),
            rule_version_id=RuleVersionId.new(),
            decision_id=DecisionId.new(),
            title="Display the certificate",
            steps=(),
            due_at=None,
        )
    )


def test_obligation_rescheduled_matches_its_schema() -> None:
    check(
        ObligationRescheduled(
            tenant_id=TENANT,
            obligation_id=ObligationId.new(),
            business_id=BusinessId.new(),
            rule_version_id=RuleVersionId.new(),
            previous_due_at=NOW,
            new_due_at=NOW,
            reason=RescheduleReason.DEADLINE_EXTENDED,
            caused_by_rule_version_id=RuleVersionId.new(),
        )
    )


def test_obligation_closed_matches_its_schema() -> None:
    check(
        ObligationClosed(
            tenant_id=TENANT,
            obligation_id=ObligationId.new(),
            business_id=BusinessId.new(),
            rule_version_id=RuleVersionId.new(),
            status=ObligationStatus.DONE,
            reason=ClosureReason.COMPLETED,
            closed_at=NOW,
            closed_by=UserId.new(),
        )
    )
