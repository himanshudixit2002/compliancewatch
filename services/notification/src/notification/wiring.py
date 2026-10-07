"""What the API layer gets from the composition root, typed by protocols and use cases only, so
the api package never imports infrastructure (import-linter keeps api and infrastructure apart)."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from domain_kernel.channels import Channel
from domain_kernel.erasure import ErasedTenants
from notification.application.bulk import BulkNotify
from notification.application.dispatch import DispatchDue
from notification.application.email_feedback import ReceiveEmailFeedback
from notification.application.enqueue import EnqueueNotifications
from notification.application.export import ExportTenantData
from notification.application.history import GetNotification, ListNotifications
from notification.application.preferences import GetPreference, SetOptIn, SetPreference
from notification.application.receipts import ReconcileReceipts
from notification.application.recipients import (
    GetRecipient,
    ListRecipients,
    RegisterRecipient,
    RemoveRecipient,
)
from notification.application.resend import ResendNotification
from notification.application.retention import PurgeExpired
from notification.application.send import SendNow
from notification.domain.channels import ChannelAdapter
from notification.domain.preferences import QuietHours
from notification.domain.repository import UnitOfWorkFactory, WorkIndex
from notification.settings import NotificationSettings
from py_common.idempotency import IdempotencyStore


@dataclass(frozen=True, slots=True)
class Wiring:
    settings: NotificationSettings
    unit_of_work: UnitOfWorkFactory
    work_index: WorkIndex
    channels: Mapping[Channel, ChannelAdapter]
    quiet_hours: QuietHours
    send: SendNow
    enqueue: EnqueueNotifications
    bulk: BulkNotify
    idempotency: IdempotencyStore
    dispatch: DispatchDue
    set_opt_in: SetOptIn
    set_preference: SetPreference
    """The route's: ``set_opt_in`` once a web opt-in is known to be covered by a consent."""
    get_preference: GetPreference
    register_recipient: RegisterRecipient
    get_recipient: GetRecipient
    list_recipients: ListRecipients
    remove_recipient: RemoveRecipient
    purge: PurgeExpired
    get_notification: GetNotification
    list_notifications: ListNotifications
    resend: ResendNotification
    export: ExportTenantData
    reconcile: ReconcileReceipts
    email_feedback: ReceiveEmailFeedback
    store_ready: Callable[[], Awaitable[bool]]
    erased_tenants: ErasedTenants
    """The tenants the notification service has erased: its routes answer them 410."""
