"""Property tests of the notification API against its spec (schemathesis).

Schemathesis generates valid and invalid requests from the served schema, which
``test_openapi.py`` pins to the committed spec, and sends them in process with a tenant header,
the bot token and the email feedback credentials of the test settings, so the receipt routes
get past their checks. The SES feedback reader verifies against ``FakeSns``'s certificate and a
web opt-in asks a ``FakeConsentReader`` (which holds no consent, so it is a 409), so no request
leaves the process.
Each response must not be a server error, and its status code, content type and body must be
the ones the spec documents.

That app runs in header mode. The routes that read a token run again in token mode, with a
service token from a ``TestIssuer`` that holds every scope they take (tenant:act,
notification:preferences, notification:send, notification:receipts and data:export) and the
tenant header.
The SES feedback route reads SNS's basic credentials, not a token, and runs only in header mode.

Only the operations in ``OPERATIONS`` run: those served when these tests arrived. A change that
adds an operation opts it in here. An operation that cannot pass yet, for a defect or because it
needs a redesign, goes in ``EXCLUDED`` with the reason.
"""

import base64
import os
from typing import Any, cast

import schemathesis
from hypothesis import HealthCheck, settings
from schemathesis.checks import CheckFunction, not_a_server_error
from schemathesis.specs.openapi.checks import (
    content_type_conformance,
    response_schema_conformance,
    status_code_conformance,
)

from domain_kernel.access import Scope
from notification.infrastructure.ses_feedback import SnsFeedbackReader
from notification.main import build_app
from notification.testing import (
    BOT_TOKEN,
    EMAIL_FEEDBACK_TOKEN,
    FakeConsentReader,
    FakeObligationReader,
    FakeSns,
    notification_settings,
)
from py_common.auth.testing import TestIssuer, bearer

TENANT_ID = "7d0f4d56-2a8e-4c1b-9f3e-5b6a1c2d3e4f"
OPERATIONS = frozenset(
    {
        "GET /health",
        "GET /ready",
        "GET /v1/notification/ping",
        "GET /v1/notification/preferences/{channel}/{recipient}",
        "PUT /v1/notification/preferences/{channel}/{recipient}",
        "POST /v1/notification/send",
        "GET /v1/notification/templates",
        "GET /v1/notification/recipients",
        "PUT /v1/notification/recipients/{recipient_id}",
        "GET /v1/notification/recipients/{recipient_id}",
        "DELETE /v1/notification/recipients/{recipient_id}",
        "GET /v1/notification/notifications",
        "GET /v1/notification/notifications/{notification_id}",
        "POST /v1/notification/notifications/{notification_id}/resend",
        "POST /v1/notification/receipts/whatsapp",
        "POST /v1/notification/receipts/email",
        "POST /v1/notification/bulk",
        "GET /v1/notification/data-export",
    }
)
TOKEN_OPERATIONS = OPERATIONS - {
    "GET /health",
    "GET /ready",
    "GET /v1/notification/ping",
    "GET /v1/notification/templates",
    "POST /v1/notification/receipts/email",
}
EXCLUDED: dict[str, str] = {}
CHECKS = cast(
    list[CheckFunction],
    [
        not_a_server_error,
        status_code_conformance,
        content_type_conformance,
        response_schema_conformance,
    ],
)
EXAMPLES = 200 if os.environ.get("HYPOTHESIS_PROFILE") == "nightly" else 25

app = build_app(
    notification_settings(
        notification_bot_token=BOT_TOKEN,
        notification_email_feedback_token=EMAIL_FEEDBACK_TOKEN,
        notification_bulk_enabled=True,
    ),
    email_feedback=SnsFeedbackReader(FakeSns().certificates),
    obligations=FakeObligationReader(),
    consents=FakeConsentReader(),
)
HEADERS = {
    "x-tenant-id": TENANT_ID,
    "x-cw-bot-token": BOT_TOKEN,
    "authorization": "Basic "
    + base64.b64encode(f"sns:{EMAIL_FEEDBACK_TOKEN}".encode()).decode("ascii"),
}
schema = schemathesis.openapi.from_asgi("/openapi.json", app).include(
    func=lambda ctx: ctx.operation.label in OPERATIONS and ctx.operation.label not in EXCLUDED
)

ISSUER = TestIssuer()
SERVICE_TOKEN = ISSUER.service(
    "notification-properties",
    [
        Scope.TENANT_ACT,
        Scope.NOTIFICATION_PREFERENCES,
        Scope.NOTIFICATION_SEND,
        Scope.NOTIFICATION_RECEIPTS,
        Scope.DATA_EXPORT,
    ],
)
token_app = build_app(
    notification_settings(**ISSUER.settings_overrides("token")), consents=FakeConsentReader()
)
token_schema = schemathesis.openapi.from_asgi("/openapi.json", token_app).include(
    func=lambda ctx: ctx.operation.label in TOKEN_OPERATIONS
)


def test_every_listed_operation_is_served() -> None:
    paths = app.openapi()["paths"]
    labels = {f"{method.upper()} {path}" for path, item in paths.items() for method in item}
    assert labels >= OPERATIONS | EXCLUDED.keys() | TOKEN_OPERATIONS


@schema.parametrize()
# Bodies with patterns and nested models make schemathesis discard many drafts; that is
# expected, not a slow or broken generator, so those two health checks do not apply.
@settings(
    max_examples=EXAMPLES,
    suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.too_slow],
)
def test_responses_conform_to_the_spec(case: schemathesis.Case[Any]) -> None:
    case.call_and_validate(headers=HEADERS, checks=CHECKS)


@token_schema.parametrize()
@settings(
    max_examples=EXAMPLES,
    suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.too_slow],
)
def test_responses_to_a_service_token_conform_to_the_spec(case: schemathesis.Case[Any]) -> None:
    case.call_and_validate(
        headers={"x-tenant-id": TENANT_ID, **bearer(SERVICE_TOKEN)}, checks=CHECKS
    )
