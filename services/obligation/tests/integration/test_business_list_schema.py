"""The public list of a business's obligations on Postgres, through obligation's own role,
cw_obligation, which owns nothing and is not a superuser, so row-level security holds as in a
deployment. Needs Docker.

- pages of one follow one another in the order of due date (none last) and id, the order a single
  page has, ties broken by id;
- the status and the window keep what they name;
- another tenant reads an empty page under row-level security, and the profile service saying the
  business is not theirs makes it a 404, through the use case and the route.
"""

from collections.abc import Iterator
from datetime import date
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from testcontainers.community.postgres import PostgresContainer

from domain_kernel.ids import BusinessId, DecisionId, TenantId
from domain_kernel.status import ObligationStatus
from obligation.application.materialise import IST, MaterialiseObligations, MaterialiseRequest
from obligation.application.queries import BusinessObligationsQuery, ListBusinessObligations
from obligation.domain.errors import BusinessNotFoundError
from obligation.domain.model import DueWindow
from obligation.domain.repository import ListingAfter
from obligation.infrastructure.repository import PostgresUnitOfWorkFactory
from obligation.main import build_app
from obligation.settings import ObligationSettings
from obligation.testing import (
    FakeProfileNodes,
    FakeRuleVersionReader,
    FakeTenantMembers,
    ref_of,
    rule,
)
from py_common.db_roles import apply_roles, as_role

pytestmark = pytest.mark.integration

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "obligation"
TENANT_A = TenantId(UUID("0a0a0a0a-0000-4000-8000-0000000000a1"))
TENANT_B = TenantId(UUID("0b0b0b0b-0000-4000-8000-0000000000b1"))
BUSINESS = BusinessId(UUID(int=0xB1))
AS_OF = date(2026, 9, 28)
MONTHLY = rule()
QUARTERLY_SAME_DAY = rule()
"""A second monthly rule: its obligations fall due on the same days, so ids break the ties."""
UNDATED = rule(recurrence=None)


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    with PostgresContainer(IMAGE, driver="psycopg") as postgres:
        base_url = postgres.get_connection_url()
        admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
        admin.dispose()
        # The service's own role, as a fresh dev volume has it before the migrations:
        # the tables they create, again after a downgrade, reach it too.
        apply_roles(base_url)
        yield f"{base_url}?options=-csearch_path%3D{SCHEMA}%2Cpublic"


@pytest.fixture(scope="module")
def app_url(database_url: str) -> str:
    with pytest.MonkeyPatch.context() as env:
        env.setenv("CW_DATABASE_URL", database_url)
        env.setenv("CW_DB_SCHEMA", SCHEMA)
        command.upgrade(Config(str(SERVICE_DIR / "alembic.ini")), "head")
    return as_role(database_url, SCHEMA)


@pytest.fixture(scope="module")
def app_engine(app_url: str) -> Iterator[Engine]:
    engine = create_engine(app_url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def factory(app_engine: Engine) -> PostgresUnitOfWorkFactory:
    """Tenant A's business with two monthly rules due on the same days and one undated duty,
    made as the app role; the first rule's facts are cached."""
    units = PostgresUnitOfWorkFactory(app_engine)
    materialise = MaterialiseObligations(units, window=3)
    for snapshot in (MONTHLY, QUARTERLY_SAME_DAY, UNDATED):
        materialise.run(MaterialiseRequest(TENANT_A, BUSINESS, DecisionId.new(), snapshot, AS_OF))
    with units(TENANT_A) as uow:
        uow.rule_versions.merge(ref_of(MONTHLY))
    return units


def listing(factory: PostgresUnitOfWorkFactory) -> ListBusinessObligations:
    return ListBusinessObligations(factory, FakeProfileNodes([(TENANT_A, BUSINESS)]))


def test_pages_of_one_follow_the_order_of_a_whole_page(factory: PostgresUnitOfWorkFactory) -> None:
    use = listing(factory)
    whole = [item.obligation for item in use.run(BusinessObligationsQuery(TENANT_A, BUSINESS, 50))]
    dated = [o for o in whole if o.due_at is not None]
    assert len(dated) >= 4
    assert whole[-1].due_at is None
    assert dated == sorted(dated, key=lambda o: (o.due_at, o.id.value))
    assert len({o.due_at for o in dated}) < len(dated), "two rules fall due on the same days"
    paged = []
    after: ListingAfter | None = None
    while True:
        page = use.run(BusinessObligationsQuery(TENANT_A, BUSINESS, 2, after=after))
        paged += [item.obligation for item in page[:1]]
        if len(page) < 2:
            break
        after = ListingAfter(page[0].obligation.due_at, page[0].obligation.id)
    assert [o.id for o in paged] == [o.id for o in whole]
    cached = {
        item.obligation.rule_version_id: item.ref
        for item in use.run(BusinessObligationsQuery(TENANT_A, BUSINESS, 50))
    }
    assert cached[MONTHLY.rule_version_id] == ref_of(MONTHLY)
    assert cached[QUARTERLY_SAME_DAY.rule_version_id] is None


def test_the_status_and_the_window_keep_what_they_name(factory: PostgresUnitOfWorkFactory) -> None:
    use = listing(factory)
    whole = [item.obligation for item in use.run(BusinessObligationsQuery(TENANT_A, BUSINESS, 50))]
    first = whole[0]
    with factory(TENANT_A) as uow:
        found = uow.obligations.get(first.id, lock=True)
        assert found is not None
        uow.obligations.save(found.start(found.updated_at))
    going = use.run(
        BusinessObligationsQuery(
            TENANT_A, BUSINESS, 50, statuses=frozenset({ObligationStatus.IN_PROGRESS})
        )
    )
    assert [item.obligation.id for item in going] == [first.id]
    assert first.due_at is not None
    day = first.due_at.astimezone(IST).date()
    window = DueWindow(day, day)
    due_that_day = use.run(BusinessObligationsQuery(TENANT_A, BUSINESS, 50, window=window))
    assert {item.obligation.due_at for item in due_that_day} == {first.due_at}
    assert all(item.obligation.due_at is not None for item in due_that_day)


def test_another_tenant_reads_nothing_and_gets_404(
    factory: PostgresUnitOfWorkFactory, app_url: str
) -> None:
    use = listing(factory)
    with factory(TENANT_B) as uow:
        hidden = uow.obligations.page_for_business(
            BUSINESS,
            statuses=frozenset(),
            due_after=None,
            due_before=None,
            after=None,
            limit=50,
        )
    assert hidden == [], "row-level security hides tenant A's obligations"
    with pytest.raises(BusinessNotFoundError):
        use.run(BusinessObligationsQuery(TENANT_B, BUSINESS, 50))
    settings = ObligationSettings(
        _env_file=None, service_name="obligation", database_url=app_url, db_schema=SCHEMA
    )
    app = build_app(
        settings,
        rules=FakeRuleVersionReader(),
        members=FakeTenantMembers(),
        profiles=FakeProfileNodes([(TENANT_A, BUSINESS)]),
    )
    path = f"/v1/businesses/{BUSINESS}/obligations"
    with TestClient(app) as client:
        as_a = client.get(path, params={"limit": 2}, headers={"x-tenant-id": str(TENANT_A)})
        as_b = client.get(path, headers={"x-tenant-id": str(TENANT_B)})
        rest = client.get(
            path,
            params={"cursor": as_a.json()["next_cursor"], "limit": 200},
            headers={"x-tenant-id": str(TENANT_A)},
        )
        foreign_cursor = client.get(
            path,
            params={"cursor": as_a.json()["next_cursor"]},
            headers={"x-tenant-id": str(TENANT_B)},
        )
    assert as_a.status_code == 200, as_a.text
    assert len(as_a.json()["items"]) == 2
    assert as_a.json()["next_cursor"]
    assert rest.status_code == 200
    assert rest.json()["next_cursor"] is None
    assert rest.json()["items"][-1]["due_at"] is None
    facts = {
        item["rule_version_id"]: item["rule_version"]
        for item in as_a.json()["items"] + rest.json()["items"]
    }
    assert facts[str(MONTHLY.rule_version_id)] is not None, "the cached version's facts"
    assert facts[str(QUARTERLY_SAME_DAY.rule_version_id)] is None, "not cached: null"
    assert as_b.status_code == 404, as_b.text
    assert as_b.json()["type"].endswith(":obligation-business-not-found")
    assert foreign_cursor.status_code == 404, "a cursor reads nothing of another tenant"
