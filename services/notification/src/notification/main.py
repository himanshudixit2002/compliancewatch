"""The notification service's HTTP app.

``build_app(settings, channels=..., rules=..., email_feedback=...)`` wires the service
(``notification.composition``) and serves its routes; the channels, the rulebook reader and the
SES feedback reader it takes replace the configured ones, which is how the demo and the tests
send and receive through fakes.
"""

from collections.abc import Mapping

from fastapi import FastAPI

from domain_kernel.channels import Channel
from domain_kernel.errors import DomainError
from notification import __version__
from notification.api.notifications import router as notifications_router
from notification.api.receipts import router as receipts_router
from notification.api.recipients import router as recipients_router
from notification.api.router import router
from notification.composition import wire
from notification.domain.channels import ChannelAdapter
from notification.domain.errors import (
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
from notification.domain.ports import EmailFeedbackReader, RuleVersionReader
from notification.settings import NotificationSettings
from py_common.app import create_app

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
}


def build_app(
    settings: NotificationSettings | None = None,
    *,
    channels: Mapping[Channel, ChannelAdapter] | None = None,
    rules: RuleVersionReader | None = None,
    email_feedback: EmailFeedbackReader | None = None,
) -> FastAPI:
    settings = settings or NotificationSettings(service_name=SERVICE_NAME)
    wiring = wire(settings, channels=channels, rules=rules, email_feedback=email_feedback)
    app = create_app(
        service_name=SERVICE_NAME,
        version=__version__,
        routers=[router, recipients_router, notifications_router, receipts_router],
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
