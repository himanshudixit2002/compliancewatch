"""``PostgresRecords`` on Postgres: it counts and finds directory entries by level and creation
time, reads audit rows of no tenant, which the product's role cannot, and can write nothing.
Needs Docker."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import InternalError, OperationalError
from testcontainers.community.postgres import PostgresContainer

from applicability_engine.infrastructure.models import BusinessDirectoryRow
from cw_demo.product.records import PostgresRecords
from domain_kernel.audit import AuditActor
from py_common.audit.testing import audit_entry, install_audit_table
from py_common.audit.writer import AuditWriter

pytestmark = pytest.mark.integration

IMAGE = "pgvector/pgvector:0.8.6-pg16"
EARLY = datetime(2026, 10, 1, tzinfo=UTC)
LATE = datetime(2026, 10, 5, tzinfo=UTC)


@pytest.fixture(scope="module")
def url() -> Iterator[str]:
    with PostgresContainer(IMAGE, driver="psycopg") as postgres:
        base = postgres.get_connection_url()
        engine = create_engine(base)
        with engine.begin() as connection:
            connection.execute(text("CREATE SCHEMA applicability"))
            connection.execute(text("SET search_path TO applicability"))
            BusinessDirectoryRow.metadata.create_all(
                connection,
                tables=[BusinessDirectoryRow.__table__],  # type: ignore[list-item]
            )
            install_audit_table(connection)
        engine.dispose()
        yield base


def test_it_reads_the_directory_and_the_audit_rows_and_writes_nothing(url: str) -> None:
    writer = create_engine(url)
    tenant = uuid4()
    early, late, entity = uuid4(), uuid4(), uuid4()
    with writer.begin() as connection:
        for business, level, created in (
            (entity, "entity", EARLY),
            (early, "registration", EARLY),
            (late, "registration", LATE),
        ):
            connection.execute(
                text(
                    "INSERT INTO applicability.business_directory "
                    "(business_id, tenant_id, level, parent_id, entity_id, created_at) "
                    "VALUES (:b, :t, :level, :parent, :e, :created)"
                ),
                {
                    "b": business,
                    "t": tenant,
                    "level": level,
                    "parent": None if level == "entity" else entity,
                    "e": entity,
                    "created": created,
                },
            )
        AuditWriter().write(
            connection,
            audit_entry(
                action="applicability.fanout.hold",
                tenant_id=None,
                subject_type="fanout_hold",
                subject_id="global",
                actor=AuditActor.system("applicability-engine"),
                reason="cw-product check: held for a test",
                occurred_at=LATE,
            ),
        )
    writer.dispose()
    records = PostgresRecords(url)
    try:
        assert records.directory_count("registration") == 2
        assert records.directory_count("registration", as_of=EARLY + timedelta(days=1)) == 1
        assert records.listed([str(early), str(late), str(uuid4())]) == {str(early), str(late)}
        assert records.listed([str(late)], as_of=EARLY) == set()
        assert records.listed([]) == set()
        (row,) = records.audit_entries(actions=["applicability.fanout.hold"], since=EARLY)
        assert (row.subject_id, row.tenant_id, row.actor_label) == (
            "global",
            None,
            "system:applicability-engine",
        )
        assert (
            records.audit_entries(
                actions=["applicability.fanout.hold"], since=LATE + timedelta(seconds=1)
            )
            == []
        )
        with (
            pytest.raises((InternalError, OperationalError)),
            records._engine.connect() as connection,
        ):
            connection.execute(text("DELETE FROM applicability.business_directory"))
    finally:
        records.close()
