"""The tenant's data export on Postgres, as the service's own role cw_obligation, which owns
nothing and is not a superuser, so row-level security holds as in a deployment: the export of one
tenant holds only that tenant's obligations, changes and comments, read in keyset pages. Needs
Docker."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from testcontainers.community.postgres import PostgresContainer

from domain_kernel.ids import TenantId, UserId
from obligation.application.export import SECTIONS, ExportTenantData
from obligation.infrastructure.repository import PostgresUnitOfWorkFactory
from obligation.testing import TenantRecords, tenant_records
from py_common.audit.testing import install_audit_table
from py_common.db_roles import apply_roles, as_role

pytestmark = pytest.mark.integration

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "obligation"
MADE = datetime(2000, 1, 5, 4, 30, tzinfo=UTC)
GENERATED = datetime(2000, 3, 1, 12, 0, tzinfo=UTC)
OWNER = UserId(UUID(int=0x0E1))


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    with PostgresContainer(IMAGE, driver="psycopg") as postgres:
        base_url = postgres.get_connection_url()
        admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
            install_audit_table(connection)
        admin.dispose()
        yield f"{base_url}?options=-csearch_path%3D{SCHEMA}%2Cpublic"


@pytest.fixture(scope="module")
def app_engine(database_url: str) -> Iterator[Engine]:
    with pytest.MonkeyPatch.context() as env:
        env.setenv("CW_DATABASE_URL", database_url)
        env.setenv("CW_DB_SCHEMA", SCHEMA)
        command.upgrade(Config(str(SERVICE_DIR / "alembic.ini")), "head")
    apply_roles(database_url)
    engine = create_engine(as_role(database_url, SCHEMA))
    yield engine
    engine.dispose()


def keep(factory: PostgresUnitOfWorkFactory, records: TenantRecords) -> None:
    with factory(records.obligation.tenant_id) as uow:
        uow.obligations.add(records.obligation)
        for change in records.changes:
            uow.history.append(change)
        uow.comments.add(records.comment)


def test_the_export_of_a_tenant_holds_only_its_rows_in_pages(app_engine: Engine) -> None:
    factory = PostgresUnitOfWorkFactory(app_engine)
    tenant, other = TenantId.new(), TenantId.new()
    ours = [
        tenant_records(tenant, MADE + timedelta(hours=index // 2), closed_by=OWNER)
        for index in range(5)
    ]
    theirs = [tenant_records(other, MADE + timedelta(minutes=index)) for index in range(3)]
    for records in (*theirs, *ours):
        keep(factory, records)

    found = ExportTenantData(factory, lambda: GENERATED, page_size=2).run(tenant)

    assert (found.service, found.tenant_id) == ("obligation", tenant)
    assert tuple(found.sections) == SECTIONS
    by_creation = sorted(ours, key=lambda r: (r.obligation.created_at, r.obligation.id.value))
    assert [row["id"] for row in found.sections["obligations"]] == [
        str(r.obligation.id.value) for r in by_creation
    ]
    changes = sorted(
        (change for r in ours for change in r.changes),
        key=lambda change: (change.occurred_at, change.id.value),
    )
    assert [row["id"] for row in found.sections["changes"]] == [str(c.id.value) for c in changes]
    comments = sorted((r.comment for r in ours), key=lambda c: (c.created_at, c.id.value))
    assert [row["id"] for row in found.sections["comments"]] == [str(c.id.value) for c in comments]
    first = found.sections["obligations"][0]
    assert (first["status"], first["closed_by"], first["created_at"]) == (
        "done",
        str(OWNER.value),
        by_creation[0].obligation.created_at.isoformat(),
    )
    text_of_export = str(found.sections)
    assert str(other.value) not in text_of_export
    assert not any(str(r.obligation.id.value) in text_of_export for r in theirs)

    whole = ExportTenantData(factory, lambda: GENERATED).run(tenant)
    assert whole.sections == found.sections, "one page or many, the same rows"
    nobody = ExportTenantData(factory, lambda: GENERATED).run(TenantId.new())
    assert nobody.sections == {section: [] for section in SECTIONS}
