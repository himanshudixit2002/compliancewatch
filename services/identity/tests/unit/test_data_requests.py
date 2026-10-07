"""A tenant's data requests: the request and its deadline, the use cases on the memory store,
the export bundle with sources that answer and fail, the routes in header and token mode, the
HTTP export source, the gauges and the sources setting."""

import json
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx2
import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient
from opentelemetry.metrics import CallbackOptions

from domain_kernel.access import Principal, Role, Scope
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import TenantId
from identity.application.bootstrap import BootstrapInternalTenant
from identity.application.consents import RecordConsent
from identity.application.data_requests import (
    ExportTenantData,
    ListDataRequests,
    ReadDataRequest,
    RequestExport,
)
from identity.application.sessions import user_principal
from identity.application.tenancy import CreateTenant
from identity.domain.billing import StoredBillingEvent
from identity.domain.consent import ConsentPurpose, ConsentSource
from identity.domain.data_requests import (
    DEADLINE,
    DataRequest,
    DataRequestKind,
    DataRequestSource,
    DataRequestStatus,
    OpenRequests,
    SourceSection,
    parse_export_sources,
)
from identity.domain.errors import (
    DataRequestKindUnavailableError,
    DataRequestNotFoundError,
    SessionRevokedError,
    TenantNotFoundError,
)
from identity.domain.provider import AAL2
from identity.domain.tenancy import Contact, TenantKind, User
from identity.infrastructure.data_request_metrics import DataRequestGauges
from identity.infrastructure.export_sources import HttpExportSource
from identity.infrastructure.memory import MemoryDataRequestDirectory, MemoryStore
from identity.infrastructure.minter import IssuerMinter
from identity.infrastructure.providers.fake import FakeIdentityProvider
from identity.main import build_app, export_sources
from identity.settings import DEFAULT_EXPORT_SOURCES
from identity.testing import identity_settings
from py_common.auth import TokenIssuer
from py_common.auth.errors import AuthForbiddenError
from py_common.auth.testing import TestIssuer, bearer

NOW = datetime(2000, 6, 1, 9, 0, tzinfo=UTC)
OWNER_PHONE = "+919876543210"
STAFF_PHONE = "+919812345678"
OTHER_PHONE = "+919800000001"
ADMIN_EMAIL = "admin@example.org"
REQUESTS = "/v1/identity/data-requests"


def request_at(at: datetime = NOW, **changes: Any) -> DataRequest:
    values: dict[str, Any] = {
        "requested_by": "",
        "reason": "Example reason",
        "at": at,
    }
    values.update(changes)
    kind = values.pop("kind", DataRequestKind.EXPORT)
    return DataRequest.new(TenantId.new(), kind, DataRequestSource.SELF_SERVICE, **values)


# ---------------------------------------------------------------- the request


def test_an_unanswered_request_is_due_thirty_days_later_and_overdue_after_that() -> None:
    request = request_at(kind=DataRequestKind.DELETION)
    assert request.deadline_at - request.requested_at == DEADLINE == timedelta(days=30)
    assert request.status is DataRequestStatus.RECEIVED, "nothing answers a deletion yet"
    assert not request.is_overdue(request.deadline_at)
    late = request.deadline_at + timedelta(seconds=1)
    assert request.is_overdue(late)
    assert request.is_open(late), "an overdue request stays open until it is answered"
    done = request.record_answers(["identity"], ["identity"], NOW)
    assert not done.is_overdue(NOW + timedelta(days=90))


def test_an_export_is_offered_at_once_and_expires_quietly_when_never_completed() -> None:
    request = request_at()
    assert request.status is DataRequestStatus.IN_PROGRESS, "the bundle can be downloaded now"
    late = request.deadline_at + timedelta(seconds=1)
    assert request.is_open(request.deadline_at)
    assert not request.is_overdue(late), "the tenant did not download it: nothing to page"
    assert request.is_expired(late)
    assert not request.is_open(late)
    partly = request.record_answers(["identity"], ["identity", "profile"], NOW)
    assert not partly.is_overdue(late)
    assert partly.is_expired(late)
    done = request.record_answers(["identity", "profile"], ["identity", "profile"], late)
    assert done.is_completed
    assert not done.is_expired(late + timedelta(days=1))


def test_answers_accumulate_until_every_service_has_answered() -> None:
    expected = ["identity", "notification", "profile"]
    first = request_at().record_answers(["identity", "profile"], expected, NOW)
    assert (first.status, first.services_done) == (
        DataRequestStatus.IN_PROGRESS,
        ("identity", "profile"),
    )
    assert first.pending(expected) == ("notification",)
    later = NOW + timedelta(hours=1)
    second = first.record_answers(["identity", "notification"], expected, later)
    assert (second.status, second.completed_at) == (DataRequestStatus.COMPLETED, later)
    assert second.services_done == ("identity", "notification", "profile")
    assert second.pending(expected) == ()
    assert second.record_answers([], expected, later + timedelta(hours=1)) == second


@pytest.mark.parametrize(
    "changes",
    [
        {"reason": "x" * 501},
        {"requested_by": "u" * 161},
    ],
)
def test_a_request_refuses_what_its_table_refuses(changes: dict[str, Any]) -> None:
    with pytest.raises(InvariantViolationError):
        request_at(**changes)


def test_a_support_request_says_why() -> None:
    with pytest.raises(InvariantViolationError, match="reason"):
        DataRequest.new(
            TenantId.new(),
            DataRequestKind.EXPORT,
            DataRequestSource.SUPPORT,
            requested_by="",
            reason="  ",
            at=NOW,
        )


# ---------------------------------------------------------------- the use cases


class FakeSource:
    def __init__(self, service: str, *, fails: bool = False) -> None:
        self._service = service
        self.fails = fails
        self.asked: list[TenantId] = []

    @property
    def service(self) -> str:
        return self._service

    def export(self, tenant_id: TenantId) -> SourceSection:
        self.asked.append(tenant_id)
        if self.fails:
            return SourceSection(self._service, None, "answered 503")
        return SourceSection(
            self._service,
            {
                "service": self._service,
                "tenant_id": str(tenant_id),
                "generated_at": NOW.isoformat(),
                "sections": {"things": [{"id": "1"}]},
            },
        )


class Setup:
    """A business and a CA firm signed up on one memory store, the internal tenant with its
    admin, and the use cases."""

    def __init__(self) -> None:
        self.store = MemoryStore()
        self.provider = FakeIdentityProvider()
        issuer = TestIssuer()
        minter = IssuerMinter(
            TokenIssuer(issuer.keys, issuer=issuer.issuer_name, audience=issuer.audience)
        )
        create = CreateTenant(
            self.store, self.provider, minter, ttl=timedelta(minutes=10), clock=lambda: NOW
        )
        business = create.run(
            self.provider.issue(phone=OWNER_PHONE), TenantKind.BUSINESS, "Example Traders"
        )
        firm = create.run(
            self.provider.issue(phone=OTHER_PHONE, aal=AAL2),
            TenantKind.CA_FIRM,
            "Example Associates",
        )
        self.tenant, self.owner = business.tenant.id, business.session.principal
        self.firm, self.firm_admin = firm.tenant.id, firm.session.principal
        internal, admin = BootstrapInternalTenant(self.store, self.provider, clock=lambda: NOW).run(
            "Example Regulatory", Contact(email=ADMIN_EMAIL)
        )
        self.internal = internal.id
        self.admin = user_principal(admin, mfa=True)
        self.profile = FakeSource("profile")
        self.notification = FakeSource("notification", fails=True)
        self.request = RequestExport(self.store, clock=lambda: NOW)
        self.list = ListDataRequests(self.store)
        self.read = ReadDataRequest(self.store)
        self.export = ExportTenantData(
            self.store, [self.profile, self.notification], clock=lambda: NOW
        )
        RecordConsent(self.store, clock=lambda: NOW).run(
            self.tenant,
            str(self.owner.user_id),
            ConsentPurpose.WHATSAPP_REMINDERS,
            granted=True,
            source=ConsentSource.WEB_ONBOARDING,
            notice_version="2000-01",
        )

    def staff(self) -> Principal:
        owner = self.store.users[self.owner.user_id] if self.owner.user_id else None
        assert owner is not None
        user = User(
            id=type(owner.id).new(),
            tenant_id=self.tenant,
            provider="fake",
            provider_subject="staff-subject",
            contact=Contact(phone=STAFF_PHONE),
            roles=frozenset({Role.STAFF}),
            created_at=NOW,
            updated_at=NOW,
        )
        with self.store(self.tenant) as uow:
            uow.users.add(user)
        return user_principal(user, mfa=False)


@pytest.fixture
def setup() -> Setup:
    return Setup()


def test_an_owner_requests_an_export_and_the_trail_records_it(setup: Setup) -> None:
    made = setup.request.run(setup.owner, setup.tenant, DataRequestKind.EXPORT, reason="  copy ")
    assert (made.source, made.reason, made.requested_by) == (
        DataRequestSource.SELF_SERVICE,
        "copy",
        f"user:{setup.owner.user_id}",
    )
    assert made.deadline_at == NOW + DEADLINE
    assert setup.list.run(setup.owner, setup.tenant) == [made]
    assert setup.read.run(setup.owner, setup.tenant, made.id) == made
    (entry,) = [e for e in setup.store.audit if e.action == "data_request.created"]
    assert (entry.tenant_id, entry.subject_id, entry.reason) == (setup.tenant, str(made.id), "copy")
    assert entry.after is not None
    assert entry.after["kind"] == "export"


def test_a_deletion_request_waits_for_the_erasure_cascade(setup: Setup) -> None:
    with pytest.raises(DataRequestKindUnavailableError):
        setup.request.run(setup.owner, setup.tenant, DataRequestKind.DELETION)
    assert setup.store.data_requests == {}


def test_only_the_tenant_s_owner_or_ca_admin_makes_or_reads_requests(setup: Setup) -> None:
    staff = setup.staff()
    with pytest.raises(AuthForbiddenError):
        setup.request.run(staff, setup.tenant, DataRequestKind.EXPORT)
    made = setup.request.run(setup.firm_admin, setup.firm, DataRequestKind.EXPORT)
    assert made.tenant_id == setup.firm
    with pytest.raises(AuthForbiddenError):
        setup.list.run(staff, setup.tenant)
    with pytest.raises(DataRequestNotFoundError):
        setup.read.run(setup.owner, setup.tenant, made.id)
    with pytest.raises(SessionRevokedError):
        setup.list.run(setup.owner, setup.firm)


def test_the_admin_records_a_support_request_for_a_tenant(setup: Setup) -> None:
    made = setup.request.run(
        setup.admin,
        setup.internal,
        DataRequestKind.EXPORT,
        reason="Asked by email",
        for_tenant=setup.tenant,
    )
    assert (made.tenant_id, made.source) == (setup.tenant, DataRequestSource.SUPPORT)
    assert setup.list.run(setup.owner, setup.tenant) == [made]
    with pytest.raises(InvariantViolationError):
        setup.request.run(
            setup.admin, setup.internal, DataRequestKind.EXPORT, for_tenant=setup.tenant
        )
    with pytest.raises(TenantNotFoundError):
        setup.request.run(
            setup.admin,
            setup.internal,
            DataRequestKind.EXPORT,
            reason="Asked by email",
            for_tenant=TenantId.new(),
        )
    with pytest.raises(AuthForbiddenError):
        setup.request.run(
            setup.owner, setup.tenant, DataRequestKind.EXPORT, reason="x", for_tenant=setup.firm
        )


def test_the_export_holds_every_section_and_a_failed_source_stays_pending(setup: Setup) -> None:
    made = setup.request.run(setup.owner, setup.tenant, DataRequestKind.EXPORT)
    bundle = setup.export.run(setup.owner, setup.tenant, made.id)
    document = json.loads(json.dumps(bundle.document()))
    assert document["tenant_id"] == str(setup.tenant)
    assert (document["complete"], document["services_pending"]) == (False, ["notification"])
    assert set(document["services"]) == {"identity", "profile", "notification"}
    assert document["services"]["notification"] == {
        "service": "notification",
        "status": "unavailable",
        "error": "answered 503",
    }
    identity = document["services"]["identity"]
    assert identity["generated_at"] == NOW.isoformat()
    sections = identity["sections"]
    assert set(sections) == {
        "tenant",
        "users",
        "consents",
        "billing_customer",
        "billing_subscriptions",
        "billing_events",
        "data_requests",
    }
    assert sections["tenant"][0]["name"] == "Example Traders"
    assert [user["phone"] for user in sections["users"]] == [OWNER_PHONE]
    assert "session_version" not in sections["users"][0]
    assert [c["purpose"] for c in sections["consents"]] == ["whatsapp_reminders"]
    assert sections["data_requests"][0]["id"] == str(made.id)
    text = json.dumps(document)
    assert str(setup.firm) not in text
    assert str(setup.internal) not in text
    assert setup.profile.asked == [setup.tenant]

    stored = setup.read.run(setup.owner, setup.tenant, made.id)
    assert stored.status is DataRequestStatus.IN_PROGRESS
    assert stored.services_done == ("identity", "profile")
    assert stored.pending(setup.export.services) == ("notification",)
    setup.notification.fails = False
    again = setup.export.run(setup.owner, setup.tenant, made.id)
    assert again.request.status is DataRequestStatus.COMPLETED
    assert again.document()["complete"] is True
    entries = [e for e in setup.store.audit if e.action == "data_request.exported"]
    assert [e.after["status"] for e in entries if e.after] == ["in_progress", "completed"]
    assert entries[0].after is not None
    assert entries[0].after["services_failed"] == ("notification",)


def test_a_support_request_does_not_show_the_admin_in_the_export(setup: Setup) -> None:
    made = setup.request.run(
        setup.admin, setup.internal, DataRequestKind.EXPORT, reason="Asked", for_tenant=setup.tenant
    )
    document = setup.export.run(setup.owner, setup.tenant, made.id).document()
    (row,) = document["services"]["identity"]["sections"]["data_requests"]
    assert row["requested_by"] == "support"
    assert str(setup.admin.user_id) not in json.dumps(document)


def test_the_bundle_streams_as_the_same_document(setup: Setup) -> None:
    made = setup.request.run(setup.owner, setup.tenant, DataRequestKind.EXPORT)
    bundle = setup.export.run(setup.owner, setup.tenant, made.id)
    streamed = b"".join(bundle.chunks())
    assert json.loads(streamed) == json.loads(json.dumps(bundle.document()))


def test_identity_s_own_data_is_read_a_page_at_a_time(setup: Setup) -> None:
    for _ in range(3):
        RecordConsent(setup.store, clock=lambda: NOW).run(
            setup.tenant,
            str(setup.owner.user_id),
            ConsentPurpose.EMAIL_REMINDERS,
            granted=True,
            source=ConsentSource.WEB_SETTINGS,
            notice_version="2000-01",
        )
    setup.staff()
    made = [setup.request.run(setup.owner, setup.tenant, DataRequestKind.EXPORT) for _ in range(3)]
    whole = ExportTenantData(setup.store, clock=lambda: NOW)
    paged = ExportTenantData(setup.store, clock=lambda: NOW, page_size=1)
    expected = whole.run(setup.owner, setup.tenant, made[0].id).document()
    sections = paged.run(setup.owner, setup.tenant, made[0].id).document()["services"]
    found = sections["identity"]["sections"]
    assert len(found["consents"]) == 4
    assert len(found["users"]) == 2
    assert [row["id"] for row in found["data_requests"]] == sorted(str(r.id) for r in made)
    whole_sections = expected["services"]["identity"]["sections"]
    for name in ("tenant", "users", "consents", "billing_events"):
        assert found[name] == whole_sections[name], name


class SlowSource(FakeSource):
    def __init__(self, service: str, wait: threading.Event) -> None:
        super().__init__(service)
        self._wait = wait

    def export(self, tenant_id: TenantId) -> SourceSection:
        self._wait.wait(5)
        return super().export(tenant_id)


def test_the_sources_are_asked_together_and_a_late_one_is_pending(setup: Setup) -> None:
    released = threading.Event()
    slow = SlowSource("obligation", released)
    export = ExportTenantData(
        setup.store,
        [setup.profile, slow, FakeSource("notification")],
        clock=lambda: NOW,
        concurrency=2,
        deadline_seconds=0.2,
    )
    made = setup.request.run(setup.owner, setup.tenant, DataRequestKind.EXPORT)
    try:
        bundle = export.run(setup.owner, setup.tenant, made.id)
    finally:
        released.set()
    document = bundle.document()
    assert document["services_pending"] == ["obligation"]
    assert document["services"]["obligation"]["error"] == "no answer within the export's 0.2 s"
    assert document["services"]["notification"]["sections"] == {"things": [{"id": "1"}]}
    assert bundle.request.services_done == ("identity", "notification", "profile")


def test_the_platform_s_payment_account_stays_out_of_the_billing_events(setup: Setup) -> None:
    event = StoredBillingEvent(
        id=uuid4(),
        tenant_id=setup.tenant,
        provider_subscription_id="sub_example",
        kind="subscription.activated",
        status=None,
        occurred_at=NOW,
        received_at=NOW,
        body_sha256="0" * 64,
        raw_event={"account_id": "acc_example", "event": "subscription.activated"},
    )
    with setup.store(setup.tenant) as uow:
        assert uow.billing.append_event(event)
    made = setup.request.run(setup.owner, setup.tenant, DataRequestKind.EXPORT)
    document = setup.export.run(setup.owner, setup.tenant, made.id).document()
    (row,) = document["services"]["identity"]["sections"]["billing_events"]
    assert row["payload"] == {"event": "subscription.activated"}
    assert "acc_example" not in json.dumps(document)


def test_the_directory_counts_every_tenant_s_open_requests(setup: Setup) -> None:
    now = [NOW]
    directory = MemoryDataRequestDirectory(setup.store, lambda: now[0])
    assert directory.open_counts() == [
        OpenRequests(DataRequestKind.EXPORT, 0, 0),
        OpenRequests(DataRequestKind.DELETION, 0, 0),
    ]
    first = setup.request.run(setup.owner, setup.tenant, DataRequestKind.EXPORT)
    setup.request.run(setup.firm_admin, setup.firm, DataRequestKind.EXPORT)
    unanswered = DataRequest.new(
        setup.firm,
        DataRequestKind.DELETION,
        DataRequestSource.SELF_SERVICE,
        requested_by="",
        reason="",
        at=NOW,
    )
    with setup.store(setup.firm) as uow:
        uow.data_requests.add(unanswered)
    assert directory.open_counts() == [
        OpenRequests(DataRequestKind.EXPORT, 2, 0),
        OpenRequests(DataRequestKind.DELETION, 1, 0),
    ]
    ExportTenantData(setup.store).run(setup.owner, setup.tenant, first.id)
    assert directory.open_counts()[0] == OpenRequests(DataRequestKind.EXPORT, 1, 0)
    now[0] = NOW + timedelta(days=31)
    assert directory.open_counts() == [
        OpenRequests(DataRequestKind.EXPORT, 0, 0),
        OpenRequests(DataRequestKind.DELETION, 1, 1),
    ], "an offered export the tenant never downloaded expires; an unanswered request pages"


# ---------------------------------------------------------------- the gauges


class CountingDirectory:
    def __init__(self, *, fails: bool = False) -> None:
        self.reads = 0
        self.fails = fails

    def open_counts(self) -> list[OpenRequests]:
        self.reads += 1
        if self.fails:
            raise RuntimeError("function missing")
        return [
            OpenRequests(DataRequestKind.EXPORT, 3, 2),
            OpenRequests(DataRequestKind.DELETION, 1, 0),
        ]


def test_the_gauges_share_one_reading_a_minute_and_report_nothing_after_a_failure() -> None:
    directory = CountingDirectory()
    now = [NOW]
    gauges = DataRequestGauges(directory, lambda: now[0])
    options = CallbackOptions()
    opened = {o.attributes["kind"]: o.value for o in gauges.open_requests(options) if o.attributes}
    assert opened == {"export": 3, "deletion": 1}
    assert [o.value for o in gauges.overdue_requests(options)] == [2]
    assert directory.reads == 1
    now[0] = NOW + timedelta(seconds=61)
    directory.fails = True
    assert list(gauges.overdue_requests(options)) == []
    assert list(gauges.open_requests(options)) == []
    assert directory.reads == 2


# ---------------------------------------------------------------- the HTTP source


def answering(status: int, body: object, seen: list[httpx2.Request]) -> httpx2.Client:
    def handle(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(status, json=body)

    return httpx2.Client(transport=httpx2.MockTransport(handle), base_url="http://profile.test")


def test_the_http_source_asks_for_the_tenant_with_identity_s_token() -> None:
    tenant = TenantId.new()
    seen: list[httpx2.Request] = []
    body = {
        "service": "profile",
        "tenant_id": str(tenant),
        "generated_at": NOW.isoformat(),
        "sections": {"nodes": []},
    }
    source = HttpExportSource(
        "profile",
        "http://unused",
        token=lambda asked: f"minted-for-{asked}",
        client=answering(200, body, seen),
    )
    section = source.export(tenant)
    assert section.data == body
    (request,) = seen
    assert request.url.path == "/v1/profile/data-export"
    assert request.headers["x-tenant-id"] == str(tenant)
    assert request.headers["authorization"] == f"Bearer minted-for-{tenant}"


def test_identity_mints_each_source_a_token_bound_to_the_tenant_and_addressed_to_it() -> None:
    issuer = TestIssuer()
    minter = IssuerMinter(
        TokenIssuer(issuer.keys, issuer=issuer.issuer_name, audience=issuer.audience)
    )
    settings = identity_settings(
        identity_export_sources="profile=http://profile.test,obligation=http://obligation.test"
    )
    tenant = TenantId.new()
    seen: list[httpx2.Request] = []
    sources = export_sources(settings, minter)
    assert [source.service for source in sources] == ["profile", "obligation"]
    for source in sources:
        source._client = answering(503, {}, seen)  # type: ignore[attr-defined]
        source.export(tenant)
    verifier = issuer.verifier()
    principals = [
        verifier.verify(request.headers["authorization"].removeprefix("Bearer "))
        for request in seen
    ]
    assert [(p.subject, p.acts_for, p.audience) for p in principals] == [
        ("identity", tenant, "profile"),
        ("identity", tenant, "obligation"),
    ]
    assert all(p.scopes == {Scope.DATA_EXPORT} for p in principals), "no tenant:act"
    claims = [
        pyjwt.decode(r.headers["authorization"][7:], options={"verify_signature": False})
        for r in seen
    ]
    assert all(claim["exp"] - claim["iat"] == 120 for claim in claims)


@pytest.mark.parametrize(
    ("status", "body", "reason"),
    [
        (503, {"type": "x"}, "answered 503"),
        (200, ["not", "an", "object"], "cannot read"),
        (200, {"service": "obligation"}, "another service"),
        (200, {"service": "profile", "tenant_id": str(uuid4())}, "another tenant"),
    ],
)
def test_the_http_source_turns_a_wrong_answer_into_a_pending_section(
    status: int, body: object, reason: str
) -> None:
    source = HttpExportSource("profile", "http://unused", client=answering(status, body, []))
    section = source.export(TenantId.new())
    assert section.data is None
    assert reason in section.error


def test_the_http_source_survives_an_unreachable_service() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    client = httpx2.Client(transport=httpx2.MockTransport(refuse), base_url="http://x.test")
    section = HttpExportSource("profile", "http://unused", client=client).export(TenantId.new())
    assert (section.data, section.error) == (None, "unreachable (ConnectError)")


def test_outside_local_and_test_the_sources_are_required_and_never_plain_http() -> None:
    staging: dict[str, Any] = {"env": "staging", "identity_dev_client_secret": None}
    with pytest.raises(ValueError, match="needs CW_IDENTITY_EXPORT_SOURCES"):
        identity_settings(**staging, identity_export_sources=DEFAULT_EXPORT_SOURCES)
    with pytest.raises(ValueError, match="plain http"):
        identity_settings(**staging, identity_export_sources="profile=http://profile.internal")
    allowed = identity_settings(
        **staging,
        identity_export_sources=(
            "profile=https://profile.example.org,obligation=http://127.0.0.1:8080,"
            "notification=http://localhost:8080,applicability-engine=http://[::1]:8080"
        ),
    )
    assert len(allowed.export_sources) == 4
    assert identity_settings(identity_export_sources=DEFAULT_EXPORT_SOURCES).export_sources


def test_the_sources_setting_names_services_and_their_urls() -> None:
    assert parse_export_sources(" profile=http://localhost:8002/ ,obligation=https://o.test") == {
        "profile": "http://localhost:8002",
        "obligation": "https://o.test",
    }
    assert parse_export_sources("") == {}
    for wrong in ("profile", "Profile=http://x", "profile=ftp://x", "a=http://x,a=http://y"):
        with pytest.raises(ValueError, match="CW_IDENTITY_EXPORT_SOURCES"):
            parse_export_sources(wrong)
    with pytest.raises(ValueError, match="not identity"):
        identity_settings(identity_export_sources="identity=http://localhost:8001")
    assert list(identity_settings(identity_export_sources="profile=http://x").export_sources) == [
        "profile"
    ]


# ---------------------------------------------------------------- the routes


@pytest.fixture
def header_mode() -> Iterator[tuple[TestClient, FakeSource]]:
    source = FakeSource("profile")
    with TestClient(build_app(identity_settings(), export_sources=[source])) as client:
        yield client, source


def signed_up_tenant(client: TestClient, phone: str = OWNER_PHONE) -> dict[str, Any]:
    token = client.post("/v1/identity/dev/provider-tokens", json={"phone": phone}).json()
    created = client.post(
        "/v1/identity/tenants",
        json={
            "kind": "business",
            "name": "Example Traders",
            "provider_token": token["provider_token"],
        },
    )
    assert created.status_code == 201, created.text
    body: dict[str, Any] = created.json()
    return body


def test_the_routes_in_header_mode(header_mode: tuple[TestClient, FakeSource]) -> None:
    client, _ = header_mode
    tenant = signed_up_tenant(client)["tenant"]["id"]
    as_tenant = {"x-tenant-id": tenant}
    assert client.post(REQUESTS, json={"kind": "export"}).status_code == 401
    refused = client.post(REQUESTS, json={"kind": "deletion"}, headers=as_tenant)
    assert refused.status_code == 422
    assert refused.json()["type"].endswith(":identity-data-request-kind-unavailable")
    made = client.post(REQUESTS, json={"kind": "export", "reason": "copy"}, headers=as_tenant)
    assert made.status_code == 201, made.text
    request = made.json()
    assert (request["status"], request["overdue"], request["services_pending"]) == (
        "in_progress",
        False,
        ["identity", "profile"],
    )
    assert client.get(REQUESTS, headers=as_tenant).json()["items"] == [request]
    one = client.get(f"{REQUESTS}/{request['id']}", headers=as_tenant)
    assert one.json() == request
    missing = client.get(f"{REQUESTS}/{uuid4()}", headers=as_tenant)
    assert missing.status_code == 404
    assert missing.json()["type"].endswith(":identity-data-request-not-found")
    download = client.get(f"{REQUESTS}/{request['id']}/export", headers=as_tenant)
    assert download.status_code == 200, download.text
    assert download.headers["content-disposition"] == (
        f'attachment; filename="compliancewatch-export-{request["id"]}.json"'
    )
    assert download.headers["cache-control"] == "no-store"
    assert download.json()["complete"] is True
    after = client.get(f"{REQUESTS}/{request['id']}", headers=as_tenant).json()
    assert (after["status"], after["services_done"], after["services_pending"]) == (
        "completed",
        ["identity", "profile"],
        [],
    )
    other = {"x-tenant-id": signed_up_tenant(client, OTHER_PHONE)["tenant"]["id"]}
    assert client.get(REQUESTS, headers=other).json()["items"] == []
    assert client.get(f"{REQUESTS}/{request['id']}/export", headers=other).status_code == 404


def test_the_routes_in_token_mode() -> None:
    source = FakeSource("profile")
    settings = identity_settings(auth_mode="token")
    with TestClient(build_app(settings, export_sources=[source])) as client:
        created = signed_up_tenant(client)
        owner = bearer(created["session"]["access_token"])
        assert client.get(REQUESTS).status_code == 401
        made = client.post(REQUESTS, json={"kind": "export"}, headers=owner)
        assert made.status_code == 201, made.text
        request_id = made.json()["id"]
        staff = client.post(
            "/v1/identity/users", json={"phone": STAFF_PHONE, "roles": ["staff"]}, headers=owner
        )
        assert staff.status_code == 201
        staff_token = client.post(
            "/v1/identity/dev/provider-tokens", json={"phone": STAFF_PHONE}
        ).json()["provider_token"]
        as_staff = bearer(
            client.post("/v1/identity/sessions", json={"provider_token": staff_token}).json()[
                "access_token"
            ]
        )
        for path in (REQUESTS, f"{REQUESTS}/{request_id}", f"{REQUESTS}/{request_id}/export"):
            assert client.get(path, headers=as_staff).status_code == 403, path
        assert client.post(REQUESTS, json={"kind": "export"}, headers=as_staff).status_code == 403
        naming = client.post(
            REQUESTS, json={"kind": "export", "tenant_id": str(uuid4())}, headers=owner
        )
        assert naming.status_code == 403
        download = client.get(f"{REQUESTS}/{request_id}/export", headers=owner)
        assert download.status_code == 200
        assert UUID(download.json()["request_id"]) == UUID(request_id)
        issued = client.post(
            "/v1/identity/service-tokens",
            json={"client_id": "worker", "client_secret": identity_settings_secret()},
        )
        service = {**bearer(issued.json()["access_token"]), "x-tenant-id": created["tenant"]["id"]}
        assert client.get(REQUESTS, headers=service).status_code == 403


def identity_settings_secret() -> str:
    from identity.testing import DEV_CLIENT_SECRET

    return DEV_CLIENT_SECRET


def test_the_admin_makes_a_support_request_through_the_route() -> None:
    store_settings = identity_settings(auth_mode="token")
    app = build_app(store_settings, export_sources=[])
    with TestClient(app) as client:
        tenant = signed_up_tenant(client)["tenant"]["id"]
        wiring = app.state.wiring
        provider = wiring.provider
        assert isinstance(provider, FakeIdentityProvider)
        BootstrapInternalTenant(wiring.unit_of_work, provider).run(
            "Example Regulatory", Contact(email=ADMIN_EMAIL)
        )
        session = client.post(
            "/v1/identity/sessions",
            json={"provider_token": provider.issue(email=ADMIN_EMAIL, aal=AAL2)},
        )
        assert session.status_code == 200, session.text
        admin = bearer(session.json()["access_token"])
        own = client.post(REQUESTS, json={"kind": "export"}, headers=admin)
        assert own.status_code == 403
        support = client.post(
            REQUESTS,
            json={"kind": "export", "reason": "Asked by email", "tenant_id": tenant},
            headers=admin,
        )
        assert support.status_code == 201, support.text
        assert support.json()["source"] == "support"
        assert client.get(REQUESTS, headers=admin).status_code == 403
