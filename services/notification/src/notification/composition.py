"""The composition root's wiring, shared by the API process and the worker.

Guide section 11: wiring of interfaces to implementations happens here, never inside the layers.
The use cases run on the Postgres unit of work (row-level security by tenant, events through the
outbox) unless ``CW_NOTIFICATION_STORE=memory``. The WhatsApp channel is real only behind
``CW_WHATSAPP_ENABLED`` with a phone number id and an access token. The dispatcher reads the
facts of change cards from the rulebook at ``CW_RULEBOOK_URL`` and counts deliveries through
OpenTelemetry. ``wire(settings, channels=..., rules=...)`` replaces the channels and the
rulebook reader, which is how the demo and the tests send through fakes.

``notification.main`` builds the HTTP app on it and ``notification.worker`` the worker's
components; this module builds no app, so the worker does not start the API's telemetry.
"""

from collections.abc import Callable, Mapping

from starlette.concurrency import run_in_threadpool

from domain_kernel.channels import Channel
from domain_kernel.protocols import NotificationChannel
from notification.application.dispatch import DispatchDue
from notification.application.enqueue import EnqueueNotifications
from notification.application.preferences import GetPreference, SetOptIn
from notification.application.recipients import GetRecipient, RegisterRecipient, RemoveRecipient
from notification.application.retention import PurgeExpired
from notification.application.send import SendNow
from notification.domain.policy import BatchPolicy, DigestPolicy
from notification.domain.ports import RuleVersionReader
from notification.domain.preferences import QuietHours
from notification.domain.repository import UnitOfWorkFactory, WorkIndex
from notification.infrastructure.memory import MemoryStore
from notification.infrastructure.metrics import OtelDeliveryMetrics
from notification.infrastructure.repository import PostgresUnitOfWorkFactory
from notification.infrastructure.rulebook_client import HttpRuleVersionReader
from notification.infrastructure.whatsapp import DisabledChannel, WhatsAppCloudChannel
from notification.settings import NotificationSettings
from notification.wiring import Wiring

WHATSAPP_DISABLED = "whatsapp channel disabled: set CW_WHATSAPP_ENABLED and the Meta credentials"
EMAIL_DISABLED = "email channel not wired yet (SES arrives with deploy)"


def default_channels(settings: NotificationSettings) -> dict[Channel, NotificationChannel]:
    """The channels the settings enable; a disabled one fails every send with the reason."""
    whatsapp: NotificationChannel
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
    return {Channel.WHATSAPP: whatsapp, Channel.EMAIL: DisabledChannel(EMAIL_DISABLED)}


def wire(
    settings: NotificationSettings,
    *,
    channels: Mapping[Channel, NotificationChannel] | None = None,
    rules: RuleVersionReader | None = None,
) -> Wiring:
    unit_of_work: UnitOfWorkFactory
    work_index: WorkIndex
    ping: Callable[[], bool]
    if settings.notification_store == "memory":
        memory = MemoryStore()
        unit_of_work, work_index, ping = memory, memory.work_index, memory.ping
    else:
        postgres = PostgresUnitOfWorkFactory.from_url(settings.database_url)
        unit_of_work, work_index, ping = postgres, postgres.work_index, postgres.ping
    wired_channels = dict(default_channels(settings) if channels is None else channels)
    quiet_hours = QuietHours.parse(settings.quiet_hours_start, settings.quiet_hours_end)
    batch = BatchPolicy(window_seconds=settings.notification_batch_window_seconds)
    metrics = OtelDeliveryMetrics()
    dispatch = DispatchDue(
        unit_of_work,
        work_index,
        wired_channels,
        rules=rules or HttpRuleVersionReader(settings.rulebook_url),
        web_base_url=settings.web_base_url,
        quiet_hours=quiet_hours,
        batch=batch,
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
        enqueue=EnqueueNotifications(
            unit_of_work,
            batch=batch,
            digest=DigestPolicy.parse(settings.notification_digest_at),
            metrics=metrics,
        ),
        dispatch=dispatch,
        set_opt_in=SetOptIn(unit_of_work),
        get_preference=GetPreference(unit_of_work),
        register_recipient=RegisterRecipient(unit_of_work),
        get_recipient=GetRecipient(unit_of_work),
        remove_recipient=RemoveRecipient(unit_of_work),
        purge=PurgeExpired(unit_of_work, work_index),
        store_ready=store_ready,
    )
