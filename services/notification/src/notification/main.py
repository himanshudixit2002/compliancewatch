"""Composition root for the notification service.

Guide section 11: wiring of interfaces to implementations happens here, never inside the layers.
The use cases run on the Postgres unit of work (row-level security by tenant, events through the
outbox) unless ``CW_NOTIFICATION_STORE=memory``. The WhatsApp channel is real only behind
``CW_WHATSAPP_ENABLED`` with a phone number id and an access token. ``build_app(settings,
channels=...)`` replaces the channels, which is how the demo and the tests send through a fake.
"""

from collections.abc import Callable, Mapping

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from domain_kernel.channels import Channel
from domain_kernel.errors import DomainError
from domain_kernel.protocols import NotificationChannel
from notification import __version__
from notification.api.router import router
from notification.application.preferences import GetPreference, SetOptIn
from notification.application.send import SendNotification
from notification.domain.errors import (
    InvalidAddressError,
    MissingPlaceholderError,
    TenantRequiredError,
    UnknownChannelError,
    UnknownTemplateError,
)
from notification.domain.preferences import QuietHours
from notification.domain.repository import UnitOfWorkFactory, WorkIndex
from notification.infrastructure.memory import MemoryStore
from notification.infrastructure.repository import PostgresUnitOfWorkFactory
from notification.infrastructure.whatsapp import DisabledChannel, WhatsAppCloudChannel
from notification.settings import NotificationSettings
from notification.wiring import Wiring
from py_common.app import create_app

SERVICE_NAME = "notification"
PROBLEM_STATUS: dict[type[DomainError], int] = {
    TenantRequiredError: 401,
    UnknownTemplateError: 422,
    MissingPlaceholderError: 422,
    InvalidAddressError: 422,
    UnknownChannelError: 503,
}
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

    async def store_ready() -> bool:
        return await run_in_threadpool(ping)

    return Wiring(
        settings=settings,
        unit_of_work=unit_of_work,
        work_index=work_index,
        channels=wired_channels,
        quiet_hours=quiet_hours,
        send=SendNotification(unit_of_work, wired_channels, quiet_hours=quiet_hours),
        set_opt_in=SetOptIn(unit_of_work),
        get_preference=GetPreference(unit_of_work),
        store_ready=store_ready,
    )


def build_app(
    settings: NotificationSettings | None = None,
    *,
    channels: Mapping[Channel, NotificationChannel] | None = None,
) -> FastAPI:
    settings = settings or NotificationSettings(service_name=SERVICE_NAME)
    wiring = wire(settings, channels=channels)
    app = create_app(
        service_name=SERVICE_NAME,
        version=__version__,
        routers=[router],
        settings=settings,
        readiness_checks=[("store", wiring.store_ready)],
        problem_status=PROBLEM_STATUS,
    )
    app.state.wiring = wiring
    return app


app = build_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("notification.main:app", host="127.0.0.1", port=8006, reload=True)
