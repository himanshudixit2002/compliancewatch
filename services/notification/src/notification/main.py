"""Composition root for the notification service.

Guide section 11: wiring of interfaces to implementations happens here, never inside the layers.
Stores are in memory until the service's own migration lands; the WhatsApp channel is real only
behind ``CW_WHATSAPP_ENABLED`` with a phone number id and an access token.
"""

from fastapi import FastAPI

from domain_kernel.channels import Channel
from domain_kernel.errors import DomainError
from domain_kernel.protocols import NotificationChannel
from notification import __version__
from notification.api.router import router
from notification.application.preferences import SetOptIn
from notification.application.send import SendNotification
from notification.domain.errors import (
    MissingPlaceholderError,
    UnknownChannelError,
    UnknownTemplateError,
)
from notification.domain.preferences import QuietHours
from notification.infrastructure.memory import LogEventSink, MemoryPreferences, MemorySentLog
from notification.infrastructure.whatsapp import DisabledChannel, WhatsAppCloudChannel
from notification.settings import NotificationSettings
from notification.wiring import Wiring
from py_common.app import create_app

SERVICE_NAME = "notification"
PROBLEM_STATUS: dict[type[DomainError], int] = {
    UnknownTemplateError: 422,
    MissingPlaceholderError: 422,
    UnknownChannelError: 503,
}
WHATSAPP_DISABLED = "whatsapp channel disabled: set CW_WHATSAPP_ENABLED and the Meta credentials"


def wire(settings: NotificationSettings) -> Wiring:
    preferences = MemoryPreferences()
    sent_log = MemorySentLog()
    events = LogEventSink()
    quiet_hours = QuietHours.parse(settings.quiet_hours_start, settings.quiet_hours_end)
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
    channels = {
        Channel.WHATSAPP: whatsapp,
        Channel.EMAIL: DisabledChannel("email channel not wired yet (SES arrives with deploy)"),
    }

    async def store_ready() -> bool:
        return preferences.ping()

    return Wiring(
        settings=settings,
        preferences=preferences,
        sent_log=sent_log,
        events=events,
        channels=channels,
        quiet_hours=quiet_hours,
        send=SendNotification(preferences, sent_log, events, channels, quiet_hours=quiet_hours),
        set_opt_in=SetOptIn(preferences),
        store_ready=store_ready,
    )


def build_app(settings: NotificationSettings | None = None) -> FastAPI:
    settings = settings or NotificationSettings(service_name=SERVICE_NAME)
    wiring = wire(settings)
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
