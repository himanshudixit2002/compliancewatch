"""A tenant's deletion at identity: the request and what it shuts at once, identity's own erasure
(the provider's accounts, then the store), the answers that complete the request, the resend,
and the routes. On the memory store, with the worker's handlers run through consumers on a
SQLite inbox; tests/integration/test_erasure_schema.py runs the Postgres eraser."""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import NullPool

from domain_kernel.access import ANONYMOUS
from domain_kernel.erasure import DATA_ERASED_TOPIC, TenantDataErased
from domain_kernel.errors import InvariantViolationError
from domain_kernel.events import DomainEvent
from domain_kernel.ids import TenantId
from identity.admin import main as admin_main
from identity.application.bootstrap import BootstrapInternalTenant
from identity.application.consents import RecordConsent
from identity.application.data_requests import (
    ListDataRequests,
    ReadDataRequest,
    RequestDeletion,
    RequestExport,
)
from identity.application.erasure import DeleteProviderAccounts, RecordErasure, ResendDeletion
from identity.application.sessions import ExchangeSession, check_session, user_principal
from identity.application.tenancy import CreateTenant
from identity.domain.billing import Customer
from identity.domain.consent import ConsentPurpose, ConsentSource
from identity.domain.data_requests import (
    DataRequest,
    DataRequestKind,
    DataRequestSource,
    DataRequestStatus,
    parse_services,
)
from identity.domain.erasure import ERASURE_SERVICES, pseudonym
from identity.domain.errors import (
    DeletionRequestNotFoundError,
    TenantDeletingError,
    TenantNotErasableError,
)
from identity.domain.events import TenantDeletionRequested
from identity.domain.provider import AAL2
from identity.domain.tenancy import Contact, Tenant, TenantKind, TenantStatus
from identity.infrastructure.erasure import MemoryIdentityEraser
from identity.infrastructure.memory import MemoryStore
from identity.infrastructure.minter import IssuerMinter
from identity.infrastructure.providers.fake import FakeIdentityProvider
from identity.main import build_app
from identity.testing import identity_settings
from identity.worker import GROUP_ID, RECORDS_GROUP_ID, erasure_handler, records_handler
from py_common.auth import TokenIssuer
from py_common.auth.testing import TestIssuer
from py_common.events import encode, to_message
from py_common.outbox import (
    ConsumerConfig,
    IdempotentConsumer,
    InboundRecord,
    Outcome,
    SyncProcessedStore,
    processed_event,
    read_first_store,
    sync_handler,
)
from py_common.outbox.consumer import Handler
from py_common.outbox.store import ProcessedStore
from py_common.outbox.testing import FakeProducer

NOW = datetime(2000, 6, 1, 9, 0, tzinfo=UTC)
OWNER_PHONE = "+919876543210"
FIRM_PHONE = "+919800000001"
ADMIN_EMAIL = "admin@example.org"
REQUESTS = "/v1/identity/data-requests"
NOTICE = "2000-01"


class Setup:
    """A business and a CA firm signed up on one memory store, the internal tenant with its
    admin, the business's consent and billing customer, and the use cases."""

    def __init__(self) -> None:
        self.store = MemoryStore()
        self.provider = FakeIdentityProvider()
        issuer = TestIssuer()
        self.minter = IssuerMinter(
            TokenIssuer(issuer.keys, issuer=issuer.issuer_name, audience=issuer.audience)
        )
        create = CreateTenant(
            self.store, self.provider, self.minter, ttl=timedelta(minutes=10), clock=lambda: NOW
        )
        self.owner_token = self.provider.issue(phone=OWNER_PHONE)
        business = create.run(self.owner_token, TenantKind.BUSINESS, "Example Traders")
        firm = create.run(
            self.provider.issue(phone=FIRM_PHONE, aal=AAL2), TenantKind.CA_FIRM, "Example CA"
        )
        self.tenant, self.owner = business.tenant.id, business.session.principal
        self.owner_subject = business.user.provider_subject
        assert self.provider.provision(phone=OWNER_PHONE) == self.owner_subject
        self.firm, self.firm_admin = firm.tenant.id, firm.session.principal
        internal, admin = BootstrapInternalTenant(self.store, self.provider, clock=lambda: NOW).run(
            "Example Regulatory", Contact(email=ADMIN_EMAIL)
        )
        self.internal, self.admin = internal.id, user_principal(admin, mfa=True)
        self.delete = RequestDeletion(self.store, clock=lambda: NOW)
        self.export = RequestExport(self.store, clock=lambda: NOW)
        self.list = ListDataRequests(self.store)
        self.read = ReadDataRequest(self.store)
        RecordConsent(self.store, clock=lambda: NOW).run(
            self.tenant,
            str(self.owner.user_id),
            ConsentPurpose.WHATSAPP_REMINDERS,
            granted=True,
            source=ConsentSource.WEB_ONBOARDING,
            notice_version=NOTICE,
            evidence="Example onboarding checkbox",
            recorded_by=self.owner.user_id,
        )
        with self.store(self.tenant) as uow:
            uow.billing.add_customer(
                Customer(self.tenant, "cust_example", "owner@example.org", "Example Owner"),
                provider="memory",
                at=NOW,
            )

    def deletion_events(self) -> list[TenantDeletionRequested]:
        return [e for e in self.store.events if isinstance(e, TenantDeletionRequested)]

    def erased_events(self) -> list[TenantDataErased]:
        return [e for e in self.store.events if isinstance(e, TenantDataErased)]


@pytest.fixture
def setup() -> Setup:
    return Setup()


# ---------------------------------------------------------------- the request


def test_the_owner_asks_and_the_tenant_shuts_at_once(setup: Setup) -> None:
    made = setup.delete.run(setup.owner, setup.tenant, reason="  closing the business ")
    assert (made.kind, made.source, made.status) == (
        DataRequestKind.DELETION,
        DataRequestSource.SELF_SERVICE,
        DataRequestStatus.RECEIVED,
    )
    assert made.deadline_at == NOW + timedelta(days=30)
    assert setup.store.tenants[setup.tenant].status is TenantStatus.DELETION_REQUESTED
    (event,) = setup.deletion_events()
    assert (event.tenant_id, event.requested_by, event.reason) == (
        setup.tenant,
        setup.owner.user_id,
        "closing the business",
    )
    assert (event.requested_at, event.deadline_at, event.retain_audit) == (
        NOW,
        made.deadline_at,
        True,
    )
    (entry,) = [e for e in setup.store.audit if e.action == "data_request.created"]
    assert entry.after is not None
    assert entry.after["kind"] == "deletion"

    exchange = ExchangeSession(setup.store, setup.provider, setup.minter, ttl=timedelta(minutes=10))
    with pytest.raises(TenantDeletingError):
        exchange.run(setup.owner_token)
    with setup.store(setup.tenant) as uow, pytest.raises(TenantDeletingError):
        check_session(uow, setup.owner)
    with pytest.raises(TenantDeletingError):
        setup.delete.run(setup.owner, setup.tenant)
    with pytest.raises(TenantDeletingError):
        setup.export.run(setup.owner, setup.tenant)
    assert setup.list.run(setup.owner, setup.tenant) == [made], "the owner follows it"
    assert setup.read.run(setup.owner, setup.tenant, made.id) == made
    assert setup.store.tenants[setup.firm].status is TenantStatus.ACTIVE


def test_support_asks_for_a_tenant_and_the_internal_tenant_is_never_erased(
    setup: Setup,
) -> None:
    made = setup.delete.run(
        setup.admin, setup.internal, reason="Asked by email", for_tenant=setup.firm
    )
    assert (made.tenant_id, made.source) == (setup.firm, DataRequestSource.SUPPORT)
    (event,) = setup.deletion_events()
    assert (event.tenant_id, event.requested_by) == (setup.firm, None)
    with pytest.raises(TenantNotErasableError):
        setup.delete.run(ANONYMOUS, setup.internal)
    with pytest.raises(TenantDeletingError):
        setup.delete.run(setup.admin, setup.internal, reason="Again", for_tenant=setup.firm)


def test_an_erased_tenant_keeps_no_name() -> None:
    tenant = Tenant(TenantId.new(), TenantKind.BUSINESS, "Example Traders", NOW)
    erased = tenant.deletion_requested().erased()
    assert (erased.status, erased.name) == (TenantStatus.ERASED, "")
    with pytest.raises(InvariantViolationError):
        Tenant(tenant.id, TenantKind.BUSINESS, "Example", NOW, status=TenantStatus.ERASED)
    with pytest.raises(InvariantViolationError):
        Tenant(tenant.id, TenantKind.BUSINESS, "", NOW)
    with pytest.raises(InvariantViolationError):
        erased.deletion_requested()


# ---------------------------------------------------------------- the request's state


def deletion(at: datetime = NOW) -> DataRequest:
    return DataRequest.new(
        TenantId.new(),
        DataRequestKind.DELETION,
        DataRequestSource.SELF_SERVICE,
        requested_by="",
        reason="",
        at=at,
    )


def test_a_deletion_completes_once_every_service_has_erased() -> None:
    request = deletion()
    expected = ("identity", "profile")
    once = request.record_erasure("profile", expected, NOW)
    assert (once.status, once.services_done, once.pending(expected)) == (
        DataRequestStatus.IN_PROGRESS,
        ("profile",),
        ("identity",),
    )
    assert once.record_erasure("profile", expected, NOW) == once, "a second answer is the same"
    done = once.record_erasure("identity", expected, NOW)
    assert (done.status, done.completed_at, done.pending(expected)) == (
        DataRequestStatus.COMPLETED,
        NOW,
        (),
    )
    with pytest.raises(InvariantViolationError):
        DataRequest.new(
            TenantId.new(),
            DataRequestKind.EXPORT,
            DataRequestSource.SELF_SERVICE,
            requested_by="",
            reason="",
            at=NOW,
        ).record_erasure("profile", expected, NOW)


def test_a_deletion_in_progress_is_overdue_past_its_deadline_and_never_expires() -> None:
    started = deletion().record_erasure("identity", ERASURE_SERVICES, NOW)
    late = started.deadline_at + timedelta(seconds=1)
    assert not started.is_overdue(started.deadline_at)
    assert started.is_overdue(late)
    assert not started.is_expired(late)
    assert started.is_open(late + timedelta(days=365))


def test_the_pseudonym_is_stable_per_tenant_and_leads_nowhere() -> None:
    tenant, other = TenantId.new(), TenantId.new()
    first = pseudonym(tenant, "owner@example.org")
    assert first.startswith("erased:")
    assert len(first) == len("erased:") + 16
    assert first == pseudonym(tenant, "owner@example.org")
    assert first != pseudonym(other, "owner@example.org")
    assert pseudonym(tenant, first) == first, "pseudonymising twice changes nothing"
    assert "owner" not in first


def test_the_services_setting_always_names_identity() -> None:
    assert identity_settings().erasure_services == ERASURE_SERVICES
    assert parse_services(" profile ,identity,profile", "x") == ("identity", "profile")
    with pytest.raises(ValueError, match="identity"):
        identity_settings(identity_erasure_services="profile")
    with pytest.raises(ValueError, match="service name"):
        parse_services("Profile", "x")


# ---------------------------------------------------------------- identity's erasure


def inbox(path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{path}", poolclass=NullPool)
    processed_event.create(engine)
    return engine


def run(handler: Handler, store: ProcessedStore, group: str, event: DomainEvent) -> Outcome:
    consumer = IdempotentConsumer(
        group_id=group,
        store=store,
        handler=handler,
        producer=FakeProducer(),
        config=ConsumerConfig(max_handler_attempts=1, retry_backoff_seconds=0),
    )
    message = to_message(event)
    record = InboundRecord(
        topic=message.topic, partition=0, offset=0, key=b"k", value=encode(message)
    )
    return asyncio.run(consumer.process(record))


class Erasures:
    """Identity's two consumers on SQLite inboxes, over the memory store."""

    def __init__(self, setup: Setup, tmp_path: Path, *, on: bool = True) -> None:
        self.setup = setup
        self.inbox = read_first_store(inbox(tmp_path / "erasure.sqlite"), GROUP_ID)
        self.records = SyncProcessedStore(
            inbox(tmp_path / "records.sqlite"), group_id=RECORDS_GROUP_ID
        )
        self.erase = erasure_handler(
            DeleteProviderAccounts(setup.store, setup.provider),
            enabled=lambda _: on,
            eraser_on=lambda _: MemoryIdentityEraser(setup.store),
            clock=lambda: NOW,
        )
        self.record = sync_handler(
            records_handler(
                RecordErasure(ERASURE_SERVICES, clock=lambda: NOW),
                units_on=lambda _: setup.store,
            )
        )

    def deletion(self, event: TenantDeletionRequested) -> Outcome:
        return run(self.erase, self.inbox, GROUP_ID, event)

    def answer(self, event: TenantDataErased) -> Outcome:
        return run(self.record, self.records, RECORDS_GROUP_ID, event)


def answer_of(service: str, asked: TenantDeletionRequested) -> TenantDataErased:
    assert asked.tenant_id is not None
    return TenantDataErased(
        tenant_id=asked.tenant_id,
        correlation_id=asked.correlation_id,
        causation_id=asked.event_id,
        service=service,
        deletion_event_id=asked.event_id,
        erased_at=NOW,
        tables={"widget": 1},
    )


def test_with_the_flag_on_identity_erases_the_tenant_and_the_answers_complete_it(
    setup: Setup, tmp_path: Path
) -> None:
    made = setup.delete.run(setup.owner, setup.tenant)
    (asked,) = setup.deletion_events()
    firm_user = setup.firm_admin.user_id
    erasures = Erasures(setup, tmp_path)
    assert setup.provider.lookup(setup.owner_subject) is not None

    assert erasures.deletion(asked) is Outcome.PROCESSED
    assert setup.provider.lookup(setup.owner_subject) is None, "the provider's account went"
    store = setup.store
    assert [u for u in store.users.values() if u.tenant_id == setup.tenant] == []
    assert [s for s in store.subjects.values() if s.tenant_id == setup.tenant] == []
    assert firm_user in store.users, "another tenant's users stay"
    tenant = store.tenants[setup.tenant]
    assert (tenant.status, tenant.name, tenant.kind) == (
        TenantStatus.ERASED,
        "",
        TenantKind.BUSINESS,
    )
    (consent,) = [r for r in store.records if r.tenant_id == setup.tenant]
    assert consent.subject == pseudonym(setup.tenant, str(setup.owner.user_id))
    assert (consent.evidence, consent.recorded_by, consent.granted) == ("", None, True)
    customer, _, _ = store.billing.customers[setup.tenant]
    assert (customer.provider_customer_id, customer.name) == ("cust_example", "")
    assert customer.email == pseudonym(setup.tenant, "owner@example.org")
    (answer,) = setup.erased_events()
    assert (answer.service, answer.causation_id, answer.deletion_event_id) == (
        "identity",
        asked.event_id,
        asked.event_id,
    )
    assert dict(answer.tables)["app_user"] == 1
    assert "consent_record" in {item.table for item in answer.retained}
    (entry,) = [e for e in store.audit if e.action == "tenant.erased"]
    assert (entry.tenant_id, entry.actor.label) == (setup.tenant, "system:identity")

    assert erasures.deletion(asked) is Outcome.SKIPPED, "a redelivery erases once"

    assert erasures.answer(answer) is Outcome.PROCESSED
    with store(setup.tenant) as uow:
        started = uow.data_requests.get(made.id)
    assert started is not None
    assert (started.status, started.services_done) == (DataRequestStatus.IN_PROGRESS, ("identity",))
    for service in ("profile", "obligation", "notification", "applicability-engine"):
        assert erasures.answer(answer_of(service, asked)) is Outcome.PROCESSED
    assert erasures.answer(answer_of("profile", asked)) is Outcome.PROCESSED, "a repeat answer"
    with store(setup.tenant) as uow:
        waiting = uow.data_requests.get(made.id)
    assert waiting is not None
    assert waiting.pending(ERASURE_SERVICES) == ("rulebook",)
    assert erasures.answer(answer_of("rulebook", asked)) is Outcome.PROCESSED
    with store(setup.tenant) as uow:
        done = uow.data_requests.get(made.id)
    assert done is not None
    assert (done.status, done.completed_at, done.services_done) == (
        DataRequestStatus.COMPLETED,
        NOW,
        ERASURE_SERVICES,
    )
    actions = [e.action for e in store.audit if e.subject_id == str(made.id)]
    assert actions.count("data_request.erased") == len(ERASURE_SERVICES)
    assert actions.count("data_request.completed") == 1
    assert erasures.answer(answer_of("rulebook", asked)) is Outcome.PROCESSED
    late = [e.action for e in store.audit if e.subject_id == str(made.id)]
    assert late == actions, "an answer after completion changes nothing"


def test_with_the_flag_off_nothing_is_erased_and_the_request_stays_pending(
    setup: Setup, tmp_path: Path
) -> None:
    made = setup.delete.run(setup.owner, setup.tenant)
    (asked,) = setup.deletion_events()
    erasures = Erasures(setup, tmp_path, on=False)
    assert erasures.deletion(asked) is Outcome.PROCESSED
    assert setup.provider.lookup(setup.owner_subject) is not None
    assert setup.owner.user_id in setup.store.users
    assert setup.store.tenants[setup.tenant].status is TenantStatus.DELETION_REQUESTED
    assert setup.erased_events() == []
    with setup.store(setup.tenant) as uow:
        waiting = uow.data_requests.get(made.id)
    assert waiting is not None
    assert waiting.status is DataRequestStatus.RECEIVED
    assert waiting.is_overdue(made.deadline_at + timedelta(days=1))


def test_an_answer_without_an_open_request_changes_nothing(setup: Setup, tmp_path: Path) -> None:
    asked = TenantDeletionRequested(
        tenant_id=setup.firm,
        requested_by=None,
        requested_at=NOW,
        deadline_at=NOW + timedelta(days=30),
    )
    erasures = Erasures(setup, tmp_path)
    assert erasures.answer(answer_of("profile", asked)) is Outcome.PROCESSED
    assert [e for e in setup.store.audit if e.action.startswith("data_request.")] == []


def test_a_malformed_answer_is_dead_lettered(setup: Setup, tmp_path: Path) -> None:
    erasures = Erasures(setup, tmp_path)
    message = to_message(answer_of("profile", deletion_event(setup)))
    broken = message.model_copy(update={"payload": {**message.payload, "service": "Profile"}})
    record = InboundRecord(
        topic=DATA_ERASED_TOPIC, partition=0, offset=0, key=b"k", value=encode(broken)
    )
    producer = FakeProducer()
    consumer = IdempotentConsumer(
        group_id=RECORDS_GROUP_ID,
        store=erasures.records,
        handler=erasures.record,
        producer=producer,
        config=ConsumerConfig(max_handler_attempts=1, retry_backoff_seconds=0),
    )
    assert asyncio.run(consumer.process(record)) is Outcome.DEAD


def deletion_event(setup: Setup) -> TenantDeletionRequested:
    return TenantDeletionRequested(
        tenant_id=setup.tenant,
        requested_by=None,
        requested_at=NOW,
        deadline_at=NOW + timedelta(days=30),
    )


# ---------------------------------------------------------------- the resend


def test_resend_sends_the_open_request_again(setup: Setup) -> None:
    made = setup.delete.run(setup.owner, setup.tenant)
    resent = ResendDeletion(setup.store, clock=lambda: NOW).run(
        setup.tenant, reason="flag turned on"
    )
    assert resent.id == made.id
    first, second = setup.deletion_events()
    assert first.event_id != second.event_id
    assert (second.requested_at, second.deadline_at, second.requested_by) == (
        first.requested_at,
        first.deadline_at,
        None,
    )
    (entry,) = [e for e in setup.store.audit if e.action == "data_request.resent"]
    assert (entry.actor.label, entry.reason) == ("system:identity-admin", "flag turned on")
    with pytest.raises(DeletionRequestNotFoundError):
        ResendDeletion(setup.store).run(setup.firm, reason="none asked")


def test_the_admin_command_resends(setup: Setup, capsys: pytest.CaptureFixture[str]) -> None:
    made = setup.delete.run(setup.owner, setup.tenant)
    code = admin_main(
        ["erasure", "resend", "--tenant", str(setup.tenant), "--reason", "flag turned on"],
        unit_of_work=setup.store,
        provider=setup.provider,
    )
    assert code == 0
    assert str(made.id) in capsys.readouterr().out
    assert len(setup.deletion_events()) == 2
    refused = admin_main(
        ["erasure", "resend", "--tenant", str(setup.firm), "--reason", "none asked"],
        unit_of_work=setup.store,
        provider=setup.provider,
    )
    assert refused == 1


# ---------------------------------------------------------------- the routes


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(build_app(identity_settings())) as client:
        yield client


def signed_up(client: TestClient, phone: str = OWNER_PHONE) -> tuple[dict[str, str], str]:
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
    return {"x-tenant-id": created.json()["tenant"]["id"]}, token["provider_token"]


def test_the_routes_record_a_deletion_and_refuse_its_sign_ins(client: TestClient) -> None:
    as_tenant, provider_token = signed_up(client)
    made = client.post(
        REQUESTS, json={"kind": "deletion", "reason": "Example closing"}, headers=as_tenant
    )
    assert made.status_code == 201, made.text
    request = made.json()
    assert (request["kind"], request["status"], request["overdue"]) == (
        "deletion",
        "received",
        False,
    )
    assert request["services_pending"] == list(ERASURE_SERVICES)
    assert client.get(f"{REQUESTS}/{request['id']}", headers=as_tenant).json() == request
    refused = client.post("/v1/identity/sessions", json={"provider_token": provider_token})
    assert refused.status_code == 403, refused.text
    assert refused.json()["type"].endswith(":identity-tenant-deleting")
    again = client.post(REQUESTS, json={"kind": "export"}, headers=as_tenant)
    assert again.status_code == 403
    assert again.json()["type"].endswith(":identity-tenant-deleting")
