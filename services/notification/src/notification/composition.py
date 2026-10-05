"""The composition root's wiring, shared by the API process and the worker.

Guide section 11: wiring of interfaces to implementations happens here, never inside the layers. The
use cases run on the Postgres unit of work (row-level security by tenant, events through the outbox)
unless ``CW_NOTIFICATION_STORE=memory``. The WhatsApp channel is real only behind
``CW_WHATSAPP_ENABLED`` with a phone number id and an access token, and the email channel only
behind ``CW_EMAIL_ENABLED`` with ``CW_SMTP_HOST`` and ``CW_EMAIL_FROM``; with
``CW_NOTIFICATION_CHANNELS=sink`` (local and test only) both are the sink, which records each
message in ``CW_NOTIFICATION_SINK_PATH`` instead of sending it. The SES feedback is read
from SNS with its signature verified. The dispatcher reads the facts of change cards from the
rulebook at ``CW_RULEBOOK_URL``, and a CA firm's bulk notification reads its clients' open
obligations from the obligation service at ``CW_OBLIGATION_URL``, both with the service's own
access token once ``CW_SERVICE_CLIENT_SECRET`` is set; deliveries are counted through
OpenTelemetry. The bulk route's Idempotency-Keys are kept next to the notifications
(``idempotency_key``, migration 0003), each key in its own short transaction. ``wire(settings,
channels=..., rules=..., email_feedback=..., obligations=...)`` replaces the channels, the
rulebook reader, the SES feedback reader and the obligation reader, which is how the demo and the
tests send and receive through fakes; and ``token_source=`` replaces where the readers' access
token comes from, which is how a process that hosts identity gives them a token minted in the
process.

``notification.main`` builds the HTTP app on it and ``notification.worker`` the worker's
components; this module builds no app, so the worker does not start the API's telemetry.
"""

from collections.abc import Callable, Mapping
from pathlib import Path

from starlette.concurrency import run_in_threadpool

from domain_kernel.channels import Channel
from notification.application.bulk import BulkNotify
from notification.application.dispatch import DispatchDue
from notification.application.email_feedback import ReceiveEmailFeedback
from notification.application.enqueue import EnqueueNotifications
from notification.application.history import GetNotification, ListNotifications
from notification.application.preferences import GetPreference, SetOptIn
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
from notification.domain.policy import BatchPolicy, DigestPolicy
from notification.domain.ports import EmailFeedbackReader, ObligationReader, RuleVersionReader
from notification.domain.preferences import QuietHours
from notification.domain.repository import UnitOfWorkFactory, WorkIndex
from notification.infrastructure.email import SmtpEmailChannel
from notification.infrastructure.memory import MemoryStore
from notification.infrastructure.metrics import OtelDeliveryMetrics
from notification.infrastructure.obligation_client import HttpObligationReader
from notification.infrastructure.repository import PostgresUnitOfWorkFactory
from notification.infrastructure.rulebook_client import HttpRuleVersionReader
from notification.infrastructure.ses_feedback import SnsFeedbackReader
from notification.infrastructure.sink import SinkChannel
from notification.infrastructure.whatsapp import DisabledChannel, WhatsAppCloudChannel
from notification.settings import NotificationSettings
from notification.wiring import Wiring
from py_common.auth import TokenSource, service_auth_from
from py_common.idempotency import IdempotencyStore, MemoryIdempotencyStore
from py_common.idempotency.sqlalchemy import SqlAlchemyIdempotencyStore

WHATSAPP_DISABLED = "whatsapp channel disabled: set CW_WHATSAPP_ENABLED and the Meta credentials"
EMAIL_DISABLED = "email channel disabled: set CW_EMAIL_ENABLED, CW_SMTP_HOST and CW_EMAIL_FROM"


def default_channels(settings: NotificationSettings) -> dict[Channel, ChannelAdapter]:
    """The channels the settings enable; a disabled one fails every send with the reason. The
    sink stands in for both when the settings choose it."""
    if settings.notification_channels == "sink":
        sink = SinkChannel(Path(settings.notification_sink_path))
        return {Channel.WHATSAPP: sink, Channel.EMAIL: sink}
    whatsapp: ChannelAdapter
    if (
        settings.whatsapp_enabled
        and settings.whatsapp_phone_number_id
        and settings.whatsapp_access_token is not None
    ):
        whatsapp = WhatsAppCloudChannel(
            settings.whatsapp_phone_number_id,
            settings.whatsapp_access_token.get_secret_value(),
            api_version=settings.whatsapp_api_version,
        )
    else:
        whatsapp = DisabledChannel(WHATSAPP_DISABLED)
    email: ChannelAdapter
    if settings.email_enabled and settings.smtp_host and settings.email_from:
        email = SmtpEmailChannel(
            settings.smtp_host,
            settings.smtp_port,
            sender=settings.email_from,
            username=settings.smtp_username,
            password=""
            if settings.smtp_password is None
            else settings.smtp_password.get_secret_value(),
        )
    else:
        email = DisabledChannel(EMAIL_DISABLED)
    return {Channel.WHATSAPP: whatsapp, Channel.EMAIL: email}


def wire(
    settings: NotificationSettings,
    *,
    channels: Mapping[Channel, ChannelAdapter] | None = None,
    rules: RuleVersionReader | None = None,
    email_feedback: EmailFeedbackReader | None = None,
    obligations: ObligationReader | None = None,
    token_source: TokenSource | None = None,
) -> Wiring:
    unit_of_work: UnitOfWorkFactory
    work_index: WorkIndex
    ping: Callable[[], bool]
    idempotency: IdempotencyStore
    if settings.notification_store == "memory":
        memory = MemoryStore()
        unit_of_work, work_index, ping = memory, memory.work_index, memory.ping
        idempotency = MemoryIdempotencyStore()
    else:
        postgres = PostgresUnitOfWorkFactory.from_url(settings.database_url)
        unit_of_work, work_index, ping = postgres, postgres.work_index, postgres.ping
        idempotency = SqlAlchemyIdempotencyStore(postgres.engine)
    auth = service_auth_from(settings, token_source=token_source)
    wired_channels = dict(default_channels(settings) if channels is None else channels)
    quiet_hours = QuietHours.parse(settings.quiet_hours_start, settings.quiet_hours_end)
    batch = BatchPolicy(window_seconds=settings.notification_batch_window_seconds)
    metrics = OtelDeliveryMetrics()
    dispatch = DispatchDue(
        unit_of_work,
        work_index,
        wired_channels,
        rules=rules or HttpRuleVersionReader(settings.rulebook_url, auth=auth),
        web_base_url=settings.web_base_url,
        quiet_hours=quiet_hours,
        batch=batch,
        metrics=metrics,
    )

    reconcile = ReconcileReceipts(unit_of_work, work_index, metrics=metrics)
    enqueue = EnqueueNotifications(
        unit_of_work,
        batch=batch,
        digest=DigestPolicy.parse(settings.notification_digest_at),
        metrics=metrics,
    )

    async def store_ready() -> bool:
        return await run_in_threadpool(ping)

    return Wiring(
        settings=settings,
        unit_of_work=unit_of_work,
        work_index=work_index,
        channels=wired_channels,
        quiet_hours=quiet_hours,
        send=SendNow(unit_of_work, dispatch, quiet_hours=quiet_hours),
        enqueue=enqueue,
        bulk=BulkNotify(
            unit_of_work,
            enqueue,
            obligations or HttpObligationReader(settings.obligation_url, auth=auth),
            enabled=settings.notification_bulk_enabled,
        ),
        idempotency=idempotency,
        dispatch=dispatch,
        set_opt_in=SetOptIn(unit_of_work),
        get_preference=GetPreference(unit_of_work),
        register_recipient=RegisterRecipient(unit_of_work),
        get_recipient=GetRecipient(unit_of_work),
        list_recipients=ListRecipients(unit_of_work),
        remove_recipient=RemoveRecipient(unit_of_work),
        purge=PurgeExpired(unit_of_work, work_index),
        get_notification=GetNotification(unit_of_work),
        list_notifications=ListNotifications(unit_of_work),
        resend=ResendNotification(unit_of_work),
        reconcile=reconcile,
        email_feedback=ReceiveEmailFeedback(
            email_feedback or SnsFeedbackReader(topic_arn=settings.notification_ses_topic_arn),
            reconcile,
        ),
        store_ready=store_ready,
    )
