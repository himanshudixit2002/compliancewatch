"""A CA firm's bulk notification on Postgres, through a role that owns nothing and is not a
superuser, so row-level security holds as in a deployment. Needs Docker.

- the route queues one change card per client recipient, answers a retry with the same key with
  its first answer, and finds every card queued already under a new key, with one
  ``notification.bulk`` audit row of the firm per request that ran, in the request's transaction;
- the card the change itself made counts: the bulk queues nothing more for that person;
- another tenant naming the firm's client queues nothing, reads none of its notifications, and its
  Idempotency-Key of the same text is a key of its own.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from testcontainers.community.postgres import PostgresContainer

from domain_kernel.channels import Channel
from domain_kernel.ids import BusinessId, ObligationId, RuleVersionId, TenantId
from notification.application.bulk import BULK_ACTION
from notification.application.recipients import RecipientRegistration
from notification.domain.ids import RecipientId
from notification.domain.occasions import Occasion
from notification.domain.ports import OpenObligation
from notification.domain.preferences import ConsentSource
from notification.domain.recipients import BusinessLink, RecipientRole
from notification.domain.routing import ObligationNotice
from notification.main import build_app
from notification.testing import FakeObligationReader, notification_settings
from py_common.audit.schema import AUDIT_SCHEMA, QUALIFIED_TABLE
from py_common.audit.testing import install_audit_table, read_audit_entries
from py_common.idempotency.fastapi import REPLAYED_HEADER

pytestmark = pytest.mark.integration

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "notification"
APP_ROLE = "notification_bulk_app"
APP_PASSWORD = "bulk-role-for-tests"
FIRM = TenantId(UUID("00000000-0000-4000-8000-00000000cb01"))
OTHER = TenantId(UUID("00000000-0000-4000-8000-00000000cb02"))
CHANGE = RuleVersionId(UUID(int=0xCB0))
CLIENT = BusinessId(UUID(int=0xCB1))
DUE = datetime(2026, 12, 31, 18, 29, 59, tzinfo=UTC)
OWNER_PHONE = "+910000000201"
STAFF_EMAIL = "staff@example-client-two.invalid"
ADMIN_PHONE = "+910000000202"
FIRST = "bulk-integration-1"
"""The Idempotency-Key of the firm's first request, sent by the other tenant too."""


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    with PostgresContainer(IMAGE, driver="psycopg") as postgres:
        base_url = postgres.get_connection_url()
        admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
            connection.execute(text(f"CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{APP_PASSWORD}'"))
            connection.execute(text(f"GRANT USAGE ON SCHEMA {SCHEMA} TO {APP_ROLE}"))
            connection.execute(
                text(
                    f"ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA} "
                    f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}"
                )
            )
        admin.dispose()
        yield f"{base_url}?options=-csearch_path%3D{SCHEMA}%2Cpublic"


@pytest.fixture(scope="module")
def engine(database_url: str) -> Iterator[Engine]:
    """The owner's engine, after the migrations and the audit table identity's migration makes."""
    with pytest.MonkeyPatch.context() as env:
        env.setenv("CW_DATABASE_URL", database_url)
        env.setenv("CW_DB_SCHEMA", SCHEMA)
        command.upgrade(Config(str(SERVICE_DIR / "alembic.ini")), "head")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        install_audit_table(connection)
        connection.execute(text(f"GRANT USAGE ON SCHEMA {AUDIT_SCHEMA} TO {APP_ROLE}"))
        connection.execute(
            text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {QUALIFIED_TABLE} TO {APP_ROLE}")
        )
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def reader() -> FakeObligationReader:
    obligations = FakeObligationReader()
    obligations.add(
        FIRM,
        OpenObligation(
            obligation_id=ObligationId(UUID(int=0xCB2)),
            business_id=CLIENT,
            rule_version_id=CHANGE,
            title="File the annual return (synthetic)",
            steps=("Reconcile the year", "File the annual return"),
            due_at=DUE,
        ),
    )
    return obligations


@pytest.fixture(scope="module")
def client(database_url: str, engine: Engine, reader: FakeObligationReader) -> Iterator[TestClient]:
    """The service as the app role, with the bulk flag on, the firm's client followed by its
    owner and staff and by the firm's admin."""
    settings = notification_settings(
        notification_store="postgres",
        database_url=database_url.replace("test:test@", f"{APP_ROLE}:{APP_PASSWORD}@"),
        db_schema=SCHEMA,
        notification_bulk_enabled=True,
    )
    app = build_app(settings, obligations=reader)
    wiring = app.state.wiring
    for role, channel, address in (
        (RecipientRole.OWNER, Channel.WHATSAPP, OWNER_PHONE),
        (RecipientRole.STAFF, Channel.EMAIL, STAFF_EMAIL),
        (RecipientRole.CA_ADMIN, Channel.WHATSAPP, ADMIN_PHONE),
    ):
        wiring.register_recipient.run(
            RecipientRegistration(
                tenant_id=FIRM,
                recipient_id=RecipientId.new(),
                role=role,
                addresses=[(channel, address)],
                businesses=[BusinessLink(CLIENT)],
            )
        )
        wiring.set_opt_in.run(channel, address, opted_in=True, source=ConsentSource.API)
    with TestClient(app) as served:
        yield served


def bulk(client: TestClient, tenant: TenantId, key: str) -> Any:
    return client.post(
        "/v1/notification/bulk",
        json={"rule_version_id": str(CHANGE), "business_ids": [str(CLIENT)], "kind": "change_card"},
        headers={"x-tenant-id": str(tenant), "Idempotency-Key": key},
    )


def cards(engine: Engine, tenant: TenantId) -> list[Any]:
    """The change cards of the tenant, read as the owner, past row-level security."""
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT recipient_id, channel, state FROM notification "
                    "WHERE tenant_id = :tenant AND occasion = 'change_card' ORDER BY channel"
                ),
                {"tenant": tenant.value},
            )
        )


def test_a_replay_answers_the_same_and_a_new_key_finds_the_cards_queued(
    client: TestClient, engine: Engine
) -> None:
    first = bulk(client, FIRM, FIRST)
    replay = bulk(client, FIRM, FIRST)
    again = bulk(client, FIRM, "bulk-integration-2")
    assert first.status_code == 201, first.text
    body = first.json()
    assert (body["queued"], body["notifications_queued"], body["skipped_duplicate"]) == (1, 2, 0)
    assert replay.json() == body
    assert replay.headers[REPLAYED_HEADER] == "true"
    assert again.status_code == 201
    assert (again.json()["skipped_duplicate"], again.json()["notifications_queued"]) == (1, 0)
    queued = cards(engine, FIRM)
    assert [(row.channel, row.state) for row in queued] == [
        ("email", "queued"),
        ("whatsapp", "queued"),
    ], "the client's owner and staff; the firm's admin hears in the digest"
    with engine.connect() as connection:
        entries = [
            entry
            for entry in read_audit_entries(connection, action=BULK_ACTION)
            if entry.tenant_id == FIRM
        ]
    assert len(entries) == 2, "one row per request that ran; the replay ran nothing"
    assert [dict(entry.after or {})["notifications_queued"] for entry in entries] == [2, 0]
    assert {entry.subject_id for entry in entries} == {str(CHANGE)}


def test_another_tenant_queues_nothing_reads_nothing_and_keeps_its_own_keys(
    client: TestClient, engine: Engine
) -> None:
    before = cards(engine, FIRM)
    theirs = bulk(client, OTHER, FIRST)
    assert theirs.status_code == 201, theirs.text
    assert REPLAYED_HEADER not in theirs.headers, "the firm's key of that text is not theirs"
    assert (theirs.json()["skipped_not_affected"], theirs.json()["notifications_queued"]) == (1, 0)
    assert cards(engine, FIRM) == before
    assert cards(engine, OTHER) == []
    listed = client.get(
        "/v1/notification/notifications",
        params={"business_id": str(CLIENT)},
        headers={"x-tenant-id": str(OTHER)},
    )
    assert listed.status_code == 200
    assert listed.json()["items"] == []
    with engine.connect() as connection:
        keys: list[UUID] = list(
            connection.execute(
                text("SELECT tenant_id FROM idempotency_key WHERE key = :sent"), {"sent": FIRST}
            ).scalars()
        )
    assert sorted(str(tenant) for tenant in keys) == sorted([str(FIRM), str(OTHER)])


def test_the_card_the_change_made_keeps_the_bulk_from_sending_again(
    client: TestClient, engine: Engine, reader: FakeObligationReader
) -> None:
    later = RuleVersionId(UUID(int=0xCB3))
    reader.add(
        FIRM,
        OpenObligation(
            obligation_id=ObligationId.new(),
            business_id=CLIENT,
            rule_version_id=later,
            title="File the corrected annual return (synthetic)",
        ),
    )
    wiring = client.app.state.wiring  # type: ignore[attr-defined]
    with wiring.unit_of_work(FIRM) as unit:
        made = wiring.enqueue.run_in(
            unit,
            ObligationNotice(
                tenant_id=FIRM,
                business_id=CLIENT,
                occasion=Occasion.change_card(ObligationId.new(), later),
                template_key="change_card",
                params={"title": "Example (synthetic)", "rule_version_id": str(later)},
            ),
        )
    assert made.queued == 3, "the change's own card reaches the firm's admin too"
    response = client.post(
        "/v1/notification/bulk",
        json={"rule_version_id": str(later), "business_ids": [str(CLIENT)], "kind": "change_card"},
        headers={"x-tenant-id": str(FIRM), "Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 201, response.text
    (business,) = response.json()["businesses"]
    assert (business["outcome"], business["queued"], business["duplicates"]) == (
        "duplicate",
        0,
        2,
    )
