"""What the API layer gets from the composition root, typed by protocols and use cases."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from domain_kernel.channels import Channel
from domain_kernel.protocols import NotificationChannel
from notification.application.preferences import SetOptIn
from notification.application.send import SendNotification
from notification.domain.model import EventSink, SentLog
from notification.domain.preferences import PreferenceRepository, QuietHours
from notification.settings import NotificationSettings


@dataclass(frozen=True, slots=True)
class Wiring:
    settings: NotificationSettings
    preferences: PreferenceRepository
    sent_log: SentLog
    events: EventSink
    channels: Mapping[Channel, NotificationChannel]
    quiet_hours: QuietHours
    send: SendNotification
    set_opt_in: SetOptIn
    store_ready: Callable[[], Awaitable[bool]]
