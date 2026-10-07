"""``HttpConsentReader`` against a mock identity service: a granted purpose, a withdrawn or never
recorded one, the tenant header and the service token it carries, and every answer it cannot use
as ``DependencyUnavailableError``."""

from typing import Any

import httpx2
import pytest

from domain_kernel.ids import TenantId
from notification.domain.errors import DependencyUnavailableError
from notification.infrastructure.identity_client import HttpConsentReader
from py_common.auth import BearerAuth, ServiceTokenUnavailableError

TENANT = TenantId.new()
SUBJECT = "4f6c0f9e-2b7a-4d4e-8b1d-0c9a5e3f2a10"


def state(purpose: str, granted: bool) -> dict[str, Any]:
    return {
        "purpose": purpose,
        "granted": granted,
        "notice_version": "2000-01",
        "since": "2000-01-03T06:30:00Z",
        "source": "web_onboarding",
    }


SUMMARY: dict[str, Any] = {
    "subject": SUBJECT,
    "states": [state("whatsapp_reminders", True), state("email_reminders", False)],
    "history": [],
}


def reader(handler: Any, *, auth: httpx2.Auth | None = None) -> HttpConsentReader:
    client = httpx2.Client(base_url="http://identity", transport=httpx2.MockTransport(handler))
    return HttpConsentReader(client=client, auth=auth)


def test_reads_the_state_of_the_purpose_for_the_tenant_and_subject() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=SUMMARY)

    consents = reader(handler)
    assert consents.granted(TENANT, SUBJECT, "whatsapp_reminders") is True
    assert consents.granted(TENANT, SUBJECT, "email_reminders") is False, "withdrawn"
    assert consents.granted(TENANT, SUBJECT, "analytics") is False, "never recorded"
    request = seen[0]
    assert request.url.path == "/v1/identity/consents"
    assert request.url.params["subject"] == SUBJECT
    assert request.headers["x-tenant-id"] == str(TENANT)
    assert "authorization" not in request.headers
    consents.close()


class StaticTokens:
    """A ``TokenSource`` with one token, or none to give when ``fail``."""

    client_id = "notification"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def token(self) -> str:
        if self.fail:
            raise ServiceTokenUnavailableError("identity refused the client (test)")
        return "service-token"

    def invalidate(self, token: str) -> None:
        return None


def test_carries_the_service_token_and_an_unavailable_one_is_unavailable() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=SUMMARY)

    assert reader(handler, auth=BearerAuth(StaticTokens())).granted(
        TENANT, SUBJECT, "whatsapp_reminders"
    )
    assert seen[0].headers["authorization"] == "Bearer service-token"
    failing = reader(handler, auth=BearerAuth(StaticTokens(fail=True)))
    with pytest.raises(DependencyUnavailableError, match="no service token"):
        failing.granted(TENANT, SUBJECT, "whatsapp_reminders")


@pytest.mark.parametrize(
    "response",
    [
        httpx2.Response(404, json={"type": "not-found"}),
        httpx2.Response(500, text="boom"),
        httpx2.Response(403, json={"type": "auth-forbidden"}),
        httpx2.Response(200, text="not json"),
        httpx2.Response(200, json={"subject": SUBJECT}),
        httpx2.Response(200, json={"states": [{"purpose": "whatsapp_reminders"}]}),
        httpx2.Response(
            200, json={"states": [{"purpose": "whatsapp_reminders", "granted": "yes"}]}
        ),
        httpx2.Response(200, json=[]),
    ],
)
def test_an_answer_it_cannot_use_is_unavailable(response: httpx2.Response) -> None:
    with pytest.raises(DependencyUnavailableError):
        reader(lambda _: response).granted(TENANT, SUBJECT, "whatsapp_reminders")


def test_an_unreachable_identity_is_unavailable() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    with pytest.raises(DependencyUnavailableError, match="unreachable"):
        reader(handler).granted(TENANT, SUBJECT, "whatsapp_reminders")
