"""The notification service's HTTP app.

``build_app(settings, channels=..., rules=..., email_feedback=..., obligations=...,
consents=...)`` wires the service (``notification.composition``) and serves its routes; the
channels, the rulebook reader, the SES feedback reader, the obligation reader and the consent
reader it takes replace the configured ones, which is
how the demo and the tests send and receive through fakes. A process that hosts identity next to
this service passes identity's ``authenticator`` and a ``token_source`` of service tokens minted in
the process. With telemetry on, the app also reports the age of the oldest pending work
(``install_pending_metrics``): the API process runs whether or not a worker does, so the gauge
keeps reporting when the dispatcher stops.
"""

from collections.abc import Mapping

from fastapi import FastAPI

from domain_kernel.channels import Channel
from domain_kernel.errors import DomainError
from domain_kernel.events import utc_now
from notification import __version__
from notification.api.bulk import router as bulk_router
from notification.api.notifications import router as notifications_router
from notification.api.receipts import router as receipts_router
from notification.api.recipients import router as recipients_router
from notification.api.router import router
from notification.composition import wire
from notification.domain.channels import ChannelAdapter
from notification.domain.errors import (
    BulkNotificationsDisabledError,
    ConsentAddressNotTheirsError,
    ConsentNotRecordedError,
    ConsentSubjectRequiredError,
    DependencyUnavailableError,
    EmailFeedbackInvalidError,
    EmailFeedbackUnauthorizedError,
    InvalidAddressError,
    MissingPlaceholderError,
    NotificationNotFoundError,
    ReceiptsDisabledError,
    ReceiptTokenInvalidError,
    RecipientNotFoundError,
    ResendNotAllowedError,
    TenantRequiredError,
    UnknownChannelError,
    UnknownTemplateError,
)
from notification.domain.ports import (
    ConsentReader,
    EmailFeedbackReader,
    ObligationReader,
    RuleVersionReader,
)
from notification.infrastructure.metrics import register_pending_age_gauge
from notification.settings import NotificationSettings
from notification.wiring import Wiring
from py_common.app import create_app, module_app
from py_common.auth import TokenSource
from py_common.auth.fastapi import Authenticator
from py_common.telemetry import Telemetry

SERVICE_NAME = "notification"
PROBLEM_STATUS: dict[type[DomainError], int] = {
    TenantRequiredError: 401,
    UnknownTemplateError: 422,
    MissingPlaceholderError: 422,
    InvalidAddressError: 422,
    RecipientNotFoundError: 404,
    UnknownChannelError: 503,
    DependencyUnavailableError: 503,
    NotificationNotFoundError: 404,
    ResendNotAllowedError: 409,
    ReceiptsDisabledError: 503,
    ReceiptTokenInvalidError: 401,
    EmailFeedbackInvalidError: 422,
    EmailFeedbackUnauthorizedError: 401,
    BulkNotificationsDisabledError: 503,
    ConsentNotRecordedError: 409,
    ConsentAddressNotTheirsError: 409,
    ConsentSubjectRequiredError: 422,
}


def install_pending_metrics(app: FastAPI, wiring: Wiring) -> bool:
    """Register the pending-work age gauge when telemetry is on; whether it did."""
    telemetry: Telemetry = app.state.telemetry
    if not telemetry.enabled or telemetry.meter_provider is None:
        return False
    register_pending_age_gauge(
        wiring.work_index.oldest_due,
        utc_now,
        telemetry.meter_provider.get_meter(SERVICE_NAME, __version__),
    )
    return True


def build_app(
    settings: NotificationSettings | None = None,
    *,
    channels: Mapping[Channel, ChannelAdapter] | None = None,
    rules: RuleVersionReader | None = None,
    email_feedback: EmailFeedbackReader | None = None,
    obligations: ObligationReader | None = None,
    consents: ConsentReader | None = None,
    authenticator: Authenticator | None = None,
    token_source: TokenSource | None = None,
) -> FastAPI:
    settings = settings or NotificationSettings(service_name=SERVICE_NAME)
    wiring = wire(
        settings,
        channels=channels,
        rules=rules,
        email_feedback=email_feedback,
        obligations=obligations,
        consents=consents,
        token_source=token_source,
    )
    app = create_app(
        service_name=SERVICE_NAME,
        version=__version__,
        routers=[router, recipients_router, notifications_router, receipts_router, bulk_router],
        settings=settings,
        readiness_checks=[("store", wiring.store_ready)],
        problem_status=PROBLEM_STATUS,
        authenticator=authenticator,
    )
    app.state.wiring = wiring
    install_pending_metrics(app, wiring)
    return app


def __getattr__(name: str) -> FastAPI:
    """``app`` is built on first access, so importing this module builds nothing."""
    return module_app(name, build_app)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("notification.main:app", host="127.0.0.1", port=8006, reload=True)
