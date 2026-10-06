"""Migration 0001 on Postgres: the tables, the unit of work with the outbox, the rules the tables
keep, the catalog lint, and a downgrade back to nothing. Needs Docker.

The repositories run as a plain database role with the grants infra/dev/postgres/50-app-role.sql
gives the product's cw_app: it owns nothing and is not a superuser.
"""

import hashlib
import importlib
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Engine, create_engine, inspect, make_url, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.pool import NullPool
from testcontainers.community.postgres import PostgresContainer

from domain_kernel.documents import DocumentType, document_id_for
from domain_kernel.ids import SourceId
from pipeline.domain.crawl import CrawlCounts, CrawlRun, CrawlStatus
from pipeline.domain.events import DocumentDiscovered
from pipeline.domain.raw_documents import DocumentStatus, RawDocumentRecord
from pipeline.domain.sources import Source, SourceDefinition
from pipeline.infrastructure.models import Base
from pipeline.infrastructure.repository import PostgresUnitOfWorkFactory

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "pipeline"
STORE_TABLES = {"source", "raw_document", "crawl_run"}
TABLES = {*STORE_TABLES, "outbox_event", "alembic_version"}
APP_ROLE = "pipeline_app"
APP_PASSWORD = "app-role-for-tests"
NOW = datetime(2026, 10, 6, 4, 30, tzinfo=UTC)
DEFINITION = SourceDefinition(
    key="cbic_notifications",
    adapter_type="cbic",
    parameters={"listing": "notifications", "category": "Central Tax"},
    cadence=timedelta(hours=2),
    regulator="CBIC",
    doc_type=DocumentType.NOTIFICATION,
)
SOURCE_ID = SourceId.new()


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    with PostgresContainer(IMAGE, driver="psycopg") as postgres:
        base_url = postgres.get_connection_url()
        admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
            connection.execute(
                text(f"CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{APP_PASSWORD}' NOSUPERUSER")
            )
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
def migrated(database_url: str) -> Iterator[Config]:
    with pytest.MonkeyPatch.context() as env:
        env.setenv("CW_DATABASE_URL", database_url)
        env.setenv("CW_DB_SCHEMA", SCHEMA)
        config = Config(str(SERVICE_DIR / "alembic.ini"))
        command.upgrade(config, "head")
        yield config


@pytest.fixture(scope="module")
def engine(database_url: str, migrated: Config) -> Iterator[Engine]:
    engine = create_engine(database_url, poolclass=NullPool)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def units(database_url: str, migrated: Config) -> Iterator[PostgresUnitOfWorkFactory]:
    url = make_url(database_url).set(username=APP_ROLE, password=APP_PASSWORD)
    factory = PostgresUnitOfWorkFactory(create_engine(url, poolclass=NullPool))
    yield factory
    factory.engine.dispose()


def record(content: bytes, **overrides: object) -> RawDocumentRecord:
    digest = hashlib.sha256(content).hexdigest()
    values: dict[str, object] = {
        "document_id": document_id_for(digest),
        "source_key": DEFINITION.key,
        "source_url": "https://taxinformation.cbic.gov.in/content/pdf/gst-ct-17-2025.pdf",
        "fetched_at": NOW,
        "content_type": "application/pdf",
        "size": len(content),
        "sha256": digest,
        "storage_key": f"raw/{digest[:2]}/{digest}",
        "external_ref": "17/2025-Central Tax",
        "title": "Seeks to extend the due date for FORM GSTR-3B",
        "published_on": date(2025, 9, 18),
    }
    values.update(overrides)
    return RawDocumentRecord(**values)  # type: ignore[arg-type]


def discovered(stored: RawDocumentRecord) -> DocumentDiscovered:
    return DocumentDiscovered(
        source_id=SOURCE_ID,
        document_id=stored.document_id,
        regulator="CBIC",
        url=stored.source_url,
        external_ref=stored.external_ref,
        title=stored.title,
        published_at=stored.published_on,
        sha256=stored.sha256,
        media_type=stored.content_type,
        fetched_at=stored.fetched_at,
        raw_uri=f"s3://cw-raw/{stored.storage_key}",
    )


def count(engine: Engine, table: str) -> int:
    with engine.connect() as connection:
        found: int = connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
    return found


def test_migration_creates_the_tables_without_tenant_columns(engine: Engine) -> None:
    inspector = inspect(engine)
    assert set(inspector.get_table_names(schema=SCHEMA)) == TABLES
    for table in STORE_TABLES:
        columns = {column["name"] for column in inspector.get_columns(table, schema=SCHEMA)}
        assert "tenant_id" not in columns, "the pipeline's data is regulatory"
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert version == "0001"


def test_models_and_migration_agree(engine: Engine) -> None:
    def only_the_store_tables(
        obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
    ) -> bool:
        table = name if type_ == "table" else getattr(getattr(obj, "table", None), "name", None)
        return table in STORE_TABLES

    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={
                "compare_type": True,
                "compare_server_default": True,
                "include_object": only_the_store_tables,
            },
        )
        assert compare_metadata(context, Base.metadata) == []


def test_the_catalog_lint_accepts_the_tables(engine: Engine) -> None:
    lint = importlib.import_module("check_migrations")  # infra/scripts, on the pytest path
    with engine.connect() as connection:
        raw = connection.connection.driver_connection
        catalog = [t for t in lint.read_tables(raw) if t.schema == SCHEMA]
    assert {t.name for t in catalog} == TABLES
    assert all(t.tenant_id == "absent" for t in catalog if t.name in STORE_TABLES)
    problems = lint.catalog_problems(catalog, lint.load_config())
    assert [p for p in problems if p.startswith(f"{SCHEMA}.")] == []
    exempt = {t.qualified for t in catalog if lint.load_config().exemption_for(t.qualified)}
    assert {f"{SCHEMA}.{table}" for table in STORE_TABLES} <= exempt


def test_a_document_and_its_event_commit_together(
    units: PostgresUnitOfWorkFactory, engine: Engine
) -> None:
    stored = record(b"%PDF-1.7 seventeen")
    with units() as unit:
        assert unit.sources.add(Source.of(DEFINITION, NOW))
        assert unit.documents.add(stored)
        unit.events.publish(discovered(stored))
    with units() as unit:
        assert unit.documents.get(stored.document_id) == stored
        assert unit.documents.add(record(b"%PDF-1.7 seventeen", title="again")) is False
        assert unit.sources.add(Source.of(DEFINITION, NOW + timedelta(days=1))) is False
        source = unit.sources.get(DEFINITION.key)
    assert source is not None
    assert (source.created_at, dict(source.parameters)) == (NOW, dict(DEFINITION.parameters))
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT topic, partition_key, tenant_id, message FROM outbox_event")
        ).all()
    assert [(row.topic, row.partition_key, row.tenant_id) for row in rows] == [
        ("document.discovered", str(SOURCE_ID), None)
    ]
    payload = rows[0].message["payload"]
    assert (payload["document_id"], payload["sha256"]) == (
        str(stored.document_id),
        stored.sha256,
    )
    assert payload["published_at"] == "2025-09-18"


def test_a_failed_unit_writes_neither_the_row_nor_the_event(
    units: PostgresUnitOfWorkFactory, engine: Engine
) -> None:
    before = (count(engine, "raw_document"), count(engine, "outbox_event"))
    stored = record(b"%PDF-1.7 rolled back")

    def write_then_fail() -> None:
        with units() as unit:
            unit.sources.add(Source.of(DEFINITION, NOW))
            unit.documents.add(stored)
            unit.events.publish(discovered(stored))
            raise RuntimeError("the transaction fails after the writes")

    with pytest.raises(RuntimeError, match="after the writes"):
        write_then_fail()
    assert (count(engine, "raw_document"), count(engine, "outbox_event")) == before
    with units() as unit:
        assert unit.documents.get(stored.document_id) is None


def test_a_document_needs_its_source(units: PostgresUnitOfWorkFactory) -> None:
    orphan = record(b"%PDF-1.7 orphan", source_key="gstn_advisories")
    with pytest.raises(IntegrityError, match="fk_raw_document_source_key_source"), units() as unit:
        unit.documents.add(orphan)


def test_a_raw_document_changes_only_its_status_and_stays(
    units: PostgresUnitOfWorkFactory, engine: Engine
) -> None:
    stored = record(b"%PDF-1.7 status", published_on=None)
    with units() as unit:
        unit.sources.add(Source.of(DEFINITION, NOW))
        unit.documents.add(stored)
    with units() as unit:
        assert unit.documents.set_status(stored.document_id, DocumentStatus.IRRELEVANT)
        assert not unit.documents.set_status(
            record(b"never stored").document_id, DocumentStatus.FAILED
        )
    with units() as unit:
        changed = unit.documents.get(stored.document_id)
    assert changed is not None
    assert changed.status is DocumentStatus.IRRELEVANT
    for statement in (
        "UPDATE raw_document SET title = 'rewritten' WHERE id = :id",
        "UPDATE raw_document SET storage_key = 'elsewhere' WHERE id = :id",
        "DELETE FROM raw_document WHERE id = :id",
    ):
        with pytest.raises(DBAPIError, match="raw_document"), engine.begin() as connection:
            connection.execute(text(statement), {"id": stored.document_id.value})


def test_an_id_that_is_not_the_digests_is_refused(engine: Engine) -> None:
    stored = record(b"%PDF-1.7 forged")
    with (
        pytest.raises(IntegrityError, match="ck_raw_document_id_from_sha256"),
        engine.begin() as connection,
    ):
        connection.execute(
            text(
                "INSERT INTO raw_document (id, source_key, source_url, fetched_at,"
                " content_type, size, sha256, storage_key)"
                " VALUES (gen_random_uuid(), :key, 'https://x.invalid', now(),"
                " 'application/pdf', 1, :sha256, 'raw/forged')"
            ),
            {"key": DEFINITION.key, "sha256": stored.sha256},
        )


def test_documents_list_newest_first_and_crawl_runs_round_trip(
    units: PostgresUnitOfWorkFactory,
) -> None:
    gstn = SourceDefinition(
        key="gstn_advisories",
        adapter_type="gstn",
        parameters={},
        cadence=timedelta(hours=3),
        regulator="GSTN",
        doc_type=DocumentType.PRESS_RELEASE,
    )
    older = record(b"advisory 670", source_key=gstn.key, published_on=date(2026, 8, 1))
    newer = record(b"advisory 672", source_key=gstn.key, published_on=date(2026, 9, 19))
    undated = record(b"advisory undated", source_key=gstn.key, published_on=None)
    run = CrawlRun.start(gstn.key, NOW)
    with units() as unit:
        unit.sources.add(Source.of(gstn, NOW))
        for document in (undated, older, newer):
            unit.documents.add(document)
        unit.crawl_runs.add(run)
    finished = run.finish(NOW + timedelta(minutes=3), CrawlCounts(listed=3, stored=3))
    with units() as unit:
        unit.crawl_runs.save(finished)
        source = unit.sources.get(gstn.key)
        assert source is not None
        unit.sources.save(
            Source(
                key=source.key,
                adapter_type=source.adapter_type,
                parameters=source.parameters,
                cadence=source.cadence,
                created_at=source.created_at,
                updated_at=NOW + timedelta(minutes=3),
                last_fetch_at=NOW + timedelta(minutes=3),
                watermark={"published_on": "2026-09-19"},
            )
        )
    with units() as unit:
        recent = unit.documents.recent(gstn.key, limit=2)
        latest = unit.crawl_runs.latest(gstn.key)
        saved = unit.sources.get(gstn.key)
        listed = [source.key for source in unit.sources.list()]
    assert [d.document_id for d in recent] == [newer.document_id, older.document_id]
    assert latest == finished
    assert latest is not None
    assert (latest.status, latest.counts.fetched) == (CrawlStatus.COMPLETED, 3)
    assert saved is not None
    assert saved.watermark == {"published_on": "2026-09-19"}
    assert saved.last_fetch_at == NOW + timedelta(minutes=3)
    assert listed == ["cbic_notifications", "gstn_advisories"]
    assert units.ping()


def test_downgrade_removes_everything(engine: Engine, migrated: Config) -> None:
    command.downgrade(migrated, "base")
    try:
        assert set(inspect(engine).get_table_names(schema=SCHEMA)) == {"alembic_version"}
        with engine.connect() as connection:
            functions = connection.execute(
                text("SELECT proname FROM pg_proc WHERE proname = 'pipeline_raw_document_guard'")
            ).all()
        assert functions == []
    finally:
        command.upgrade(migrated, "head")
    assert set(inspect(engine).get_table_names(schema=SCHEMA)) == TABLES
