"""A web opt-in needs identity's consent: ``PUT /v1/notification/preferences/{channel}/{recipient}``
with ``opted_in`` and source web_onboarding or web_settings asks identity (a
``FakeConsentReader`` here) whether the subject's consent for the channel's purpose is granted in
the request's tenant, and whether the address is the subject's own where identity knows their
contact, and records nothing when either fails. Opt-outs and the other sources never ask. A
change given on the web keeps the tenant it was given for."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from domain_kernel.access import ANONYMOUS, Principal, Role, Scope
from domain_kernel.channels import Channel
from domain_kernel.ids import TenantId, UserId
from notification.api.deps import OptInCaller
from notification.application.preferences import SetOptIn, SetPreference
from notification.domain.errors import (
    ConsentAddressNotTheirsError,
    ConsentNotRecordedError,
    ConsentSubjectRequiredError,
    DependencyUnavailableError,
    TenantRequiredError,
)
from notification.domain.preferences import ConsentSource
from notification.infrastructure.memory import MemoryStore
from notification.main import build_app
from notification.testing import NOON_IST, FakeConsentReader, notification_settings
from py_common.auth.errors import AuthTokenRequiredError
from py_common.auth.testing import TestIssuer, bearer

TENANT = TenantId.new()
OTHER = TenantId.new()
SUBJECT = str(UserId.new())
PHONE = "+919876543210"
MAIL = "owner@example.com"
WA_PATH = f"/v1/notification/preferences/whatsapp/{PHONE}"
MAIL_PATH = f"/v1/notification/preferences/email/{MAIL}"
AS_TENANT = {"x-tenant-id": str(TENANT)}
WHATSAPP = "whatsapp_reminders"
ISSUER = TestIssuer()


def problem(response: Any) -> str:
    kind: str = response.json()["type"]
    return kind.rsplit(":", 1)[-1]


def web_opt_in(source: str = "web_onboarding", **changes: object) -> dict[str, object]:
    return {"opted_in": True, "source": source, "subject": SUBJECT, **changes}


@pytest.fixture
def consents() -> FakeConsentReader:
    return FakeConsentReader()


@pytest.fixture
def client(consents: FakeConsentReader) -> Iterator[TestClient]:
    with TestClient(build_app(notification_settings(), consents=consents)) as test_client:
        yield test_client


@pytest.mark.parametrize("source", ["web_onboarding", "web_settings"])
def test_a_web_opt_in_covered_by_a_granted_consent_is_recorded(
    client: TestClient, consents: FakeConsentReader, source: str
) -> None:
    consents.grant(TENANT, SUBJECT, WHATSAPP)
    consents.grant(TENANT, SUBJECT, "email_reminders")
    put = client.put(WA_PATH, json=web_opt_in(source, language="hi"), headers=AS_TENANT)
    assert put.status_code == 200, put.text
    assert (put.json()["opted_in"], put.json()["source"]) == (True, source)
    mail = client.put(MAIL_PATH, json=web_opt_in(source), headers=AS_TENANT)
    assert mail.status_code == 200, mail.text
    assert consents.asked == [
        (TENANT, SUBJECT, WHATSAPP),
        (TENANT, SUBJECT, "email_reminders"),
    ]
    assert client.get(WA_PATH).json()["language"] == "hi"


def test_a_web_opt_in_without_a_granted_consent_is_a_409_and_records_nothing(
    client: TestClient, consents: FakeConsentReader
) -> None:
    consents.grant(TENANT, SUBJECT, "email_reminders")
    consents.grant(OTHER, SUBJECT, WHATSAPP)
    consents.grant(TENANT, "someone-else", WHATSAPP)
    refused = client.put(WA_PATH, json=web_opt_in(), headers=AS_TENANT)
    assert (refused.status_code, problem(refused)) == (409, "notification-consent-not-recorded")
    assert WHATSAPP in refused.json()["detail"]
    assert "9876543210" not in refused.json()["detail"] + refused.json()["title"]
    assert client.get(WA_PATH).status_code == 404, "nothing was recorded"


def test_a_withdrawn_consent_leaves_an_earlier_opt_out_in_place(
    client: TestClient, consents: FakeConsentReader
) -> None:
    out = client.put(WA_PATH, json={"opted_in": False, "source": "web_settings"})
    assert out.status_code == 200, out.text
    consents.grant(TENANT, SUBJECT, WHATSAPP)
    consents.withdraw(TENANT, SUBJECT, WHATSAPP)
    refused = client.put(WA_PATH, json=web_opt_in("web_settings"), headers=AS_TENANT)
    assert refused.status_code == 409
    assert client.get(WA_PATH).json()["opted_in"] is False


def test_an_opt_out_and_the_other_sources_never_ask_identity(
    client: TestClient, consents: FakeConsentReader
) -> None:
    for source in ("web_onboarding", "web_settings"):
        out = client.put(WA_PATH, json={"opted_in": False, "source": source})
        assert out.status_code == 200, out.text
    for source in ("whatsapp_keyword", "api", "support"):
        put = client.put(WA_PATH, json={"opted_in": True, "source": source})
        assert put.status_code == 200, put.text
        assert put.json()["source"] == source
        named = client.put(WA_PATH, json={"opted_in": True, "source": source, "subject": "x"})
        assert named.status_code == 200, "a subject is ignored outside a web opt-in"
    assert consents.asked == []


def test_identity_down_is_a_503_and_records_nothing(
    client: TestClient, consents: FakeConsentReader
) -> None:
    consents.grant(TENANT, SUBJECT, WHATSAPP)
    consents.down = True
    down = client.put(WA_PATH, json=web_opt_in(), headers=AS_TENANT)
    assert (down.status_code, problem(down)) == (503, "notification-dependency-unavailable")
    assert client.get(WA_PATH).status_code == 404


def test_a_web_opt_in_needs_a_tenant_and_a_subject(
    client: TestClient, consents: FakeConsentReader
) -> None:
    consents.grant(TENANT, SUBJECT, WHATSAPP)
    no_tenant = client.put(WA_PATH, json=web_opt_in())
    assert (no_tenant.status_code, problem(no_tenant)) == (401, "notification-tenant-required")
    no_subject = client.put(WA_PATH, json={"opted_in": True, "source": "web_onboarding"})
    assert no_subject.status_code == 401, "the tenant is checked first"
    no_subject = client.put(
        WA_PATH, json={"opted_in": True, "source": "web_onboarding"}, headers=AS_TENANT
    )
    assert (no_subject.status_code, problem(no_subject)) == (
        422,
        "notification-consent-subject-required",
    )
    empty = client.put(WA_PATH, json=web_opt_in(subject=""), headers=AS_TENANT)
    assert empty.status_code == 422, "a subject has at least one character"
    long = client.put(WA_PATH, json=web_opt_in(subject="s" * 255), headers=AS_TENANT)
    assert long.status_code == 422
    assert consents.asked == []
    assert client.get(WA_PATH).status_code == 404


def test_an_invalid_address_is_refused_before_identity_is_asked(
    client: TestClient, consents: FakeConsentReader
) -> None:
    refused = client.put(
        "/v1/notification/preferences/whatsapp/call-me", json=web_opt_in(), headers=AS_TENANT
    )
    assert (refused.status_code, problem(refused)) == (422, "notification-address-invalid")
    assert consents.asked == []


def test_a_service_token_names_the_tenant_with_tenant_act(consents: FakeConsentReader) -> None:
    settings = notification_settings(**ISSUER.settings_overrides("token"))
    web = bearer(
        ISSUER.service("web", [Scope.NOTIFICATION_PREFERENCES, Scope.TENANT_ACT]),
    )
    without_tenant_act = bearer(ISSUER.service("web", [Scope.NOTIFICATION_PREFERENCES]))
    consents.grant(TENANT, SUBJECT, WHATSAPP)
    with TestClient(build_app(settings, consents=consents)) as client:
        put = client.put(WA_PATH, json=web_opt_in(), headers={**web, **AS_TENANT})
        assert put.status_code == 200, put.text
        refused = client.put(
            WA_PATH, json=web_opt_in(), headers={**without_tenant_act, **AS_TENANT}
        )
        assert (refused.status_code, problem(refused)) == (403, "auth-forbidden")
        unnamed = client.put(WA_PATH, json=web_opt_in(), headers=web)
        assert (unnamed.status_code, problem(unnamed)) == (401, "notification-tenant-required")
        keyword = client.put(
            WA_PATH,
            json={"opted_in": True, "source": "whatsapp_keyword"},
            headers={**without_tenant_act, **AS_TENANT},
        )
        assert keyword.status_code == 200, "only a web opt-in reads the tenant"
        user = client.put(
            WA_PATH, json=web_opt_in(), headers=bearer(ISSUER.user(TENANT, [Role.OWNER]))
        )
        assert (user.status_code, problem(user)) == (403, "auth-forbidden"), (
            "users still never change preferences directly"
        )
    assert consents.asked == [(TENANT, SUBJECT, WHATSAPP)]


def test_an_address_identity_knows_is_not_the_subject_s_is_a_409(
    client: TestClient, consents: FakeConsentReader
) -> None:
    consents.grant(TENANT, SUBJECT, WHATSAPP)
    consents.contacts[(TENANT, SUBJECT, Channel.WHATSAPP)] = "+919812345678"
    refused = client.put(WA_PATH, json=web_opt_in(), headers=AS_TENANT)
    assert (refused.status_code, problem(refused)) == (
        409,
        "notification-consent-address-not-theirs",
    )
    assert "98" not in refused.json()["detail"], "neither address is named"
    assert client.get(WA_PATH).status_code == 404, "nothing was recorded"
    consents.contacts[(TENANT, SUBJECT, Channel.WHATSAPP)] = PHONE
    assert client.put(WA_PATH, json=web_opt_in(), headers=AS_TENANT).status_code == 200
    unknown = client.put(MAIL_PATH, json=web_opt_in(), headers=AS_TENANT)
    assert unknown.status_code == 409, "no email consent yet"
    consents.grant(TENANT, SUBJECT, "email_reminders")
    known_nowhere = client.put(MAIL_PATH, json=web_opt_in(), headers=AS_TENANT)
    assert known_nowhere.status_code == 200, "identity knows no email for the subject"


def test_a_web_change_keeps_the_tenant_it_was_given_for(
    client: TestClient, consents: FakeConsentReader
) -> None:
    consents.grant(TENANT, SUBJECT, WHATSAPP)
    store = client.app.state.wiring.unit_of_work  # type: ignore[attr-defined]
    assert isinstance(store, MemoryStore)

    def kept() -> TenantId | None:
        with store.shared() as unit:
            found = unit.preferences.get(Channel.WHATSAPP, PHONE)
        assert found is not None
        return found.set_for_tenant

    assert client.put(WA_PATH, json=web_opt_in(), headers=AS_TENANT).status_code == 200
    assert kept() == TENANT
    other = {"opted_in": False, "source": "web_settings"}
    assert client.put(WA_PATH, json=other, headers={"x-tenant-id": str(OTHER)}).status_code == 200
    assert kept() == OTHER, "the last web change names its own tenant"
    keyword = {"opted_in": True, "source": "whatsapp_keyword"}
    assert client.put(WA_PATH, json=keyword, headers=AS_TENANT).status_code == 200
    assert kept() is None, "a keyword belongs to no tenant, whatever header came with it"


def test_the_caller_names_the_tenant_and_a_service_source_needs_a_token() -> None:
    service = OptInCaller(Principal.service("web", [Scope.TENANT_ACT]), TENANT)
    assert service.tenant() == TENANT
    service.require_service("api")
    OptInCaller(ANONYMOUS, TENANT, header_mode=True).require_service("api")
    with pytest.raises(AuthTokenRequiredError):
        OptInCaller(ANONYMOUS, TENANT).require_service("support")


def test_the_use_case_checks_before_it_saves() -> None:
    store = MemoryStore()
    consents = FakeConsentReader()
    use_case = SetPreference(SetOptIn(store, clock=lambda: NOON_IST), consents)

    def opt_in(**changes: Any) -> None:
        values: dict[str, Any] = {
            "opted_in": True,
            "source": ConsentSource.WEB_ONBOARDING,
            "tenant_id": TENANT,
            "subject": SUBJECT,
            **changes,
        }
        use_case.run(Channel.EMAIL, MAIL, **values)

    with pytest.raises(TenantRequiredError):
        opt_in(tenant_id=None)
    with pytest.raises(ConsentSubjectRequiredError):
        opt_in(subject=None)
    with pytest.raises(ConsentNotRecordedError):
        opt_in()
    consents.grant(TENANT, SUBJECT, "email_reminders")
    consents.contacts[(TENANT, SUBJECT, Channel.EMAIL)] = "someone.else@example.com"
    with pytest.raises(ConsentAddressNotTheirsError):
        opt_in()
    del consents.contacts[(TENANT, SUBJECT, Channel.EMAIL)]
    consents.withdraw(TENANT, SUBJECT, "email_reminders")
    consents.down = True
    with pytest.raises(DependencyUnavailableError):
        opt_in()
    with store.shared() as unit:
        assert unit.preferences.get(Channel.EMAIL, MAIL) is None
    consents.down = False
    consents.grant(TENANT, SUBJECT, "email_reminders")
    opt_in()
    with store.shared() as unit:
        saved = unit.preferences.get(Channel.EMAIL, MAIL)
    assert saved is not None
    assert saved.opted_in
    use_case.run(Channel.EMAIL, MAIL, opted_in=False, source=ConsentSource.WEB_SETTINGS)
    assert saved.set_for_tenant == TENANT
    assert len(consents.asked) == 4, "the opt-out asked nothing"
