"""Fakes for tests of this service and of services that send notifications."""

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from domain_kernel.channels import Channel
from domain_kernel.events import utc_now
from domain_kernel.ids import RuleVersionId
from domain_kernel.notifications import DeliveryReceipt, DeliveryStatus, RenderedMessage
from notification.domain.channels import OutboundMessage
from notification.domain.errors import DependencyUnavailableError
from notification.domain.ports import AttemptResult, QueueResult, ReceiptResult, RuleVersionFacts
from notification.domain.receipts import ReceiptKind
from notification.settings import NotificationSettings

BOT_TOKEN = "bot-token-for-tests"
"""A ``CW_NOTIFICATION_BOT_TOKEN`` for tests that call the receipt route."""
NOON_IST = datetime(2026, 9, 28, 6, 30, tzinfo=UTC)
"""12:00 IST, outside the default quiet hours."""
NIGHT_IST = datetime(2026, 9, 28, 17, 30, tzinfo=UTC)
"""23:00 IST, inside the default quiet hours."""


class FakeClock:
    """A clock the test moves: call it for the time, ``advance`` it by seconds."""

    def __init__(self, now: datetime = NOON_IST) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> datetime:
        self.now += timedelta(seconds=seconds)
        return self.now


class FakeChannel:
    """A channel that takes every message it could, as the real adapters decide: a WhatsApp
    message outside the 24-hour window whose template is not approved fails without a send.
    ``fail_next`` fails that many deliveries first; ``sent`` keeps the rendered messages and
    ``delivered`` the whole outbound messages."""

    def __init__(self, *, clock: Callable[[], datetime] = utc_now) -> None:
        self.sent: list[RenderedMessage] = []
        self.delivered: list[OutboundMessage] = []
        self.fail_next = 0
        self._clock = clock

    def deliver(self, message: OutboundMessage) -> DeliveryReceipt:
        if not message.deliverable:
            return DeliveryReceipt(
                DeliveryStatus.FAILED, self._clock(), error=message.undeliverable_reason()
            )
        if self.fail_next > 0:
            self.fail_next -= 1
            return DeliveryReceipt(DeliveryStatus.FAILED, self._clock(), error="fake: down")
        self.sent.append(message.rendered)
        self.delivered.append(message)
        return DeliveryReceipt(
            DeliveryStatus.SENT, self._clock(), provider_message_id=f"fake-{len(self.sent)}"
        )


def notification_settings(**overrides: Any) -> NotificationSettings:
    """Settings that ignore the repo ``.env``, on the memory store; the channels stay disabled
    by default."""
    values: dict[str, Any] = {
        "_env_file": None,
        "service_name": "notification",
        "notification_store": "memory",
    }
    values.update(overrides)
    return NotificationSettings(**values)


class FakeRuleVersionReader:
    """The rulebook's facts from a dict; ``down`` makes every read fail as an outage would."""

    def __init__(self, facts: Mapping[RuleVersionId, RuleVersionFacts] | None = None) -> None:
        self.facts = dict(facts or {})
        self.down = False
        self.calls: list[RuleVersionId] = []

    def get(self, rule_version_id: RuleVersionId) -> RuleVersionFacts | None:
        self.calls.append(rule_version_id)
        if self.down:
            raise DependencyUnavailableError("rulebook unreachable (fake)")
        return self.facts.get(rule_version_id)


class RecordingMetrics:
    """Keeps what the use cases count, for assertions."""

    def __init__(self) -> None:
        self.enqueues: list[tuple[Channel, QueueResult]] = []
        self.attempts: list[tuple[Channel, AttemptResult]] = []
        self.lags: list[tuple[Channel, float]] = []
        self.duplicates_sent: list[Channel] = []
        self.receipts: list[tuple[Channel, ReceiptKind, ReceiptResult]] = []

    def enqueued(self, channel: Channel, result: QueueResult) -> None:
        self.enqueues.append((channel, result))

    def attempted(self, channel: Channel, result: AttemptResult) -> None:
        self.attempts.append((channel, result))

    def delivery_lag(self, channel: Channel, seconds: float) -> None:
        self.lags.append((channel, seconds))

    def duplicate_sent(self, channel: Channel) -> None:
        self.duplicates_sent.append(channel)

    def receipt(self, channel: Channel, kind: ReceiptKind, result: ReceiptResult) -> None:
        self.receipts.append((channel, kind, result))
