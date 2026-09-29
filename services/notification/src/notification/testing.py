"""Fakes for tests of this service and of services that send notifications."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from domain_kernel.events import utc_now
from domain_kernel.notifications import DeliveryReceipt, DeliveryStatus, RenderedMessage
from notification.settings import NotificationSettings

NOON_IST = datetime(2026, 9, 28, 6, 30, tzinfo=UTC)
"""12:00 IST, outside the default quiet hours."""
NIGHT_IST = datetime(2026, 9, 28, 17, 30, tzinfo=UTC)
"""23:00 IST, inside the default quiet hours."""


class FakeChannel:
    def __init__(self, *, clock: Callable[[], datetime] = utc_now) -> None:
        self.sent: list[RenderedMessage] = []
        self.fail_next = 0
        self._clock = clock

    def send(self, message: RenderedMessage) -> DeliveryReceipt:
        if self.fail_next > 0:
            self.fail_next -= 1
            return DeliveryReceipt(DeliveryStatus.FAILED, self._clock(), error="fake: down")
        self.sent.append(message)
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
