"""notification.sent and notification.failed serialise to messages the published schemas accept."""

from datetime import UTC, datetime

from cw_contracts.events import TOPICS, EventEnvelopeV1
from domain_kernel.channels import Channel
from domain_kernel.events import DomainEvent
from domain_kernel.ids import BusinessId, NotificationId, ObligationId, TenantId
from notification.domain.events import NotificationFailed, NotificationSent
from py_common.events import decode, encode, to_message

NOW = datetime(2026, 9, 28, 6, 30, tzinfo=UTC)
COMMON: dict[str, object] = {
    "tenant_id": TenantId.new(),
    "notification_id": NotificationId.new(),
    "obligation_id": ObligationId.new(),
    "business_id": BusinessId.new(),
    "channel": Channel.WHATSAPP,
    "dedupe_key": "f" * 64,
}


def check(event: DomainEvent) -> None:
    message = decode(encode(to_message(event)))
    EventEnvelopeV1.model_validate(message.model_dump(mode="json"))
    spec = TOPICS[message.topic]
    assert message.schema_version == spec.version
    assert spec.tenant_scoped
    spec.model.model_validate(message.payload)


def test_sent_matches_its_schema() -> None:
    check(NotificationSent(sent_at=NOW, language="hi", provider_message_id="wamid.1", **COMMON))  # type: ignore[arg-type]
    check(NotificationSent(sent_at=NOW, language="en", **COMMON))  # type: ignore[arg-type]


def test_failed_matches_its_schema() -> None:
    check(NotificationFailed(error="down", attempts=2, will_retry=True, failed_at=NOW, **COMMON))  # type: ignore[arg-type]
