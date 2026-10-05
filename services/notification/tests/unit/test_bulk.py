"""A CA firm's bulk notification, ``POST /v1/notification/bulk``, on the memory store: one change
card per client recipient and business, the firm's own people left to their digest, the dedupe
against the cards the change made and an earlier request, the Idempotency-Key, the flag, the
audit entry, the tenant's own businesses only, and the roles in token mode."""

from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain_kernel.access import Role, Scope
from domain_kernel.audit import AuditActor
from domain_kernel.channels import Channel
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import BusinessId, ObligationId, RuleVersionId, TenantId, UserId
from notification.application.bulk import (
    BULK_ACTION,
    MAX_BUSINESSES,
    BulkOutcome,
    BulkRequest,
    client_recipient,
)
from notification.application.recipients import RecipientRegistration
from notification.domain.ids import RecipientId
from notification.domain.notification import DeliveryState
from notification.domain.occasions import Occasion, OccasionKind
from notification.domain.ports import OpenObligation
from notification.domain.preferences import ConsentSource
from notification.domain.recipients import BusinessLink, Recipient, RecipientRole
from notification.domain.routing import ObligationNotice
from notification.infrastructure.memory import MemoryStore
from notification.main import build_app
from notification.testing import FakeObligationReader, notification_settings
from py_common.auth.testing import TestIssuer, bearer
from py_common.idempotency.fastapi import REPLAYED_HEADER
from py_common.settings import AuthMode

ISSUER = TestIssuer()
WA, EMAIL = Channel.WHATSAPP, Channel.EMAIL
BULK = "/v1/notification/bulk"
FIRM = TenantId(UUID("00000000-0000-4000-8000-00000000ca01"))
OTHER = TenantId(UUID("00000000-0000-4000-8000-00000000ca02"))
CHANGE = RuleVersionId(UUID(int=0xC4A))
TOLD = BusinessId(UUID(int=0xA1))
"""A client with its owner and its staff as recipients."""
FIRM_ONLY = BusinessId(UUID(int=0xA2))
"""A client only the firm's admin follows."""
UNAFFECTED = BusinessId(UUID(int=0xA3))
"""A client the change asks nothing of."""
SILENT = BusinessId(UUID(int=0xA4))
"""A client whose owner never opted in."""
DUE = datetime(2026, 12, 31, 18, 29, 59, tzinfo=UTC)
OWNER_PHONE = "+910000000101"
STAFF_EMAIL = "staff@example-client.invalid"
ADMIN_PHONE = "+910000000102"
SILENT_PHONE = "+910000000103"


def obligation(business: BusinessId, *, due_at: datetime | None = DUE) -> OpenObligation:
    return OpenObligation(
        obligation_id=ObligationId.new(),
        business_id=business,
        rule_version_id=CHANGE,
        title="File the annual return for the year (synthetic)",
        steps=("Reconcile the year", "File the annual return"),
        due_at=due_at,
    )


class Api:
    """The service on its memory store with the bulk flag on, a firm with four clients, and the
    obligation service's open obligations of the change for three of them."""

    def __init__(self, mode: AuthMode = "header", *, enabled: bool = True) -> None:
        self.obligations = FakeObligationReader()
        self.first = self.obligations.add(FIRM, obligation(TOLD))
        self.obligations.add(FIRM, obligation(TOLD, due_at=None))
        self.obligations.add(FIRM, obligation(FIRM_ONLY))
        self.obligations.add(FIRM, obligation(SILENT))
        settings = notification_settings(
            notification_bulk_enabled=enabled, **ISSUER.settings_overrides(mode)
        )
        self.app: FastAPI = build_app(settings, obligations=self.obligations)
        self.client = TestClient(self.app)
        self.owner = self.register(RecipientRole.OWNER, [(WA, OWNER_PHONE)], [TOLD])
        self.staff = self.register(RecipientRole.STAFF, [(EMAIL, STAFF_EMAIL)], [TOLD])
        self.admin = self.register(
            RecipientRole.CA_ADMIN, [(WA, ADMIN_PHONE)], [TOLD, FIRM_ONLY, SILENT]
        )
        self.silent = self.register(
            RecipientRole.OWNER, [(WA, SILENT_PHONE)], [SILENT], opt_in=False
        )

    def register(
        self,
        role: RecipientRole,
        addresses: list[tuple[Channel, str]],
        businesses: list[BusinessId],
        *,
        opt_in: bool = True,
    ) -> str:
        """A recipient of the firm, through the use cases, so it works in every mode."""
        recipient = RecipientId.new()
        wiring = self.app.state.wiring
        wiring.register_recipient.run(
            RecipientRegistration(
                tenant_id=FIRM,
                recipient_id=recipient,
                role=role,
                addresses=addresses,
                businesses=[BusinessLink(business) for business in businesses],
            )
        )
        for channel, address in addresses if opt_in else ():
            wiring.set_opt_in.run(channel, address, opted_in=True, source=ConsentSource.API)
        return str(recipient)

    @property
    def store(self) -> MemoryStore:
        store = self.app.state.wiring.unit_of_work
        assert isinstance(store, MemoryStore)
        return store

    def bulk(
        self,
        businesses: list[BusinessId],
        *,
        key: str | None = "bulk-test-key-1",
        headers: dict[str, str] | None = None,
        **body: Any,
    ) -> Any:
        sent = {
            "rule_version_id": str(CHANGE),
            "business_ids": [str(business) for business in businesses],
            "kind": "change_card",
            **body,
        }
        given = {"x-tenant-id": str(FIRM)} if headers is None else dict(headers)
        if key is not None:
            given["Idempotency-Key"] = key
        return self.client.post(BULK, json=sent, headers=given)

    def cards(self) -> list[Any]:
        return [
            n for n in self.store.notifications_of(FIRM) if n.occasion is OccasionKind.CHANGE_CARD
        ]


@pytest.fixture
def api() -> Iterator[Api]:
    served = Api()
    with served.client:
        yield served


def problem(response: Any) -> str:
    kind: str = response.json()["type"]
    return kind.rsplit(":", 1)[-1]


def outcomes(response: Any) -> dict[str, str]:
    return {item["business_id"]: item["outcome"] for item in response.json()["businesses"]}


def test_each_client_person_gets_one_card_and_the_firm_is_left_to_its_digest(api: Api) -> None:
    response = api.bulk([TOLD, FIRM_ONLY, UNAFFECTED, SILENT])
    assert response.status_code == 201, response.text
    body = response.json()
    assert (
        body["queued"],
        body["skipped_duplicate"],
        body["skipped_no_recipient"],
        body["skipped_not_affected"],
        body["notifications_queued"],
    ) == (1, 0, 2, 1, 2)
    assert outcomes(response) == {
        str(TOLD): "queued",
        str(FIRM_ONLY): "no_recipient",
        str(UNAFFECTED): "not_affected",
        str(SILENT): "no_recipient",
    }
    told = body["businesses"][0]
    assert (told["obligation_id"], told["queued"], told["duplicates"], told["unreachable"]) == (
        str(api.first.obligation_id),
        2,
        0,
        0,
    )
    assert body["businesses"][3]["unreachable"] == 1
    assert body["businesses"][2]["obligation_id"] is None
    cards = api.cards()
    assert {str(card.recipient_id) for card in cards} == {api.owner, api.staff}
    for card in cards:
        assert (card.template_key, card.business_id, card.obligation_id) == (
            "change_card",
            TOLD,
            api.first.obligation_id,
        )
        assert card.state is DeliveryState.QUEUED
        assert dict(card.params) == {
            "title": api.first.title,
            "steps": list(api.first.steps),
            "due_at": DUE.isoformat(),
            "rule_version_id": str(CHANGE),
        }
    assert {card.channel.value for card in cards} == {"whatsapp", "email"}


def test_a_replay_answers_the_same_and_a_new_key_finds_every_card_queued(api: Api) -> None:
    first = api.bulk([TOLD, UNAFFECTED])
    replay = api.bulk([TOLD, UNAFFECTED])
    again = api.bulk([TOLD, UNAFFECTED], key="bulk-test-key-2")
    assert first.status_code == replay.status_code == again.status_code == 201
    assert replay.json() == first.json()
    assert replay.headers[REPLAYED_HEADER] == "true"
    assert REPLAYED_HEADER not in again.headers
    assert (again.json()["queued"], again.json()["skipped_duplicate"]) == (0, 1)
    assert again.json()["notifications_queued"] == 0
    assert again.json()["businesses"][0]["duplicates"] == 2
    assert len(api.cards()) == 2, "one change, one card per person and business"
    entries = [entry for entry in api.store.audit if entry.action == BULK_ACTION]
    assert len(entries) == 2, "the replay ran nothing"
    entry = entries[0]
    assert (entry.tenant_id, entry.subject_type, entry.subject_id) == (
        FIRM,
        "rule_version",
        str(CHANGE),
    )
    assert entry.actor == AuditActor.system("notification"), "no token, no person"
    after = dict(entry.after or {})
    assert {key: after[key] for key in ("kind", "businesses", "queued", "not_affected")} == {
        "kind": "change_card",
        "businesses": 2,
        "queued": 1,
        "not_affected": 1,
    }
    assert after["notifications_queued"] == 2
    outcomes_by_kind = after["outcomes"]
    assert isinstance(outcomes_by_kind, Mapping)
    assert outcomes_by_kind["queued"] == (str(TOLD),)
    assert dict(entries[1].after or {})["duplicate"] == 1


def test_the_card_the_change_made_counts_as_sent(api: Api) -> None:
    """The change card obligation.created queued for the owner has the key a bulk card would."""
    with api.store(FIRM) as unit:
        api.app.state.wiring.enqueue.run_in(
            unit,
            ObligationNotice(
                tenant_id=FIRM,
                business_id=TOLD,
                occasion=Occasion.change_card(ObligationId.new(), CHANGE),
                template_key="change_card",
                params={"title": "Example title (synthetic)", "rule_version_id": str(CHANGE)},
            ),
        )
    made = len(api.cards())
    assert made == 3, "the change's own card reaches the firm's admin too"
    response = api.bulk([TOLD])
    told = response.json()["businesses"][0]
    assert (told["outcome"], told["queued"], told["duplicates"]) == ("duplicate", 0, 2)
    assert len(api.cards()) == made


def test_a_key_reused_with_another_body_is_422_and_none_is_428(api: Api) -> None:
    assert api.bulk([TOLD]).status_code == 201
    reused = api.bulk([TOLD, SILENT])
    missing = api.bulk([TOLD], key=None)
    assert (reused.status_code, problem(reused)) == (422, "idempotency-key-reused")
    assert (missing.status_code, problem(missing)) == (428, "idempotency-key-required")


@pytest.mark.parametrize(
    "body",
    [
        {"business_ids": []},
        {"business_ids": [str(TOLD), str(TOLD)]},
        {"business_ids": [str(uuid4()) for _ in range(MAX_BUSINESSES + 1)]},
        {"kind": "reminder"},
        {"business_ids": [str(TOLD)], "message": "free text"},
    ],
)
def test_a_request_that_names_no_business_or_one_twice_is_422(
    api: Api, body: dict[str, Any]
) -> None:
    response = api.bulk([TOLD], key=f"bulk-invalid-{len(str(body))}", **body)
    assert (response.status_code, problem(response)) == (422, "request-invalid")
    assert api.cards() == []


def test_off_the_flag_refuses_before_the_key_and_queues_nothing() -> None:
    api = Api(enabled=False)
    with api.client:
        refused = api.bulk([TOLD])
    assert (refused.status_code, problem(refused)) == (503, "notification-bulk-disabled")
    assert api.cards() == []
    assert api.obligations.asked == []


def test_an_obligation_service_outage_is_503_and_a_retry_runs(api: Api) -> None:
    api.obligations.down = True
    down = api.bulk([TOLD])
    api.obligations.down = False
    retried = api.bulk([TOLD])
    assert (down.status_code, problem(down)) == (503, "notification-dependency-unavailable")
    assert retried.status_code == 201, "the key was released"
    assert REPLAYED_HEADER not in retried.headers
    assert retried.json()["queued"] == 1


def test_another_tenant_tells_no_one_of_the_firms_clients(api: Api) -> None:
    response = api.bulk([TOLD, FIRM_ONLY], headers={"x-tenant-id": str(OTHER)})
    assert response.status_code == 201, response.text
    assert set(outcomes(response).values()) == {"not_affected"}
    assert api.cards() == []
    assert {tenant for tenant, _, _ in api.obligations.asked} == {OTHER}
    missing = api.bulk([TOLD], headers={})
    assert (missing.status_code, problem(missing)) == (401, "notification-tenant-required")


def test_the_spec_lists_the_ca_roles_the_key_and_201(api: Api) -> None:
    spec = api.client.get("/openapi.json").json()
    operation = spec["paths"][BULK]["post"]
    assert operation["tags"] == ["public", "notifications"]
    assert operation["x-roles"] == ["ca_admin", "ca_staff"]
    (key,) = [p for p in operation["parameters"] if p["name"] == "Idempotency-Key"]
    assert key["required"] is True
    assert {"201", "401", "403", "409", "422", "428", "503"} <= set(operation["responses"])


def test_in_token_mode_only_the_firms_people_send() -> None:
    api = Api("token")
    admin = bearer(ISSUER.user(FIRM, [Role.CA_ADMIN], user_id=UserId(UUID(int=0xAD))))
    staff = bearer(ISSUER.user(FIRM, [Role.CA_STAFF]))
    owner = bearer(ISSUER.user(FIRM, [Role.OWNER]))
    acting = bearer(ISSUER.service("worker", [Scope.TENANT_ACT, Scope.NOTIFICATION_SEND]))
    with api.client:
        sent = api.bulk([TOLD], headers=admin)
        by_staff = api.bulk([TOLD], key="bulk-token-staff", headers=staff)
        refused = api.bulk([TOLD], key="bulk-token-owner", headers=owner)
        service = api.bulk(
            [TOLD], key="bulk-token-service", headers={**acting, "x-tenant-id": str(FIRM)}
        )
        anonymous = api.bulk([TOLD], key="bulk-token-none")
    assert sent.status_code == 201, sent.text
    assert by_staff.status_code == 201
    assert by_staff.json()["skipped_duplicate"] == 1
    assert (refused.status_code, problem(refused)) == (403, "auth-forbidden")
    assert (service.status_code, problem(service)) == (403, "auth-forbidden")
    assert (anonymous.status_code, problem(anonymous)) == (401, "auth-token-required")
    by_admin, by_ca_staff = [e for e in api.store.audit if e.action == BULK_ACTION]
    assert by_admin.actor == AuditActor.user(UserId(UUID(int=0xAD)), [Role.CA_ADMIN])
    assert by_ca_staff.actor.label == "ca_staff"


# ---------------------------------------------------------------- the use case's pieces


def test_a_client_recipient_is_one_of_the_clients_own_people() -> None:
    now = datetime(2026, 10, 6, tzinfo=UTC)

    def person(role: RecipientRole) -> Recipient:
        return Recipient(
            id=RecipientId.new(),
            tenant_id=FIRM,
            user_id=None,
            role=role,
            created_at=now,
            updated_at=now,
        )

    assert [client_recipient(person(role)) for role in RecipientRole] == [
        True,
        True,
        False,
        False,
    ]


def test_a_request_names_one_to_five_hundred_businesses_once_each() -> None:
    actor = AuditActor.system("notification")
    with pytest.raises(InvariantViolationError, match="1 to 500"):
        BulkRequest(FIRM, CHANGE, (), actor)
    with pytest.raises(InvariantViolationError, match="twice"):
        BulkRequest(FIRM, CHANGE, (TOLD, TOLD), actor)
    request = BulkRequest(FIRM, CHANGE, (TOLD, SILENT), actor)
    assert request.business_ids == (TOLD, SILENT)
    assert [outcome.value for outcome in BulkOutcome] == [
        "queued",
        "duplicate",
        "no_recipient",
        "not_affected",
    ]
