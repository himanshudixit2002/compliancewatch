"""A tenant's deletion at identity: the request and what it shuts at once, identity's own erasure
(the provider's accounts, then the store), the answers that complete the request, the resend,
and the routes. On the memory store, with the worker's handlers run through consumers on a
SQLite inbox; tests/integration/test_erasure_schema.py runs the Postgres eraser."""

import asyncio
import hashlib
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import NullPool

from domain_kernel.access import ANONYMOUS
from domain_kernel.audit import AuditActor, AuditEntry
from domain_kernel.erasure import DATA_ERASED_TOPIC, DeletionRequest, TenantDataErased
from domain_kernel.errors import InvariantViolationError
from domain_kernel.events import DomainEvent
from domain_kernel.ids import EventId, TenantId, UserId
from identity.admin import main as admin_main
from identity.application.bootstrap import BootstrapInternalTenant
from identity.application.consents import RecordConsent
from identity.application.data_requests import (
    ListDataRequests,
    ReadDataRequest,
    RequestDeletion,
    RequestExport,
)
from identity.application.erasure import (
    CheckErasure,
    DeleteProviderAccounts,
    RecordErasure,
    ResendDeletion,
)
from identity.application.sessions import ExchangeSession, check_session, user_principal
from identity.application.tenancy import CreateTenant
from identity.domain.billing import Customer, Subscription, SubscriptionStatus
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
from identity.settings import DEV_ERASURE_PEPPER
from identity.testing import DEV_CLIENT_SECRET, identity_settings
from identity.worker import GROUP_ID, RECORDS_GROUP_ID, erasure_handler, records_handler
from identity.worker import components as worker_components
from py_common.auth import TokenIssuer
from py_common.auth.testing import TestIssuer
from py_common.erasure import erase_and_record
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
ERASURES = "/v1/identity/erasures"
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

PEPPER = b"Example pepper of thirty-two bytes or more"
SECOND_PASS = timedelta(minutes=15)


def deletion(at: datetime = NOW) -> DataRequest:
    request = DataRequest.new(
        TenantId.new(),
        DataRequestKind.DELETION,
        DataRequestSource.SELF_SERVICE,
        requested_by="",
        reason="",
        at=at,
    )
    return request.sent(EventId.new())


def test_a_deletion_completes_once_every_service_has_answered_both_passes() -> None:
    request = deletion()
    first = request.deletion_event_id
    assert first is not None
    expected = ("identity", "profile")
    assert request.erasure_pass == 1
    once = request.record_erasure("profile", expected, NOW, event_id=first)
    assert (once.status, once.services_done, once.pending(expected)) == (
        DataRequestStatus.IN_PROGRESS,
        ("profile",),
        ("identity",),
    )
    assert once.record_erasure("profile", expected, NOW, event_id=first) == once, "the same"
    stale = once.record_erasure("identity", expected, NOW, event_id=EventId.new())
    assert stale == once, "an answer to another event changes nothing"
    answered = once.record_erasure("identity", expected, NOW, event_id=first)
    assert answered.first_pass_complete(expected)
    assert answered.status is DataRequestStatus.IN_PROGRESS, "not done after one pass"
    second = EventId.new()
    waiting = answered.schedule_second_pass(second, NOW + SECOND_PASS, expected)
    assert (waiting.erasure_pass, waiting.deletion_event_id, waiting.second_pass_at) == (
        2,
        second,
        NOW + SECOND_PASS,
    )
    assert waiting.pending(expected) == expected, "every service owes the second pass"
    assert waiting.record_erasure("profile", expected, NOW, event_id=first) == waiting
    half = waiting.record_erasure("profile", expected, NOW, event_id=second)
    assert (half.status, half.second_pass_done) == (DataRequestStatus.IN_PROGRESS, ("profile",))
    done = half.record_erasure("identity", expected, NOW, event_id=second)
    assert (done.status, done.completed_at, done.pending(expected)) == (
        DataRequestStatus.COMPLETED,
        NOW,
        (),
    )
    assert done.record_erasure("profile", expected, NOW, event_id=second) == done
    with pytest.raises(InvariantViolationError):
        once.schedule_second_pass(second, NOW, expected)
    export = DataRequest.new(
        TenantId.new(),
        DataRequestKind.EXPORT,
        DataRequestSource.SELF_SERVICE,
        requested_by="",
        reason="",
        at=NOW,
    )
    assert export.erasure_pass is None
    with pytest.raises(InvariantViolationError):
        export.record_erasure("profile", expected, NOW, event_id=first)
    with pytest.raises(InvariantViolationError):
        export.sent(first)
    with pytest.raises(InvariantViolationError):
        replace(request, second_pass_done=("profile",))


def test_a_deletion_in_progress_is_overdue_past_its_deadline_and_never_expires() -> None:
    request = deletion()
    assert request.deletion_event_id is not None
    started = request.record_erasure(
        "identity", ERASURE_SERVICES, NOW, event_id=request.deletion_event_id
    )
    late = started.deadline_at + timedelta(seconds=1)
    assert not started.is_overdue(started.deadline_at)
    assert started.is_overdue(late)
    assert not started.is_expired(late)
    assert started.is_open(late + timedelta(days=365))


def test_the_pseudonym_is_keyed_stable_per_pepper_and_leads_nowhere() -> None:
    tenant, other = TenantId.new(), TenantId.new()
    first = pseudonym(tenant, "+919876543250", PEPPER)
    assert first.startswith("erased:")
    assert len(first) == len("erased:") + 32
    assert first == pseudonym(tenant, "+919876543250", PEPPER), "stable under one pepper"
    assert first != pseudonym(other, "+919876543250", PEPPER), "another tenant"
    assert first != pseudonym(tenant, "+919876543250", PEPPER + b"!"), "another pepper"
    unkeyed = hashlib.sha256(f"{tenant}|+919876543250".encode()).hexdigest()
    assert unkeyed[:32] not in first, "a dictionary of unkeyed hashes finds nothing"
    assert pseudonym(tenant, first, PEPPER) == first, "pseudonymising twice changes nothing"
    assert "9876543250" not in first
    with pytest.raises(ValueError, match="pepper"):
        pseudonym(tenant, "+919876543250", b"")


def test_the_pepper_is_the_setting_or_the_dev_placeholder() -> None:
    assert identity_settings().erasure_pepper == DEV_ERASURE_PEPPER.encode()
    given = "Example pepper of thirty-two bytes or more"
    assert identity_settings(identity_erasure_pepper=given).erasure_pepper == given.encode()
    with pytest.raises(ValueError, match="32 bytes"):
        identity_settings(identity_erasure_pepper="short")
    staging = identity_settings(env="staging", identity_dev_client_secret=None)
    with pytest.raises(ValueError, match="CW_IDENTITY_ERASURE_PEPPER"):
        staging.erasure_pepper  # noqa: B018


def test_the_second_pass_waits_longer_than_a_token_lives() -> None:
    assert identity_settings().identity_erasure_second_pass_seconds == 900
    with pytest.raises(ValueError, match="CW_ACCESS_TOKEN_TTL_SECONDS"):
        identity_settings(identity_erasure_second_pass_seconds=600)
    with pytest.raises(ValueError, match="CW_ACCESS_TOKEN_TTL_SECONDS"):
        identity_settings(access_token_ttl_seconds=1800, identity_erasure_second_pass_seconds=900)


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
            CheckErasure(setup.store),
            enabled=lambda _: on,
            eraser_on=lambda _: MemoryIdentityEraser(setup.store, pepper=PEPPER),
            clock=lambda: NOW,
        )
        self.record = sync_handler(
            records_handler(
                RecordErasure(ERASURE_SERVICES, clock=lambda: NOW, second_pass_after=SECOND_PASS),
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


def request_of(setup: Setup, made: DataRequest) -> DataRequest:
    with setup.store(setup.tenant) as uow:
        found = uow.data_requests.get(made.id)
    assert found is not None
    return found


def test_with_the_flag_on_identity_erases_the_tenant_and_both_passes_complete_it(
    setup: Setup, tmp_path: Path
) -> None:
    made = setup.delete.run(setup.owner, setup.tenant)
    (asked,) = setup.deletion_events()
    assert made.deletion_event_id == asked.event_id, "the request keeps the event it sent"
    firm_user = setup.firm_admin.user_id
    with setup.store(setup.tenant) as uow:
        uow.billing.add_subscription(
            Subscription(
                tenant_id=setup.tenant,
                plan_key="owner_monthly",
                provider_subscription_id="sub_example",
                status=SubscriptionStatus.CREATED,
                started_at=NOW,
                checkout_url="https://checkout.example.org/sub_example",
            )
        )
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
    assert store.erased.is_erased(setup.tenant), "the erased marker"
    (consent,) = [r for r in store.records if r.tenant_id == setup.tenant]
    assert consent.subject == pseudonym(setup.tenant, str(setup.owner.user_id), PEPPER)
    assert (consent.evidence, consent.recorded_by, consent.granted) == ("", None, True)
    customer, _, _ = store.billing.customers[setup.tenant]
    assert (customer.provider_customer_id, customer.name) == ("cust_example", "")
    assert customer.email == pseudonym(setup.tenant, "owner@example.org", PEPPER)
    assert store.billing.subscriptions["sub_example"].checkout_url == "", "the link is gone"
    (answer,) = setup.erased_events()
    assert (answer.service, answer.causation_id, answer.deletion_event_id) == (
        "identity",
        asked.event_id,
        asked.event_id,
    )
    assert dict(answer.tables)["app_user"] == 1
    assert dict(answer.tables)["billing_subscription"] == 1
    assert {"consent_record", "erased_tenant"} <= {item.table for item in answer.retained}
    (entry,) = [e for e in store.audit if e.action == "tenant.erased"]
    assert (entry.tenant_id, entry.actor.label) == (setup.tenant, "system:identity")
    assert entry.after is not None
    assert entry.after["other_provider_accounts"] == ()

    assert erasures.deletion(asked) is Outcome.SKIPPED, "a redelivery erases once"

    assert erasures.answer(answer) is Outcome.PROCESSED
    started = request_of(setup, made)
    assert (started.status, started.services_done) == (DataRequestStatus.IN_PROGRESS, ("identity",))
    for service in ("profile", "obligation", "notification", "applicability-engine"):
        assert erasures.answer(answer_of(service, asked)) is Outcome.PROCESSED
    assert erasures.answer(answer_of("profile", asked)) is Outcome.PROCESSED, "a repeat answer"
    assert request_of(setup, made).pending(ERASURE_SERVICES) == ("rulebook",)
    assert erasures.answer(answer_of("rulebook", asked)) is Outcome.PROCESSED

    waiting = request_of(setup, made)
    assert (waiting.status, waiting.erasure_pass, waiting.second_pass_at) == (
        DataRequestStatus.IN_PROGRESS,
        2,
        NOW + SECOND_PASS,
    )
    first, second = setup.deletion_events()
    assert waiting.deletion_event_id == second.event_id != first.event_id
    assert store.not_before[second.event_id.value] == NOW + SECOND_PASS, "held in the outbox"
    assert (second.requested_at, second.deadline_at) == (first.requested_at, first.deadline_at)
    assert erasures.answer(answer_of("profile", first)) is Outcome.PROCESSED
    assert request_of(setup, made) == waiting, "a late answer to the first pass changes nothing"

    assert erasures.deletion(second) is Outcome.PROCESSED, "the second pass checks out too"
    second_answer = setup.erased_events()[-1]
    assert second_answer.deletion_event_id == second.event_id
    assert dict(second_answer.tables)["tenant"] == 0, "nothing more to change"
    assert erasures.answer(second_answer) is Outcome.PROCESSED
    for service in ("profile", "obligation", "notification", "applicability-engine"):
        assert erasures.answer(answer_of(service, second)) is Outcome.PROCESSED
    assert request_of(setup, made).pending(ERASURE_SERVICES) == ("rulebook",)
    assert erasures.answer(answer_of("rulebook", second)) is Outcome.PROCESSED
    done = request_of(setup, made)
    assert (done.status, done.completed_at, done.second_pass_done) == (
        DataRequestStatus.COMPLETED,
        NOW,
        ERASURE_SERVICES,
    )
    actions = [e.action for e in store.audit if e.subject_id == str(made.id)]
    assert actions.count("data_request.erased") == 2 * len(ERASURE_SERVICES)
    assert actions.count("data_request.second_pass_scheduled") == 1
    assert actions.count("data_request.completed") == 1
    assert erasures.answer(answer_of("rulebook", second)) is Outcome.PROCESSED
    late = [e.action for e in store.audit if e.subject_id == str(made.id)]
    assert late == actions, "an answer after completion changes nothing"


def test_users_at_another_provider_are_listed_for_the_operator(
    setup: Setup, tmp_path: Path
) -> None:
    with setup.store(setup.tenant) as uow:
        (owner,) = uow.users.list()
        elsewhere = replace(
            owner, id=UserId.new(), provider="supabase", provider_subject=str(uuid4())
        )
        uow.users.add(elsewhere)
    setup.delete.run(setup.owner, setup.tenant)
    (asked,) = setup.deletion_events()
    assert Erasures(setup, tmp_path).deletion(asked) is Outcome.PROCESSED
    (entry,) = [e for e in setup.store.audit if e.action == "tenant.erased"]
    assert entry.after is not None
    assert entry.after["other_provider_accounts"] == (
        {
            "user_id": str(elsewhere.id),
            "provider": "supabase",
            "subject": elsewhere.provider_subject,
        },
    )
    assert elsewhere.id not in setup.store.users


@pytest.mark.parametrize("case", ["another event", "internal", "active", "no request", "unknown"])
def test_identity_refuses_an_event_it_did_not_send_before_touching_the_provider(
    setup: Setup, tmp_path: Path, case: str
) -> None:
    made = setup.delete.run(setup.owner, setup.tenant)
    (sent,) = setup.deletion_events()
    tenants = {
        "another event": setup.tenant,
        "internal": setup.internal,
        "active": setup.firm,
        "no request": setup.tenant,
        "unknown": TenantId.new(),
    }
    forged = TenantDeletionRequested(
        tenant_id=tenants[case],
        requested_by=None,
        requested_at=NOW,
        deadline_at=NOW + timedelta(days=30),
    )
    if case == "no request":
        with setup.store(setup.tenant) as uow:
            current = uow.data_requests.get(made.id)
            assert current is not None
            uow.data_requests.save(
                replace(current, status=DataRequestStatus.COMPLETED, completed_at=NOW)
            )
        forged = sent
    users = dict(setup.store.users)
    erasures = Erasures(setup, tmp_path)
    assert erasures.deletion(forged) is Outcome.REFUSED
    assert setup.provider.lookup(setup.owner_subject) is not None, "the provider was not asked"
    assert setup.store.users == users
    assert setup.erased_events() == []
    assert not setup.store.erased.is_erased(tenants[case])
    (entry,) = [e for e in setup.store.audit if e.action == "tenant.erasure_refused"]
    assert (entry.tenant_id, entry.actor.label) == (tenants[case], "system:identity")
    assert entry.after is not None
    assert entry.after["deletion_event_id"] == str(forged.event_id)


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
    waiting = request_of(setup, made)
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


@pytest.mark.parametrize("field", ["service", "deletion_event_id"])
def test_a_malformed_answer_is_dead_lettered(setup: Setup, tmp_path: Path, field: str) -> None:
    erasures = Erasures(setup, tmp_path)
    message = to_message(answer_of("profile", deletion_event(setup)))
    broken = message.model_copy(update={"payload": {**message.payload, field: "Profile"}})
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


def test_the_worker_needs_the_pepper_where_the_flag_can_be_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CW_TENANT_ERASURE_ENABLED", "true")
    staging = identity_settings(
        env="staging", identity_store="postgres", identity_dev_client_secret=None
    )
    with pytest.raises(ValueError, match="CW_IDENTITY_ERASURE_PEPPER"):
        worker_components(staging, provider=FakeIdentityProvider(), enabled=lambda _: True)
    monkeypatch.setenv("CW_TENANT_ERASURE_ENABLED", "false")
    hosted = worker_components(staging, provider=FakeIdentityProvider(), enabled=lambda _: False)
    assert [consumer.group_id for consumer in hosted.consumers] == [GROUP_ID, RECORDS_GROUP_ID]


# ---------------------------------------------------------------- the resend


def test_resend_sends_the_open_request_again_as_the_event_to_check(setup: Setup) -> None:
    made = setup.delete.run(setup.owner, setup.tenant)
    resent = ResendDeletion(setup.store, clock=lambda: NOW).run(
        setup.tenant, reason="flag turned on"
    )
    assert resent.id == made.id
    first, second = setup.deletion_events()
    assert first.event_id != second.event_id
    assert (resent.deletion_event_id, request_of(setup, made).deletion_event_id) == (
        second.event_id,
        second.event_id,
    )
    assert (second.requested_at, second.deadline_at, second.requested_by) == (
        first.requested_at,
        first.deadline_at,
        None,
    )
    (entry,) = [e for e in setup.store.audit if e.action == "data_request.resent"]
    assert (entry.actor.label, entry.reason) == ("system:identity-admin", "flag turned on")
    with pytest.raises(DeletionRequestNotFoundError):
        ResendDeletion(setup.store).run(setup.firm, reason="none asked")
    current = request_of(setup, made)
    with setup.store(setup.tenant) as uow:
        uow.data_requests.save(
            replace(current, status=DataRequestStatus.COMPLETED, completed_at=NOW)
        )
    with pytest.raises(DeletionRequestNotFoundError):
        ResendDeletion(setup.store).run(setup.tenant, reason="a completed request")


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


def service_headers(client: TestClient, client_id: str) -> dict[str, str]:
    issued = client.post(
        "/v1/identity/service-tokens",
        json={"client_id": client_id, "client_secret": DEV_CLIENT_SECRET},
    )
    assert issued.status_code == 200, issued.text
    return {"Authorization": f"Bearer {issued.json()['access_token']}"}


def test_the_check_route_answers_what_identity_holds_of_a_deletion(client: TestClient) -> None:
    as_tenant, _ = signed_up(client)
    tenant = as_tenant["x-tenant-id"]
    active = client.get(f"{ERASURES}/{tenant}")
    assert active.status_code == 200, active.text
    assert active.json() == {
        "tenant_id": tenant,
        "status": "active",
        "internal": False,
        "deletion_event_id": None,
    }
    made = client.post(REQUESTS, json={"kind": "deletion"}, headers=as_tenant)
    assert made.status_code == 201, made.text
    store = client.app.state.wiring.unit_of_work  # type: ignore[attr-defined]
    (sent,) = [e for e in store.events if isinstance(e, TenantDeletionRequested)]
    asked = client.get(f"{ERASURES}/{tenant}").json()
    assert (asked["status"], asked["deletion_event_id"]) == (
        "deletion_requested",
        str(sent.event_id),
    )
    unknown = client.get(f"{ERASURES}/{uuid4()}")
    assert unknown.status_code == 404
    assert unknown.json()["type"].endswith(":identity-tenant-not-found")


def test_the_check_route_takes_a_service_with_erasure_verify_only() -> None:
    with TestClient(build_app(identity_settings(auth_mode="token"))) as client:
        token = client.post("/v1/identity/dev/provider-tokens", json={"phone": OWNER_PHONE})
        created = client.post(
            "/v1/identity/tenants",
            json={
                "kind": "business",
                "name": "Example Traders",
                "provider_token": token.json()["provider_token"],
            },
        ).json()
        path = f"{ERASURES}/{created['tenant']['id']}"
        owner = {"Authorization": f"Bearer {created['session']['access_token']}"}
        assert client.get(path, headers=service_headers(client, "profile")).status_code == 200
        assert client.get(path, headers=service_headers(client, "worker")).status_code == 200
        assert client.get(path, headers=service_headers(client, "qa")).status_code == 403
        assert client.get(path, headers=owner).status_code == 403, "a person is refused"
        assert client.get(path).status_code == 401


def test_identity_s_tenant_routes_answer_410_once_it_erased_the_tenant(
    client: TestClient,
) -> None:
    as_tenant, _ = signed_up(client)
    made = client.post(REQUESTS, json={"kind": "deletion"}, headers=as_tenant).json()
    store = client.app.state.wiring.unit_of_work  # type: ignore[attr-defined]
    tenant = TenantId.parse(as_tenant["x-tenant-id"])
    MemoryIdentityEraser(store, pepper=PEPPER).record(
        TenantDataErased(
            tenant_id=tenant, service="identity", deletion_event_id=EventId.new(), erased_at=NOW
        ),
        audit_entry_for(tenant),
    )
    gone = client.get(f"{REQUESTS}/{made['id']}", headers=as_tenant)
    assert gone.status_code == 410, gone.text
    assert gone.json()["type"].endswith(":tenant-erased")
    assert client.get(f"{ERASURES}/{tenant}").status_code == 200, "the check still answers"


def audit_entry_for(tenant: TenantId) -> AuditEntry:
    return AuditEntry(
        action="tenant.erased",
        tenant_id=tenant,
        subject_type="tenant",
        subject_id=str(tenant),
        actor=AuditActor.system("identity"),
        occurred_at=NOW,
    )


def test_a_token_issued_before_the_erasure_opens_nothing_after_it() -> None:
    with TestClient(build_app(identity_settings(auth_mode="token"))) as client:
        token = client.post("/v1/identity/dev/provider-tokens", json={"phone": OWNER_PHONE})
        created = client.post(
            "/v1/identity/tenants",
            json={
                "kind": "business",
                "name": "Example Traders",
                "provider_token": token.json()["provider_token"],
            },
        ).json()
        owner = {"Authorization": f"Bearer {created['session']['access_token']}"}
        assert client.get("/v1/identity/me", headers=owner).status_code == 200
        made = client.post(REQUESTS, json={"kind": "deletion"}, headers=owner)
        assert made.status_code == 201, made.text
        assert client.get("/v1/identity/me", headers=owner).status_code == 403, "deleting"
        store = client.app.state.wiring.unit_of_work  # type: ignore[attr-defined]
        (sent,) = [e for e in store.events if isinstance(e, TenantDeletionRequested)]
        assert sent.tenant_id is not None
        erase_and_record(
            "identity",
            MemoryIdentityEraser(store, pepper=PEPPER),
            DeletionRequest(
                event_id=sent.event_id,
                tenant_id=sent.tenant_id,
                correlation_id=sent.correlation_id,
                requested_at=sent.requested_at,
                deadline_at=sent.deadline_at,
            ),
            clock=lambda: NOW,
        )
        gone = client.get("/v1/identity/me", headers=owner)
        assert gone.status_code == 410, gone.text
        assert gone.json()["type"].endswith(":tenant-erased")
        assert client.get(f"{REQUESTS}/{made.json()['id']}", headers=owner).status_code == 410
