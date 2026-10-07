"""A tenant's erasure across the services, as ``cw-mvp serve`` and the worker run it.

The whole app runs in one process on its memory stores (``running_app``). A pump stands in for
the worker: it hands identity's ``tenant.deletion.requested`` to the erasure consumer of each
service (identity, profile, obligation, notification, the applicability engine and the rulebook,
each an ``IdempotentConsumer`` on a SQLite inbox with the service's memory eraser), then every
``tenant.data.erased`` they answer to identity's ``identity.erasure-records`` consumer.

Two business owners sign up, and the first has data in every service: its consent to WhatsApp
reminders, its GSTIN registration at profile, a recipient and an opt-in preference at
notification for a number the second tenant registered too, plus a number of its own, its
notifications, obligations with their history and comments, and the engine's decisions, review
item and directory entries (the last three stored as the worker's consumers would have stored
them). The first owner asks for its deletion. From then on the tenant signs nobody in.

With the flag ``identity.tenant_erasure`` on, the request completes once all six services have
answered; a count per service shows no row of the tenant left, but what each lists as retained
(the pseudonymised consents and billing customer, the erased tenant marker, the data request, the
shared number's consent without the tenant's reference, the rule-level caches, the rulebook's
regulatory data, pending events); the audit trail shows the request, identity's erasure and each
service's answer; the second tenant's data is untouched; and the owner still cannot sign in.

With the flag off, the request is recorded and the event emitted, every consumer only logs, the
data stays, and the request turns overdue after 30 days (a frozen clock), which the
DataRequestOverdue alert pages on. Nothing reaches a real identity provider, model provider or
regulator.
"""

import asyncio
from collections.abc import Callable
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
from domain_kernel.erasure import TenantDataErased, erasure_group
from domain_kernel.events import DomainEvent
from domain_kernel.ids import BusinessId, DecisionId, ObligationId, RuleVersionId, TenantId
from domain_kernel.ontology import AttributeLevel
from domain_kernel.operators import Operator
from domain_kernel.predicates import Applicability, Predicate, PredicateResult
from identity.application.erasure import DeleteProviderAccounts, RecordErasure
from identity.domain.data_requests import DataRequestKind, OpenRequests
from identity.domain.erasure import ERASURE_SERVICES, pseudonym
from identity.domain.events import TenantDeletionRequested
from identity.domain.tenancy import TenantStatus
from identity.infrastructure.erasure import MemoryIdentityEraser
from identity.infrastructure.memory import MemoryDataRequestDirectory
from identity.infrastructure.memory import MemoryStore as IdentityStore
from identity.worker import RECORDS_GROUP_ID, records_handler
from identity.worker import erasure_handler as identity_erasure
from notification.domain.notification import Notification
from notification.domain.occasions import OccasionKind
from notification.domain.repository import WorkEntry
from notification.infrastructure.erasure import MemoryNotificationEraser
from notification.infrastructure.memory import MemoryStore as NotificationStore
from obligation.infrastructure.erasure import MemoryObligationEraser
from obligation.infrastructure.memory import MemoryStore as ObligationStore
from obligation.testing import tenant_records
from profile_service.infrastructure.erasure import MemoryProfileEraser
from profile_service.infrastructure.memory import MemoryStore as ProfileStore
from py_common.erasure import EraserOn, erasure_handler
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


class Services:
    """The memory stores of the running app, by service."""

    def __init__(self, app: CombinedApp) -> None:
        def store(service: str) -> Any:
            return app.services[service].state.wiring.unit_of_work

        self.identity = store("identity")
        self.provider = app.services["identity"].state.wiring.provider
        self.profile = store("profile")
        self.obligation = store("obligation")
        self.notification = store("notification")
        self.engine = store("applicability-engine")
        self.rulebook = store("rulebook")
        assert isinstance(self.identity, IdentityStore)
        assert isinstance(self.profile, ProfileStore)
        assert isinstance(self.obligation, ObligationStore)
        assert isinstance(self.notification, NotificationStore)
        assert isinstance(self.engine, EngineStore)
        assert isinstance(self.rulebook, MemoryKnowledgeStore)
        self.rulebook_answers: list[DomainEvent] = []

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

    def remaining(self, tenant: TenantId) -> dict[str, int]:
        """The rows of the tenant each service still holds, retained tables aside."""
        identity, profile, obligation = self.identity, self.profile, self.obligation
        state, engine = self.notification.state, self.engine
        return {
            "identity": sum(u.tenant_id == tenant for u in identity.users.values())
            + sum(s.tenant_id == tenant for s in identity.subjects.values())
            + sum(
                r.tenant_id == tenant and not r.subject.startswith("erased:")
                for r in identity.records
            ),
            "profile": sum(n.tenant_id == tenant for n in profile.nodes.values())
            + sum(t.tenant_id == tenant for t in profile.tasks.values())
            + sum(v.tenant_id == tenant for v in profile.versions.values()),
            "obligation": len(obligation.of_tenant(tenant))
            + sum(c.tenant_id == tenant for c in obligation.changes)
            + sum(c.tenant_id == tenant for c in obligation.comments)
            + sum(d.tenant_id == tenant for d in obligation.decisions.values()),
            "notification": len(self.notification.notifications_of(tenant))
            + sum(row.entry.tenant_id == tenant for row in state.work.values())
            + sum(key[0] == tenant for key in state.recipients)
            + sum(key[2] == tenant for key in state.directory)
            + sum(p.set_for_tenant == tenant for p in state.preferences.values()),
            "applicability-engine": sum(d.tenant_id == tenant for d in engine.decisions.values())
            + sum(i.tenant_id == tenant for i in engine.reviews.values())
            + sum(e.tenant_id == tenant for e in engine.directory.values()),
            "rulebook": 0,
        }


def inbox(path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{path}", poolclass=NullPool)
    processed_event.create(engine)
    return engine


def record(event: DomainEvent, offset: int) -> InboundRecord:
    message = to_message(event)
    return InboundRecord(
        topic=message.topic, partition=0, offset=offset, key=b"k", value=encode(message)
    )


class Pump:
    """The worker's erasure consumers, without Kafka: each deletion request to the six
    services' consumers, then each answer to identity's records consumer."""

    def __init__(self, services: Services, tmp_path: Path, *, enabled: bool) -> None:
        self.services = services
        self.config = ConsumerConfig(max_handler_attempts=1, retry_backoff_seconds=0)
        self.producer = FakeProducer()
        on: Callable[[TenantId], bool] = lambda _: enabled  # noqa: E731
        identity_store = services.identity
        accounts = DeleteProviderAccounts(identity_store, services.provider)
        erasers: dict[str, EraserOn] = {
            "profile": lambda _: MemoryProfileEraser(services.profile),
            "obligation": lambda _: MemoryObligationEraser(services.obligation),
            "notification": lambda _: MemoryNotificationEraser(services.notification),
            "applicability-engine": lambda _: MemoryEngineEraser(services.engine),
            "rulebook": lambda _: MemoryRulebookEraser(
                services.rulebook, services.rulebook_answers
            ),
        }
        self.erasures: list[IdempotentConsumer] = [
            self.consumer(
                "identity",
                identity_erasure(
                    accounts,
                    enabled=on,
                    eraser_on=lambda _: MemoryIdentityEraser(identity_store),
                ),
                read_first_store(inbox(tmp_path / "identity.sqlite"), erasure_group("identity")),
            )
        ]
        for service, eraser_on in erasers.items():
            group = erasure_group(service)
            self.erasures.append(
                self.consumer(
                    service,
                    sync_handler(erasure_handler(service, eraser_on, enabled=on)),
                    SyncProcessedStore(inbox(tmp_path / f"{service}.sqlite"), group_id=group),
                )
            )
        self.records = IdempotentConsumer(
            group_id=RECORDS_GROUP_ID,
            store=SyncProcessedStore(inbox(tmp_path / "records.sqlite"), group_id=RECORDS_GROUP_ID),
            handler=sync_handler(
                records_handler(RecordErasure(ERASURE_SERVICES), units_on=lambda _: identity_store)
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

    def drain(self) -> list[Outcome]:
        outcomes = []
        for offset, asked in enumerate(self.services.deletions()):
            for consumer in self.erasures:
                outcomes.append(asyncio.run(consumer.process(record(asked, offset))))
        for offset, answer in enumerate(self.services.answers()):
            outcomes.append(asyncio.run(self.records.process(record(answer, offset))))
        return outcomes


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
    """What the worker's consumers store for a tenant: obligations with their history and
    comments, the engine's decisions with a review item and directory entries, and
    notifications queued for its number."""
    for index in range(2):
        records = tenant_records(tenant, WHEN + timedelta(minutes=index))
        with services.obligation(tenant) as uow:
            uow.obligations.add(records.obligation)
            for change in records.changes:
                uow.history.append(change)
            uow.comments.add(records.comment)
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


def test_with_the_flag_on_the_deletion_leaves_no_row_of_the_tenant(tmp_path: Path) -> None:
    with running_app() as app:
        public = f"http://127.0.0.1:{app.settings.mvp_public_port}"
        with (
            httpx2.Client(base_url=public, timeout=30.0) as client,
            httpx2.Client(base_url=app.settings.mvp_internal_url, timeout=30.0) as internal,
        ):
            services = Services(app)
            first, second = two_tenants(client, internal, services)
            tenant = TenantId(UUID(first["tenant"]["id"]))
            other = TenantId(UUID(second["tenant"]["id"]))
            owner = {"x-tenant-id": str(tenant)}
            assert all(
                services.remaining(tenant)[s] > 0 for s in ERASURE_SERVICES if s != "rulebook"
            )
            theirs = services.remaining(other)

            made = client.post(
                REQUESTS, json={"kind": "deletion", "reason": "Example closing"}, headers=owner
            )
            assert made.status_code == 201, made.text
            request = made.json()
            assert (request["status"], request["services_pending"]) == (
                "received",
                list(ERASURE_SERVICES),
            )
            deleting = sign_in(client, FIRST_PHONE)
            assert deleting.status_code == 403, deleting.text
            assert deleting.json()["type"].endswith(":identity-tenant-deleting")

            pump = Pump(services, tmp_path, enabled=True)
            outcomes = pump.drain()
            assert set(outcomes) == {Outcome.PROCESSED}, outcomes
            assert set(pump.drain()) == {Outcome.SKIPPED}, "a redelivery erases nothing twice"

            done = client.get(f"{REQUESTS}/{request['id']}", headers=owner).json()
            assert (done["status"], done["services_pending"], done["overdue"]) == (
                "completed",
                [],
                False,
            )
            assert done["services_done"] == list(ERASURE_SERVICES)
            assert services.remaining(tenant) == dict.fromkeys(ERASURE_SERVICES, 0)
            assert services.remaining(other) == theirs, "the other tenant keeps everything"

            answers = {answer.service: answer for answer in services.answers()}
            assert set(answers) == set(ERASURE_SERVICES)
            retained = {
                service: {item.table for item in answer.retained}
                for service, answer in answers.items()
            }
            assert {"consent_record", "billing_customer", "tenant", "data_request"} <= retained[
                "identity"
            ]
            assert "channel_preference" in retained["notification"], "the shared number's consent"
            assert "rule_version_ref" in retained["obligation"]
            assert "fanout_run" in retained["applicability-engine"]
            assert "rule_candidate" in retained["rulebook"]
            assert answers["rulebook"].tables == {}

            erased = services.identity.tenants[tenant]
            assert (erased.status, erased.name) == (TenantStatus.ERASED, "")
            (consent,) = [r for r in services.identity.records if r.tenant_id == tenant]
            assert consent.subject == pseudonym(tenant, first["user"]["id"])
            shared = services.notification.state.preferences[(Channel.WHATSAPP, FIRST_PHONE)]
            assert (shared.opted_in, shared.set_for_tenant) == (True, None)
            assert (Channel.WHATSAPP, OWN_PHONE) not in services.notification.state.preferences

            trail = client.get(
                f"{IDENTITY}/audit",
                params={"subject_type": "data_request", "subject_id": request["id"]},
                headers=owner,
            )
            assert trail.status_code == 200, trail.text
            actions = [entry["action"] for entry in trail.json()["items"]]
            assert actions.count("data_request.created") == 1
            assert actions.count("data_request.erased") == len(ERASURE_SERVICES)
            assert actions.count("data_request.completed") == 1
            erasures = client.get(
                f"{IDENTITY}/audit",
                params={"subject_type": "tenant", "subject_id": str(tenant)},
                headers=owner,
            ).json()["items"]
            assert [entry["action"] for entry in erasures] == ["tenant.erased", "tenant.created"], (
                "newest first: the audit rows stay, its creation among them"
            )
            for store in (services.profile, services.obligation, services.notification):
                assert [e.action for e in store.audit if e.action == "tenant.erased"] == [
                    "tenant.erased"
                ]
            assert services.rulebook.audit_entries("tenant.erased")

            gone = sign_in(client, FIRST_PHONE)
            assert gone.status_code == 404, gone.text
            assert gone.json()["type"].endswith(":identity-user-not-provisioned")
            assert sign_in(client, SECOND_PHONE).status_code == 200


def test_with_the_flag_off_the_request_stays_pending_and_turns_overdue(tmp_path: Path) -> None:
    with running_app() as app:
        public = f"http://127.0.0.1:{app.settings.mvp_public_port}"
        with (
            httpx2.Client(base_url=public, timeout=30.0) as client,
            httpx2.Client(base_url=app.settings.mvp_internal_url, timeout=30.0) as internal,
        ):
            services = Services(app)
            first, _ = two_tenants(client, internal, services)
            tenant = TenantId(UUID(first["tenant"]["id"]))
            owner = {"x-tenant-id": str(tenant)}
            before = services.remaining(tenant)
            made = client.post(REQUESTS, json={"kind": "deletion"}, headers=owner)
            assert made.status_code == 201, made.text
            request = made.json()
            assert len(services.deletions()) == 1, "the event is emitted"

            assert set(Pump(services, tmp_path, enabled=False).drain()) == {Outcome.PROCESSED}
            assert services.answers() == []
            assert services.remaining(tenant) == before, "every consumer only logged"
            pending = client.get(f"{REQUESTS}/{request['id']}", headers=owner).json()
            assert (pending["status"], pending["overdue"]) == ("received", False)
            assert pending["services_pending"] == list(ERASURE_SERVICES)
            assert sign_in(client, FIRST_PHONE).status_code == 403, "nobody signs in meanwhile"

            later = datetime.now(UTC) + timedelta(days=31)
            directory = MemoryDataRequestDirectory(services.identity, lambda: later)
            assert directory.open_counts()[1] == OpenRequests(DataRequestKind.DELETION, 1, 1), (
                "past its deadline the request pages through DataRequestOverdue"
            )
