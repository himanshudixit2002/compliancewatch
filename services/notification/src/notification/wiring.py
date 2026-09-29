"""What the API layer gets from the composition root, typed by protocols and use cases only, so
the api package never imports infrastructure (import-linter keeps api and infrastructure apart)."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from domain_kernel.channels import Channel
from domain_kernel.protocols import NotificationChannel
from notification.application.dispatch import DispatchDue
from notification.application.enqueue import EnqueueNotifications
from notification.application.preferences import GetPreference, SetOptIn
from notification.application.recipients import GetRecipient, RegisterRecipient, RemoveRecipient
from notification.application.retention import PurgeExpired
from notification.application.send import SendNow
from notification.domain.preferences import QuietHours
from notification.domain.repository import UnitOfWorkFactory, WorkIndex
from notification.settings import NotificationSettings


@dataclass(frozen=True, slots=True)
class Wiring:
    settings: NotificationSettings
    unit_of_work: UnitOfWorkFactory
    work_index: WorkIndex
    channels: Mapping[Channel, NotificationChannel]
    quiet_hours: QuietHours
    send: SendNow
    enqueue: EnqueueNotifications
    dispatch: DispatchDue
    set_opt_in: SetOptIn
    get_preference: GetPreference
    register_recipient: RegisterRecipient
    get_recipient: GetRecipient
    remove_recipient: RemoveRecipient
    purge: PurgeExpired
    store_ready: Callable[[], Awaitable[bool]]
