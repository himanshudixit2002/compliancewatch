"""A tenant's erasure across the services, as ``cw-mvp serve`` and the worker run it.

The whole app runs in one process on its memory stores (``running_app``). A pump stands in for
the worker and its relays: it hands identity's ``tenant.deletion.requested`` events that are due
to the erasure consumer of each service (identity, profile, obligation, notification, the
applicability engine and the rulebook, each an ``IdempotentConsumer`` on a SQLite inbox with the
service's memory eraser), then every ``tenant.data.erased`` they answer to identity's
``identity.erasure-records`` consumer. Identity checks each event against its own records; every
other service checks it over HTTP with identity's ``GET /v1/identity/erasures/{tenant_id}`` on
the internal listener, as the worker does.

Two business owners sign up, and the first has data in every service: its consent to WhatsApp
reminders, its billing customer and a subscription with a checkout link, an idempotency key at
every service that keeps them, its GSTIN registration at profile, a recipient and an opt-in
preference at notification for a number the second tenant registered too, plus a number of its
own, its notifications, obligations with their history, comments and a reminder, and the
engine's decisions, review item and directory entries (the last ones stored as the worker's
consumers would have stored them). The first owner asks for its deletion. From then on the
tenant signs nobody in.

With the flag ``identity.tenant_erasure`` on, every service answers the first pass; identity
then holds the second pass back (``CW_IDENTITY_ERASURE_SECOND_PASS_SECONDS``), and once it is
due every service answers it too and the request completes. Every collection of every memory
store is then walked, whatever it is called: none holds a row of the tenant but those of a table
its service says it retained (the pseudonymised consents and billing customer, the erased tenant
and its markers, the data request, the outbox, the rule-level caches, the rulebook's regulatory
data) and the audit log, kept seven years. The audit trail shows the request, both passes and
each service's answers; the second tenant's data is untouched; the owner cannot sign in, every
service's routes answer the tenant 410, and a late obligation event queues nothing. A forged
deletion event for the second tenant erases nothing anywhere: every service refuses it and says
so in the audit log.

With the flag off, the request is recorded and the event emitted, every consumer only logs, the
data stays, and the request turns overdue after 30 days (a frozen clock), which the
DataRequestOverdue alert pages on. Nothing reaches a real identity provider, model provider or
regulator.
"""

import asyncio
import dataclasses
import json
from collections.abc import Callable, Iterator, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final
from uuid import UUID, uuid4

import httpx2
from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import NullPool

from applicability_engine.domain.directory import DirectoryEntry
from applicability_engine.domain.model import Decision, Trigger
from applicability_engine.domain.review import ReviewItem, ReviewReason
from applicability_engine.infrastructure.erasure import MemoryEngineEraser
from applicability_engine.infrastructure.memory import MemoryStore as EngineStore
from cw_mvp.app import CombinedApp
from cw_mvp.testing import running_app
from domain_kernel.channels import Channel
from domain_kernel.confidence import ZERO
from domain_kernel.dedupe import DedupeKey
from domain_kernel.erasure import ERASURE_REFUSED_ACTION, TenantDataErased, erasure_group
from domain_kernel.events import DomainEvent
from domain_kernel.ids import (
    BusinessId,
    DecisionId,
    EventId,
    ObligationId,
    RuleVersionId,
    TenantId,
)
from domain_kernel.ontology import AttributeLevel
from domain_kernel.operators import Operator
from domain_kernel.predicates import Applicability, Predicate, PredicateResult
from identity.application.erasure import CheckErasure, DeleteProviderAccounts, RecordErasure
from identity.domain.billing import Customer, Subscription, SubscriptionStatus
from identity.domain.data_requests import DataRequest, DataRequestKind, OpenRequests
from identity.domain.erasure import ERASURE_SERVICES, pseudonym
from identity.domain.events import TenantDeletionRequested
from identity.domain.tenancy import TenantStatus
from identity.infrastructure.erasure import MemoryIdentityEraser
from identity.infrastructure.memory import MemoryDataRequestDirectory
from identity.infrastructure.memory import MemoryStore as IdentityStore
from identity.settings import DEV_ERASURE_PEPPER
from identity.worker import RECORDS_GROUP_ID, records_handler
from identity.worker import erasure_handler as identity_erasure
from notification.application.enqueue import EnqueueNotifications
from notification.domain.notification import Notification
from notification.domain.occasions import OccasionKind
from notification.domain.repository import WorkEntry
from notification.infrastructure.erasure import MemoryNotificationEraser
from notification.infrastructure.memory import MemoryStore as NotificationStore
from notification.worker import GROUP_ID as NOTIFICATIONS_GROUP
from notification.worker import obligation_handler
from obligation.domain.reminders import Reminder
from obligation.infrastructure.erasure import MemoryObligationEraser
from obligation.infrastructure.memory import MemoryStore as ObligationStore
from obligation.testing import tenant_records
from profile_service.infrastructure.erasure import MemoryProfileEraser
from profile_service.infrastructure.memory import MemoryStore as ProfileStore
from py_common.erasure import (
    EraserOn,
    HttpErasureVerifier,
    MemoryErasedTenants,
    erasure_handler,
)
from py_common.events import encode, to_message
from py_common.idempotency import MemoryIdempotencyStore
from py_common.idempotency.store import IdempotencyRequest
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
from rulebook.infrastructure.erasure import MemoryRulebookEraser
from rulebook.infrastructure.memory import MemoryKnowledgeStore

IDENTITY: Final = "/v1/identity"
REQUESTS: Final = f"{IDENTITY}/data-requests"
FIRST_PHONE: Final = "+919876543250"
OWN_PHONE: Final = "+919876543251"
SECOND_PHONE: Final = "+919812345652"
GSTIN: Final = "29ABCDE1234F1Z5"
NOTICE: Final = "2000-01"
WHEN: Final = datetime(2000, 1, 3, 6, 30, tzinfo=UTC)
REGULAR: Final = Predicate("registration_type", Operator.EQ, "regular")
PEPPER: Final = DEV_ERASURE_PEPPER.encode()
SECOND_PASS: Final = timedelta(seconds=900)
EXAMPLES: Final = (
    Path(__file__).resolve().parents[4] / "packages" / "contracts" / "events" / "examples"
)
AUDIT: Final = "audit.event"
"""The audit log: never erased, its rows masked when written and kept seven years."""
TABLES: Final[Mapping[str, Mapping[str, str]]] = {
    "identity": {
        "records": "consent_record",
        "tenants": "tenant",
        "users": "app_user",
        "subjects": "user_subject",
        "service_clients": "service_client",
        "billing.customers": "billing_customer",
        "billing.subscriptions": "billing_subscription",
        "billing.events": "billing_event",
        "billing.starts": "billing_start",
        "data_requests": "data_request",
        "events": "outbox_event",
        "not_before": "outbox_event",
        "audit": AUDIT,
        "erased": "erased_tenant",
        "idempotency": "idempotency_key",
    },
    "profile": {
        "nodes": "profile_node",
        "tasks": "review_task",
        "versions": "profile_version",
        "events": "outbox_event",
        "eval_cases": "profile_node",
        "audit": AUDIT,
        "erased": "erased_tenant",
        "idempotency": "idempotency_key",
    },
    "obligation": {
        "obligations": "obligation",
        "events": "outbox_event",
        "changes": "obligation_change",
        "comments": "obligation_comment",
        "reminders": "obligation_reminder",
        "rule_versions": "rule_version_ref",
        "decisions": "obligation_decision",
        "audit": AUDIT,
        "erased": "erased_tenant",
        "idempotency": "idempotency_key",
    },
    "notification": {
        "state.preferences": "channel_preference",
        "state.inbound": "channel_preference",
        "state.suppressions": "suppression",
        "state.notifications": "notification",
        "state.work": "work_index",
        "state.recipients": "recipient",
        "state.directory": "address_directory",
        "sink.events": "outbox_event",
        "audit": AUDIT,
        "erased": "erased_tenant",
        "idempotency": "idempotency_key",
    },
    "applicability-engine": {
        "decisions": "applicability_decision",
        "directory": "business_directory",
        "reviews": "review_item",
        "events": "outbox_event",
        "audit": AUDIT,
        "fanout_runs": "fanout_run",
        "fanout_hold": "fanout_hold",
        "erased": "erased_tenant",
        "idempotency": "idempotency_key",
    },
    "rulebook": {
        "answers": "outbox_event",
        "erased": "erased_tenant",
        "_audit": AUDIT,
    },
}
"""What each collection of a service's memory store stands for: the table of its Postgres
schema. A collection that names a tenant and is not listed here fails the walk."""


def refers(value: object, tenant: TenantId, depth: int = 0) -> bool:
    """Whether ``value`` names ``tenant``: the id itself, a field ``tenant_id`` or
    ``set_for_tenant``, a key or element that does, or its text in a ``tenant_id`` item."""
    if depth > 4:
        return False
    if isinstance(value, TenantId):
        return value == tenant
    if isinstance(value, str | int | float | bool | bytes | datetime) or value is None:
        return False
    if isinstance(value, Mapping):
        if value.get("tenant_id") == str(tenant):
            return True
        return any(refers(item, tenant, depth + 1) for item in value.values())
    if isinstance(value, tuple | list | set | frozenset):
        return any(refers(item, tenant, depth + 1) for item in value)
    if dataclasses.is_dataclass(value):
        return any(
            refers(getattr(value, field.name), tenant, depth + 1)
            for field in dataclasses.fields(value)
        )
    return False


def entries(collection: object) -> list[object]:
    """The rows of a collection: a mapping's (key, value) pairs, any other's items."""
    if isinstance(collection, Mapping):
        return list(collection.items())
    if isinstance(collection, list | set | tuple | frozenset | MemoryErasedTenants):
        return list(collection)
    raise TypeError(f"not a collection: {type(collection).__name__}")


def attributes(owner: object) -> dict[str, object]:
    """An object's attributes, slots included."""
    if dataclasses.is_dataclass(owner):
        return {field.name: getattr(owner, field.name) for field in dataclasses.fields(owner)}
    return dict(vars(owner))


def collections_of(
    owner: object, prefix: str = "", seen: set[int] | None = None
) -> Iterator[tuple[str, object]]:
    """Every collection ``owner`` holds, by its attribute path, through the memory classes it
    holds (a ledger, the notification state, the event sink), each once."""
    seen = set() if seen is None else seen
    if id(owner) in seen:
        return
    seen.add(id(owner))
    for name, value in attributes(owner).items():
        path = f"{prefix}{name}"
        if isinstance(value, Mapping | list | set | tuple | frozenset | MemoryErasedTenants):
            if id(value) not in seen:
                seen.add(id(value))
                yield path, value
        elif type(value).__module__.endswith(".infrastructure.memory"):
            yield from collections_of(value, f"{path}.", seen)


class Services:
    """The memory stores of the running app, by service, with what the pump adds."""

    def __init__(self, app: CombinedApp) -> None:
        def wiring(service: str) -> Any:
            return app.services[service].state.wiring

        self.identity = wiring("identity").unit_of_work
        self.provider = wiring("identity").provider
        self.profile = wiring("profile").unit_of_work
        self.obligation = wiring("obligation").unit_of_work
        self.notification = wiring("notification").unit_of_work
        self.engine = wiring("applicability-engine").unit_of_work
        self.rulebook = wiring("rulebook").unit_of_work
        assert isinstance(self.identity, IdentityStore)
        assert isinstance(self.profile, ProfileStore)
        assert isinstance(self.obligation, ObligationStore)
        assert isinstance(self.notification, NotificationStore)
        assert isinstance(self.engine, EngineStore)
        assert isinstance(self.rulebook, MemoryKnowledgeStore)
        self.idempotency: dict[str, MemoryIdempotencyStore] = {}
        for service in (
            "identity",
            "profile",
            "obligation",
            "notification",
            "applicability-engine",
        ):
            store = wiring(service).idempotency
            assert isinstance(store, MemoryIdempotencyStore)
            self.idempotency[service] = store
        self.rulebook_answers: list[DomainEvent] = []
        self.rulebook_erased = MemoryErasedTenants()

    def stores(self) -> dict[str, object]:
        return {
            "identity": self.identity,
            "profile": self.profile,
            "obligation": self.obligation,
            "notification": self.notification,
            "applicability-engine": self.engine,
            "rulebook": self.rulebook,
        }

    def answers(self) -> list[TenantDataErased]:
        """Every tenant.data.erased the services emitted, in the order of the services."""
        events = [
            *self.identity.events,
            *self.profile.events,
            *self.obligation.events,
            *self.notification.events,
            *self.engine.events,
            *self.rulebook_answers,
        ]
        return [event for event in events if isinstance(event, TenantDataErased)]

    def deletions(self) -> list[TenantDeletionRequested]:
        return [e for e in self.identity.events if isinstance(e, TenantDeletionRequested)]

    def due(self, now: datetime) -> list[TenantDeletionRequested]:
        """The deletion requests the relay would have sent by ``now``."""
        held = self.identity.not_before
        return [e for e in self.deletions() if held.get(e.event_id.value, now) <= now]

    def walk(self, tenant: TenantId) -> dict[str, dict[str, int]]:
        """Every collection of every memory store, by service and table: how many of its rows
        name the tenant. Fails on a collection that names it and stands for no known table."""
        found: dict[str, dict[str, int]] = {}
        for service, store in self.stores().items():
            tables = TABLES[service]
            held: dict[str, int] = {}
            collections = dict(collections_of(store))
            if service == "rulebook":
                collections["answers"] = self.rulebook_answers
                collections["erased"] = self.rulebook_erased
            for path, collection in collections.items():
                rows = sum(refers(row, tenant) for row in entries(collection))
                if not rows:
                    continue
                assert path in tables, f"{service}.{path} names the tenant and stands for no table"
                held[tables[path]] = held.get(tables[path], 0) + rows
            if service in self.idempotency and self.idempotency[service].held_by(tenant):
                held[tables["idempotency"]] = self.idempotency[service].held_by(tenant)
            found[service] = held
        return found

    def left(self, tenant: TenantId) -> dict[str, dict[str, int]]:
        """What ``walk`` finds of the tenant that its services did not say they kept, nor the
        audit log."""
        kept: dict[str, set[str]] = {}
        for answer in self.answers():
            if answer.tenant_id == tenant:
                kept.setdefault(answer.service, set()).update(i.table for i in answer.retained)
        return {
            service: {
                table: rows
                for table, rows in held.items()
                if table != AUDIT and table not in kept.get(service, set())
            }
            for service, held in self.walk(tenant).items()
        }


def inbox(path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{path}", poolclass=NullPool)
    processed_event.create(engine, checkfirst=True)
    return engine


def record(event: DomainEvent, offset: int) -> InboundRecord:
    message = to_message(event)
    return InboundRecord(
        topic=message.topic, partition=0, offset=offset, key=b"k", value=encode(message)
    )


class Pump:
    """The worker's erasure consumers and relays, without Kafka: each deletion request that is
    due to the six services' consumers, then each answer to identity's records consumer."""

    def __init__(
        self, services: Services, tmp_path: Path, internal_url: str, *, enabled: bool
    ) -> None:
        self.services = services
        self.config = ConsumerConfig(max_handler_attempts=1, retry_backoff_seconds=0)
        self.producer = FakeProducer()
        self.clock = WHEN
        on: Callable[[TenantId], bool] = lambda _: enabled  # noqa: E731
        identity_store = services.identity
        verifier = HttpErasureVerifier(internal_url)
        idempotency = services.idempotency
        erasers: dict[str, EraserOn] = {
            "profile": lambda _: MemoryProfileEraser(
                services.profile, idempotency=idempotency["profile"]
            ),
            "obligation": lambda _: MemoryObligationEraser(
                services.obligation, idempotency=idempotency["obligation"]
            ),
            "notification": lambda _: MemoryNotificationEraser(
                services.notification, idempotency=idempotency["notification"]
            ),
            "applicability-engine": lambda _: MemoryEngineEraser(
                services.engine, idempotency=idempotency["applicability-engine"]
            ),
            "rulebook": lambda _: MemoryRulebookEraser(
                services.rulebook, services.rulebook_answers, services.rulebook_erased
            ),
        }
        self.erasures: list[IdempotentConsumer] = [
            self.consumer(
                "identity",
                identity_erasure(
                    DeleteProviderAccounts(identity_store, services.provider),
                    CheckErasure(identity_store),
                    enabled=on,
                    eraser_on=lambda _: MemoryIdentityEraser(
                        identity_store, pepper=PEPPER, idempotency=idempotency["identity"]
                    ),
                ),
                read_first_store(inbox(tmp_path / "identity.sqlite"), erasure_group("identity")),
            )
        ]
        for service, eraser_on in erasers.items():
            group = erasure_group(service)
            self.erasures.append(
                self.consumer(
                    service,
                    erasure_handler(service, eraser_on, enabled=on, verifier=verifier),
                    read_first_store(inbox(tmp_path / f"{service}.sqlite"), group),
                )
            )
        self.records = IdempotentConsumer(
            group_id=RECORDS_GROUP_ID,
            store=SyncProcessedStore(inbox(tmp_path / "records.sqlite"), group_id=RECORDS_GROUP_ID),
            handler=sync_handler(
                records_handler(
                    RecordErasure(
                        ERASURE_SERVICES, clock=lambda: self.clock, second_pass_after=SECOND_PASS
                    ),
                    units_on=lambda _: identity_store,
                )
            ),
            producer=self.producer,
            config=self.config,
        )

    def consumer(self, service: str, handler: Handler, store: ProcessedStore) -> IdempotentConsumer:
        return IdempotentConsumer(
            group_id=erasure_group(service),
            store=store,
            handler=handler,
            producer=self.producer,
            config=self.config,
        )

    def drain(self, *, at: datetime = WHEN) -> list[Outcome]:
        """Deliver what is due ``at``, the deletions first, then every answer."""
        self.clock = at
        outcomes = []
        for offset, asked in enumerate(self.services.due(at)):
            for consumer in self.erasures:
                outcomes.append(asyncio.run(consumer.process(record(asked, offset))))
        for offset, answer in enumerate(self.services.answers()):
            outcomes.append(asyncio.run(self.records.process(record(answer, offset))))
        return outcomes

    def deliver(self, event: DomainEvent) -> list[Outcome]:
        """One deletion event, forged or not, to every service's erasure consumer."""
        return [asyncio.run(consumer.process(record(event, 0))) for consumer in self.erasures]


def sign_up(client: httpx2.Client, phone: str, name: str) -> dict[str, Any]:
    token = client.post(f"{IDENTITY}/dev/provider-tokens", json={"phone": phone})
    assert token.status_code == 200, token.text
    created = client.post(
        f"{IDENTITY}/tenants",
        json={"kind": "business", "name": name, "provider_token": token.json()["provider_token"]},
    )
    assert created.status_code == 201, created.text
    body: dict[str, Any] = created.json()
    return body


def sign_in(client: httpx2.Client, phone: str) -> httpx2.Response:
    token = client.post(f"{IDENTITY}/dev/provider-tokens", json={"phone": phone}).json()
    return client.post(f"{IDENTITY}/sessions", json={"provider_token": token["provider_token"]})


def recipient(client: httpx2.Client, tenant: dict[str, str], *phones: str) -> None:
    answer = client.put(
        f"/v1/notification/recipients/{uuid4()}",
        json={
            "role": "owner",
            "language": "en",
            "digest_mode": "off",
            "addresses": [{"channel": "whatsapp", "address": phone} for phone in phones],
            "businesses": [],
        },
        headers=tenant,
    )
    assert answer.status_code in (200, 201), answer.text


def stock_the_stores(services: Services, tenant: TenantId) -> None:
    """What the worker's consumers and the other routes store for a tenant: obligations with
    their history, comments and a reminder, the engine's decisions with a review item and
    directory entries, notifications queued for its number, its billing customer with a
    subscription and its checkout link, and an idempotency key at every service that keeps
    them."""
    for index in range(2):
        records = tenant_records(tenant, WHEN + timedelta(minutes=index))
        with services.obligation(tenant) as uow:
            uow.obligations.add(records.obligation)
            for change in records.changes:
                uow.history.append(change)
            uow.comments.add(records.comment)
        due_at = records.obligation.due_at
        assert due_at is not None
        with services.obligation.lock:
            services.obligation.reminders.append(
                Reminder(
                    id=EventId.new(),
                    tenant_id=tenant,
                    obligation_id=records.obligation.id,
                    due_at=due_at,
                    threshold_days=7,
                    reminder_index=1,
                    sent_at=WHEN,
                )
            )
    with services.engine(tenant) as uow:
        for index in range(2):
            unsure = bool(index)
            result = Applicability.UNSURE if unsure else Applicability.APPLIES
            made = Decision(
                decision_id=DecisionId.new(),
                tenant_id=tenant,
                business_id=BusinessId.new(),
                rule_version_id=RuleVersionId.new(),
                result=result,
                confidence=ZERO,
                evaluated=(PredicateResult(REGULAR, result, ZERO, "synthetic"),),
                profile_version=1,
                decided_at=WHEN,
                trigger=Trigger.PROFILE_UPDATED,
                as_of_fy=None,
            )
            uow.decisions.add(made)
            uow.directory.add(
                DirectoryEntry(
                    tenant, made.business_id, AttributeLevel.ENTITY, None, made.business_id
                )
            )
            if unsure:
                uow.reviews.add(ReviewItem.open(made, ReviewReason.FREE_TEXT))
    for _ in range(2):
        notification = Notification.queue(
            tenant_id=tenant,
            business_id=BusinessId.new(),
            obligation_id=ObligationId.new(),
            recipient_id=None,
            channel=Channel.WHATSAPP,
            address=FIRST_PHONE,
            occasion=OccasionKind.REMINDER,
            template_key="obligation_due_soon",
            language="en",
            params={"title": "Example obligation"},
            dedupe_key=DedupeKey(uuid4().hex * 2),
            now=WHEN,
        )
        with services.notification(tenant) as unit:
            assert unit.notifications.add_if_absent(notification)
            unit.work.add(WorkEntry.of(notification))
    with services.identity(tenant) as uow:
        uow.billing.add_customer(
            Customer(tenant, "cust_example", "owner@example.org", "Example Owner"),
            provider="memory",
            at=WHEN,
        )
        uow.billing.add_subscription(
            Subscription(
                tenant_id=tenant,
                plan_key="owner_monthly",
                provider_subscription_id="sub_example",
                status=SubscriptionStatus.CREATED,
                started_at=WHEN,
                checkout_url="https://checkout.example.org/sub_example",
            )
        )
    for store in services.idempotency.values():
        store.begin(tenant, IdempotencyRequest("Example-Key-1", "POST", "/x", "0" * 64))


def two_tenants(
    client: httpx2.Client, internal: httpx2.Client, services: Services
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Two owners signed up; the first with data in every service, the second with a little,
    sharing the first's number."""
    first = sign_up(client, FIRST_PHONE, "Example Traders")
    second = sign_up(client, SECOND_PHONE, "Example Stores")
    owner = {"x-tenant-id": first["tenant"]["id"]}
    other = {"x-tenant-id": second["tenant"]["id"]}
    consent = client.post(
        f"{IDENTITY}/consents",
        json={
            "subject": first["user"]["id"],
            "purpose": "whatsapp_reminders",
            "granted": True,
            "source": "web_onboarding",
            "notice_version": NOTICE,
            "evidence": "Example onboarding checkbox",
        },
        headers=owner,
    )
    assert consent.status_code == 201, consent.text
    registered = client.post(
        "/v1/profile/registrations",
        json={"gstin": GSTIN, "name": "Example Traders Bengaluru", "entity_name": "Example"},
        headers=owner,
    )
    assert registered.status_code in (200, 201), registered.text
    recipient(client, owner, FIRST_PHONE, OWN_PHONE)
    recipient(client, other, FIRST_PHONE)
    opted = internal.put(
        f"/v1/notification/preferences/whatsapp/{FIRST_PHONE}",
        json={"opted_in": True, "source": "web_onboarding", "subject": first["user"]["id"]},
        headers=owner,
    )
    assert opted.status_code == 200, opted.text
    stock_the_stores(services, TenantId(UUID(first["tenant"]["id"])))
    return first, second


def without(found: dict[str, dict[str, int]], *tables: str) -> dict[str, dict[str, int]]:
    return {
        service: {table: rows for table, rows in held.items() if table not in tables}
        for service, held in found.items()
    }


def request_of(services: Services, tenant: TenantId, request_id: str) -> DataRequest:
    found: list[DataRequest] = [
        r for r in services.identity.data_requests.values() if str(r.id) == request_id
    ]
    (request,) = found
    assert request.tenant_id == tenant
    return request


def late_obligation_event(services: Services, tenant: TenantId, tmp_path: Path) -> Outcome:
    """An obligation.created of the tenant that was still in flight, to notification's
    consumer, with the store's markers as the worker reads them on Postgres."""
    store = services.notification
    handler = obligation_handler(
        EnqueueNotifications(store),
        unit_on=lambda _, tenant_id: store(tenant_id),
        erased_on=lambda _: store.erased,
    )
    consumer = IdempotentConsumer(
        group_id=NOTIFICATIONS_GROUP,
        store=SyncProcessedStore(inbox(tmp_path / "late.sqlite"), group_id=NOTIFICATIONS_GROUP),
        handler=sync_handler(handler),
        producer=FakeProducer(),
        config=ConsumerConfig(max_handler_attempts=1, retry_backoff_seconds=0),
    )
    message = json.loads(
        (EXAMPLES / "obligation.created" / "filing-with-due-date.json").read_text("utf-8")
    )
    message.update(tenant_id=str(tenant), event_id=str(uuid4()))
    late = InboundRecord(
        topic="obligation.created",
        partition=0,
        offset=0,
        key=b"k",
        value=json.dumps(message).encode(),
    )
    return asyncio.run(consumer.process(late))


def test_with_the_flag_on_the_deletion_leaves_no_row_of_the_tenant(tmp_path: Path) -> None:
    with running_app() as app:
        public = f"http://127.0.0.1:{app.settings.mvp_public_port}"
        internal_url = app.settings.mvp_internal_url
        with (
            httpx2.Client(base_url=public, timeout=30.0) as client,
            httpx2.Client(base_url=internal_url, timeout=30.0) as internal,
        ):
            services = Services(app)
            first, second = two_tenants(client, internal, services)
            tenant = TenantId(UUID(first["tenant"]["id"]))
            other = TenantId(UUID(second["tenant"]["id"]))
            owner = {"x-tenant-id": str(tenant)}
            stocked = services.walk(tenant)
            for service, tables in {
                "identity": {"app_user", "billing_customer", "idempotency_key"},
                "profile": {"profile_node", "idempotency_key"},
                "obligation": {"obligation", "obligation_reminder", "idempotency_key"},
                "notification": {"notification", "work_index", "channel_preference"},
                "applicability-engine": {"applicability_decision", "review_item"},
            }.items():
                assert tables <= set(stocked[service]), (service, stocked[service])
            theirs = services.walk(other)

            made = client.post(
                REQUESTS, json={"kind": "deletion", "reason": "Example closing"}, headers=owner
            )
            assert made.status_code == 201, made.text
            request = made.json()
            assert (request["status"], request["services_pending"], request["erasure_pass"]) == (
                "received",
                list(ERASURE_SERVICES),
                1,
            )
            deleting = sign_in(client, FIRST_PHONE)
            assert deleting.status_code == 403, deleting.text
            assert deleting.json()["type"].endswith(":identity-tenant-deleting")

            pump = Pump(services, tmp_path, internal_url, enabled=True)
            forged = TenantDeletionRequested(
                tenant_id=other,
                requested_by=None,
                requested_at=WHEN,
                deadline_at=WHEN + timedelta(days=30),
            )
            assert set(pump.deliver(forged)) == {Outcome.REFUSED}, "nobody asked for it"
            refusals = [
                *services.identity.audit,
                *services.profile.audit,
                *services.obligation.audit,
                *services.notification.audit,
                *services.engine.audit,
                *services.rulebook.audit_entries(),
            ]
            assert sorted(
                entry.actor.label for entry in refusals if entry.action == ERASURE_REFUSED_ACTION
            ) == sorted(f"system:{service}" for service in ERASURE_SERVICES), "each says so"
            assert without(services.walk(other), AUDIT) == without(theirs, AUDIT), (
                "a forged event erases nothing"
            )

            assert set(pump.drain()) == {Outcome.PROCESSED}
            assert set(pump.drain()) == {Outcome.SKIPPED}, "a redelivery erases nothing twice"
            waiting = request_of(services, tenant, request["id"])
            assert (waiting.status.value, waiting.erasure_pass) == ("in_progress", 2)
            assert waiting.services_done == ERASURE_SERVICES
            assert waiting.second_pass_at == WHEN + SECOND_PASS, "held back for the second pass"
            assert len(services.due(WHEN)) == 1, "not sent before it is due"

            later = WHEN + SECOND_PASS
            assert set(pump.drain(at=later)) == {Outcome.PROCESSED, Outcome.SKIPPED}
            done = request_of(services, tenant, request["id"])
            assert (done.status.value, done.completed_at, done.second_pass_done) == (
                "completed",
                later,
                ERASURE_SERVICES,
            )
            assert services.left(tenant) == {service: {} for service in TABLES}, (
                "no row of the tenant is left but what its services retained"
            )
            assert without(services.walk(other), AUDIT) == without(theirs, AUDIT), (
                "the other tenant keeps everything"
            )

            answers = {(answer.service, answer.deletion_event_id) for answer in services.answers()}
            assert len(answers) == 2 * len(ERASURE_SERVICES), "each service answered both passes"
            retained: dict[str, set[str]] = {}
            for answer in services.answers():
                retained.setdefault(answer.service, set()).update(i.table for i in answer.retained)
            assert {"consent_record", "billing_customer", "tenant", "data_request"} <= retained[
                "identity"
            ]
            assert all("erased_tenant" in tables for tables in retained.values())
            assert "channel_preference" in retained["notification"], "the shared number's consent"
            assert "rule_version_ref" in retained["obligation"]
            assert "fanout_run" in retained["applicability-engine"]
            assert "rule_candidate" in retained["rulebook"]

            erased = services.identity.tenants[tenant]
            assert (erased.status, erased.name) == (TenantStatus.ERASED, "")
            (consent,) = [r for r in services.identity.records if r.tenant_id == tenant]
            assert consent.subject == pseudonym(tenant, first["user"]["id"], PEPPER)
            assert services.identity.billing.subscriptions["sub_example"].checkout_url == ""
            shared = services.notification.state.preferences[(Channel.WHATSAPP, FIRST_PHONE)]
            assert (shared.opted_in, shared.set_for_tenant) == (True, None)
            assert (Channel.WHATSAPP, OWN_PHONE) not in services.notification.state.preferences

            trail = [e.action for e in services.identity.audit if e.subject_id == request["id"]]
            assert trail.count("data_request.created") == 1
            assert trail.count("data_request.erased") == 2 * len(ERASURE_SERVICES)
            assert trail.count("data_request.second_pass_scheduled") == 1
            assert trail.count("data_request.completed") == 1
            for store in (services.profile, services.obligation, services.notification):
                assert [e.action for e in store.audit if e.action == "tenant.erased"] == [
                    "tenant.erased"
                ] * 2, "one per pass"
            assert services.rulebook.audit_entries("tenant.erased")

            gone = sign_in(client, FIRST_PHONE)
            assert gone.status_code == 404, gone.text
            assert gone.json()["type"].endswith(":identity-user-not-provisioned")
            assert sign_in(client, SECOND_PHONE).status_code == 200
            for path in (
                f"{REQUESTS}/{request['id']}",
                "/v1/businesses",
                "/v1/obligation/obligations",
                "/v1/notification/notifications",
                f"/v1/applicability-engine/businesses/{uuid4()}/decisions",
            ):
                answered = client.get(path, headers=owner)
                assert answered.status_code == 410, (path, answered.text)
                assert answered.json()["type"].endswith(":tenant-erased")
            assert late_obligation_event(services, tenant, tmp_path) is Outcome.PROCESSED
            assert services.left(tenant)["notification"] == {}, "a late event queues nothing"


def test_with_the_flag_off_the_request_stays_pending_and_turns_overdue(tmp_path: Path) -> None:
    with running_app() as app:
        public = f"http://127.0.0.1:{app.settings.mvp_public_port}"
        internal_url = app.settings.mvp_internal_url
        with (
            httpx2.Client(base_url=public, timeout=30.0) as client,
            httpx2.Client(base_url=internal_url, timeout=30.0) as internal,
        ):
            services = Services(app)
            first, _ = two_tenants(client, internal, services)
            tenant = TenantId(UUID(first["tenant"]["id"]))
            owner = {"x-tenant-id": str(tenant)}
            before = services.walk(tenant)
            made = client.post(REQUESTS, json={"kind": "deletion"}, headers=owner)
            assert made.status_code == 201, made.text
            request = made.json()
            assert len(services.deletions()) == 1, "the event is emitted"

            pump = Pump(services, tmp_path, internal_url, enabled=False)
            assert set(pump.drain()) == {Outcome.PROCESSED}
            assert services.answers() == []
            what_the_request_adds = (AUDIT, "data_request", "outbox_event")
            assert without(services.walk(tenant), *what_the_request_adds) == without(
                before, *what_the_request_adds
            ), "every consumer only logged"
            pending = client.get(f"{REQUESTS}/{request['id']}", headers=owner).json()
            assert (pending["status"], pending["overdue"]) == ("received", False)
            assert pending["services_pending"] == list(ERASURE_SERVICES)
            assert sign_in(client, FIRST_PHONE).status_code == 403, "nobody signs in meanwhile"

            later = datetime.now(UTC) + timedelta(days=31)
            directory = MemoryDataRequestDirectory(services.identity, lambda: later)
            assert directory.open_counts()[1] == OpenRequests(DataRequestKind.DELETION, 1, 1), (
                "past its deadline the request pages through DataRequestOverdue"
            )
