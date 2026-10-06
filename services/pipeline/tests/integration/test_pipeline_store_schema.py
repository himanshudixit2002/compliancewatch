"""Migrations 0001 to 0004 on Postgres: the tables, the unit of work with the outbox and the
audit log, the rules the tables keep, the crawl's queries, the parse of a document and the tasks
on it, its classification and its rule extraction with the candidate's event, the catalog lint,
and a downgrade back to nothing. Needs Docker.

The repositories run as a plain database role with the grants infra/dev/postgres/50-app-role.sql
gives the product's cw_app: it owns nothing and is not a superuser. ``audit.event`` is made as
identity's migration makes it (``py_common.audit.testing.install_audit_table``).
"""

import hashlib
import importlib
from collections.abc import Iterator
from dataclasses import replace
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

from domain_kernel.audit import AuditActor, AuditEntryId
from domain_kernel.documents import DocumentType, document_id_for
from domain_kernel.ids import SourceId, UserId
from pipeline.application.sources import AddSource, AdminAction, NewSource
from pipeline.domain.candidate import candidate_from_mapping
from pipeline.domain.classification import Classification, Relevance, TypeConfidence
from pipeline.domain.crawl import CrawlCounts, CrawlRun, CrawlStatus
from pipeline.domain.events import DocumentClassified, DocumentDiscovered
from pipeline.domain.extraction import ExtractionOutcome, RuleExtraction, candidate_id_for
from pipeline.domain.issues import Issue
from pipeline.domain.raw_documents import DocumentStatus, RawDocumentRecord
from pipeline.domain.repository import DocumentKey, TaskKey
from pipeline.domain.sources import Source, SourceDefinition
from pipeline.domain.tasks import PipelineTask, TaskKind, TaskStatus
from pipeline.infrastructure.adapters import RegistryAdapterTypes
from pipeline.infrastructure.models import Base
from pipeline.infrastructure.repository import PostgresUnitOfWorkFactory
from py_common.audit.testing import install_audit_table, read_audit_entries

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "pipeline"
STORE_TABLES = {
    "source",
    "raw_document",
    "crawl_run",
    "pipeline_task",
    "document_classification",
    "rule_extraction",
}
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
            connection.execute(text("CREATE SCHEMA audit"))
            connection.execute(
                text(f"CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{APP_PASSWORD}' NOSUPERUSER")
            )
            for schema in (SCHEMA, "audit"):
                connection.execute(text(f"GRANT USAGE ON SCHEMA {schema} TO {APP_ROLE}"))
                connection.execute(
                    text(
                        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} "
                        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}"
                    )
                )
        with admin.begin() as connection:
            install_audit_table(connection)
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
    assert version == "0004"
    names = {column["name"] for column in inspector.get_columns("source", schema=SCHEMA)}
    assert "name" in names
    indexes = {index["name"] for index in inspector.get_indexes("raw_document", schema=SCHEMA)}
    assert "ix_raw_document_source_url" in indexes
    parse = {column["name"] for column in inspector.get_columns("raw_document", schema=SCHEMA)}
    assert {"parser_version", "doc_type", "transcript_key"} <= parse
    task_indexes = {
        index["name"]: index for index in inspector.get_indexes("pipeline_task", schema=SCHEMA)
    }
    assert task_indexes["uq_pipeline_task_open"]["unique"]


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


def test_a_source_name_is_kept_and_bounded(
    units: PostgresUnitOfWorkFactory, engine: Engine
) -> None:
    named = Source.of(
        SourceDefinition(
            key="mahagst_notifications",
            adapter_type="mahagst",
            parameters={},
            cadence=timedelta(hours=12),
            regulator="Maharashtra GST",
            doc_type=DocumentType.NOTIFICATION,
            name="Maharashtra GST notifications",
        ),
        NOW,
    )
    with units() as unit:
        unit.sources.add(named)
    with units() as unit:
        assert unit.sources.get(named.key, for_update=True) == named
    with (
        pytest.raises(IntegrityError, match="ck_source_name_length"),
        engine.begin() as connection,
    ):
        connection.execute(
            text("UPDATE source SET name = repeat('x', 201) WHERE key = :key"),
            {"key": named.key},
        )


def test_the_crawl_finds_known_urls_and_pages_documents_on_postgres(
    units: PostgresUnitOfWorkFactory,
) -> None:
    council = SourceDefinition(
        key="gstcouncil_press",
        adapter_type="gstcouncil",
        parameters={},
        cadence=timedelta(hours=6),
        regulator="GST Council",
        doc_type=DocumentType.PRESS_RELEASE,
    )
    url = "https://gstcouncil.gov.in/press/56.pdf"
    first = record(b"press 56", source_key=council.key, source_url=url, published_on=None)
    corrected = record(
        b"press 56, corrected",
        source_key=council.key,
        source_url=url,
        published_on=None,
        fetched_at=NOW + timedelta(days=1),
    )
    dated = [
        record(
            f"press {day}".encode(),
            source_key=council.key,
            source_url=f"https://gstcouncil.gov.in/press/{day}.pdf",
            published_on=date(2026, 9, day),
        )
        for day in (3, 9, 21)
    ]
    dated.append(
        record(
            b"press 9, second",
            source_key=council.key,
            source_url="https://gstcouncil.gov.in/press/9b.pdf",
            published_on=date(2026, 9, 9),
        )
    )
    with units() as unit:
        unit.sources.add(Source.of(council, NOW))
        for document in (first, corrected, *dated):
            unit.documents.add(document)
    with units() as unit:
        assert unit.documents.find_by_url(council.key, url) == corrected
        assert unit.documents.find_by_url(council.key, url + "?x") is None
        urls = [url, "https://gstcouncil.gov.in/press/3.pdf", "https://gstcouncil.gov.in/nope"]
        assert unit.documents.known_urls(council.key, urls) == frozenset(urls[:2])
        assert unit.documents.counts()[council.key] == 2 + len(dated)
        everything = unit.documents.page(council.key, after=None, limit=50)
        pages: list[RawDocumentRecord] = []
        after: DocumentKey | None = None
        while page := unit.documents.page(council.key, after=after, limit=2):
            pages.extend(page)
            after = DocumentKey.of(page[-1])
        recent = unit.documents.fetched_since(NOW + timedelta(hours=1))
    assert pages == list(everything)
    assert [d.published_on for d in everything][:4] == [
        date(2026, 9, 21),
        date(2026, 9, 9),
        date(2026, 9, 9),
        date(2026, 9, 3),
    ]
    assert [d.published_on for d in everything][4:] == [None, None]
    assert everything[4] == corrected, "the undated last, the latest fetch first"
    assert corrected in recent
    assert first not in recent


def test_runs_start_once_and_are_found_per_source_on_postgres(
    units: PostgresUnitOfWorkFactory,
) -> None:
    advisories = "gstn_advisories"
    first = CrawlRun.start(advisories, NOW + timedelta(days=3))
    second = CrawlRun.start(advisories, NOW + timedelta(days=3, hours=3))
    with units() as unit:
        assert unit.crawl_runs.start(first)
        assert not unit.crawl_runs.start(first)
        assert unit.crawl_runs.start(second)
    with units() as unit:
        unit.crawl_runs.save(first.finish(first.started_at + timedelta(minutes=1), CrawlCounts()))
        assert unit.crawl_runs.running(advisories) == [second]
        assert unit.crawl_runs.latest_by_source()[advisories] == second
        since = unit.crawl_runs.started_since(NOW + timedelta(days=3))
    assert [run.id for run in since] == [first.id, second.id]


def test_an_admins_change_and_its_audit_row_commit_together(
    units: PostgresUnitOfWorkFactory, engine: Engine
) -> None:
    admin = AdminAction(actor=AuditActor.user(UserId.new()), reason="A source for the schema test")
    added = AddSource(units, RegistryAdapterTypes()).run(
        NewSource(
            key="cbic_circulars",
            name="CBIC CGST circulars",
            adapter_type="cbic",
            parameters={"listing": "circulars", "category": "Circulars CGST"},
            cadence=timedelta(hours=6),
        ),
        admin,
    )
    with engine.connect() as connection:
        (entry,) = read_audit_entries(connection, action="pipeline.source.add")
    assert (entry.subject_id, entry.tenant_id, entry.reason) == (added.key, None, admin.reason)

    def add_then_fail() -> None:
        with units() as unit:
            unit.audit.write(replace(entry, entry_id=AuditEntryId.new()))
            raise RuntimeError("the change fails after its audit row")

    with pytest.raises(RuntimeError, match="after its audit row"):
        add_then_fail()
    with engine.connect() as connection:
        assert len(read_audit_entries(connection, action="pipeline.source.add")) == 1


def test_a_parse_is_recorded_once_and_a_transcript_stays(
    units: PostgresUnitOfWorkFactory, engine: Engine
) -> None:
    stored = record(b"%PDF-1.7 parsed", doc_type=DocumentType.STATUTE)
    with units() as unit:
        unit.sources.add(Source.of(DEFINITION, NOW))
        unit.documents.add(stored)
    with units() as unit:
        assert unit.documents.record_parse(stored.document_id, "pdf-tables@1")
        assert not unit.documents.record_parse(stored.document_id, "pdf-tables@1")
        assert unit.documents.record_parse(stored.document_id, "manual@1", transcript_key="t/1")
        assert not unit.documents.record_parse(stored.document_id, "manual@1", transcript_key="t/2")
        assert not unit.documents.record_parse(record(b"never stored").document_id, "pdf@1")
    with units() as unit:
        parsed = unit.documents.get(stored.document_id)
    assert parsed is not None
    assert (parsed.status, parsed.parser_version, parsed.transcript_key) == (
        DocumentStatus.PARSED,
        "manual@1",
        "t/1",
    )
    assert parsed.doc_type is DocumentType.STATUTE
    for statement, check in (
        ("UPDATE raw_document SET doc_type = 'circular' WHERE id = :id", "raw_document"),
        ("UPDATE raw_document SET parser_version = 'pdf' WHERE id = :id", "parser_version"),
        ("UPDATE raw_document SET transcript_key = '' WHERE id = :id", "transcript_key"),
    ):
        with pytest.raises(DBAPIError, match=check), engine.begin() as connection:
            connection.execute(text(statement), {"id": stored.document_id.value})


def test_tasks_open_once_per_document_and_kind_and_page_oldest_first(
    units: PostgresUnitOfWorkFactory, engine: Engine
) -> None:
    documents = [record(f"%PDF-1.7 scan {n}".encode()) for n in range(3)]
    with units() as unit:
        unit.sources.add(Source.of(DEFINITION, NOW))
        for document in documents:
            unit.documents.add(document)
    opened = [
        PipelineTask.opened(
            TaskKind.MANUAL_PARSE,
            document.document_id,
            DEFINITION.key,
            at=NOW + timedelta(minutes=n),
            reason="pdf@1: the PDF has no text layer",
        )
        for n, document in enumerate(documents)
    ]
    with units() as unit:
        for task in opened:
            assert unit.tasks.open(task) == task
        again = PipelineTask.opened(
            TaskKind.MANUAL_PARSE, documents[0].document_id, DEFINITION.key, at=NOW
        )
        assert unit.tasks.open(again) == opened[0], "one open manual parse per document"
        triage = PipelineTask.opened(
            TaskKind.TRIAGE, documents[0].document_id, DEFINITION.key, at=NOW
        )
        assert unit.tasks.open(triage) == triage
    closed = opened[1].resolve(
        UserId.new().value, NOW + timedelta(hours=1), {"transcript_key": "t/1"}, "Transcribed"
    )
    with units() as unit:
        assert unit.tasks.get(opened[1].id, for_update=True) == opened[1]
        unit.tasks.save(closed)
        assert unit.tasks.open_counts() == {TaskKind.MANUAL_PARSE: 2, TaskKind.TRIAGE: 1}
        assert unit.tasks.open_for(documents[1].document_id, TaskKind.MANUAL_PARSE) is None
        reopened = PipelineTask.opened(
            TaskKind.MANUAL_PARSE,
            documents[1].document_id,
            DEFINITION.key,
            at=NOW + timedelta(minutes=30),
        )
        assert unit.tasks.open(reopened) == reopened, "a closed task leaves room for a new one"
    with units() as unit:
        assert unit.tasks.get(opened[1].id) == closed
        pages: list[PipelineTask] = []
        after: TaskKey | None = None
        while page := unit.tasks.page(
            status=TaskStatus.OPEN, kind=TaskKind.MANUAL_PARSE, after=after, limit=2
        ):
            pages.extend(page)
            after = TaskKey.of(page[-1])
        everything = unit.tasks.page(status=None, kind=None, after=None, limit=50)
    assert [task.id for task in pages] == [opened[0].id, opened[2].id, reopened.id]
    assert len(everything) == 5
    with (
        pytest.raises(IntegrityError, match="ck_pipeline_task_resolved"),
        engine.begin() as connection,
    ):
        connection.execute(
            text("UPDATE pipeline_task SET status = 'dismissed' WHERE id = :id"),
            {"id": opened[0].id.value},
        )


def classified(document: RawDocumentRecord, **overrides: object) -> Classification:
    values: dict[str, object] = {
        "document_id": document.document_id,
        "doc_type": DocumentType.NOTIFICATION,
        "relevance": Relevance.RELEVANT,
        "confidence": TypeConfidence.CERTAIN,
        "reasons": ("its opening names it a notification, the type its source publishes",),
        "classified_at": NOW,
    }
    values.update(overrides)
    return Classification(**values)  # type: ignore[arg-type]


def test_a_classification_is_added_once_and_a_triage_replaces_it(
    units: PostgresUnitOfWorkFactory, engine: Engine
) -> None:
    conflict = record(b"%PDF-1.7 a circular among notifications")
    task = PipelineTask.opened(TaskKind.TRIAGE, conflict.document_id, DEFINITION.key, at=NOW)
    first = classified(
        conflict,
        doc_type=DocumentType.CIRCULAR,
        confidence=TypeConfidence.CONFLICT,
        task_id=task.id,
    )
    with units() as unit:
        unit.sources.add(Source.of(DEFINITION, NOW))
        unit.documents.add(conflict)
        unit.tasks.open(task)
        assert unit.classifications.add(first)
        assert not unit.classifications.add(classified(conflict))
        unit.events.publish(
            DocumentClassified.of(first, source_id=SOURCE_ID, source_key=DEFINITION.key)
        )
    triaged = Classification.triaged(
        conflict.document_id,
        relevance=Relevance.RELEVANT,
        doc_type=DocumentType.CIRCULAR,
        by=UserId.new().value,
        task_id=task.id,
        at=NOW + timedelta(hours=1),
        reason="Read the text: a circular",
    )
    with units() as unit:
        assert unit.classifications.get(conflict.document_id) == first
        unit.classifications.save(triaged)
    with units() as unit:
        assert unit.classifications.get(conflict.document_id) == triaged
        assert unit.classifications.get(record(b"never stored").document_id) is None
    with engine.connect() as connection:
        (message,) = connection.execute(
            text("SELECT message FROM outbox_event WHERE topic = 'document.classified'")
        ).scalars()
    assert message["payload"]["confidence"] == "conflict"
    assert message["payload"]["task_id"] == str(task.id)
    with (
        pytest.raises(IntegrityError, match="ck_document_classification_decided_by"),
        engine.begin() as connection,
    ):
        connection.execute(
            text(
                "UPDATE document_classification SET classifier = 'detector@1'"
                " WHERE document_id = :id"
            ),
            {"id": conflict.document_id.value},
        )


def test_a_classified_document_keeps_its_status_when_parsed_again(
    units: PostgresUnitOfWorkFactory,
) -> None:
    stored = record(b"%PDF-1.7 classified then parsed again")
    with units() as unit:
        unit.sources.add(Source.of(DEFINITION, NOW))
        unit.documents.add(stored)
        assert unit.documents.record_parse(stored.document_id, "pdf@1")
        assert unit.documents.set_status(stored.document_id, DocumentStatus.EXTRACTED)
    with units() as unit:
        assert not unit.documents.record_parse(stored.document_id, "pdf@1")
        assert unit.documents.record_parse(stored.document_id, "pdf-tables@1")
    with units() as unit:
        again = unit.documents.get(stored.document_id)
    assert again is not None
    assert (again.status, again.parser_version) == (DocumentStatus.EXTRACTED, "pdf-tables@1")


ANSWER = {
    "title": "Example: the due date of an example return is extended",
    "summary": "An example notification extends the due date of FORM GSTR-3B.",
    "doc_kind": "notification",
    "change_kind": "extension",
    "effective_from": None,
    "effective_to": None,
    "references": [],
    "applies_to": [
        {
            "attribute": "filing_scheme",
            "operator": "eq",
            "value": "regular_monthly",
            "clause_ref": "en.p3",
        }
    ],
    "obligation": None,
    "recurrence": None,
    "amounts": [],
    "citations": [{"clause_ref": "en.p3", "quote": "extends the due date"}],
    "confidence": 0.9,
}


def test_an_extraction_and_its_candidate_event_commit_together_and_stay(
    units: PostgresUnitOfWorkFactory, engine: Engine
) -> None:
    stored = record(b"%PDF-1.7 extracted")
    prompt = "extraction.rule_candidate@1"
    extraction = RuleExtraction(
        document_id=stored.document_id,
        prompt_version=prompt,
        candidate_id=candidate_id_for(stored.document_id, prompt),
        outcome=ExtractionOutcome.EXTRACTED,
        model="scripted/golden",
        attempts=2,
        source_key=DEFINITION.key,
        doc_type=DocumentType.NOTIFICATION,
        regulator="CBIC",
        issues=(Issue("date_not_in_cited_clauses", "effective_from 2026-04-20", None),),
        citation_count=1,
        confidence=0.9,
        needs_review=True,
        answer="{}",
        ontology_version="0.2.0",
        extracted_at=NOW,
        fields=candidate_from_mapping(ANSWER).to_mapping(),
    )
    with units() as unit:
        unit.sources.add(Source.of(DEFINITION, NOW))
        unit.documents.add(stored)
        assert unit.extractions.add(extraction)
        unit.events.publish(extraction.event(SOURCE_ID))
    with units() as unit:
        assert not unit.extractions.add(extraction), "kept as written"
        assert unit.extractions.get(stored.document_id, prompt) == extraction
        assert unit.extractions.get(stored.document_id, "extraction.rule_candidate@2") is None
    with engine.connect() as connection:
        (message,) = connection.execute(
            text("SELECT message FROM outbox_event WHERE topic = 'rule.candidate.created'")
        ).scalars()
    payload = message["payload"]
    assert (payload["candidate_id"], payload["suggested_rule_key"], payload["outcome"]) == (
        str(extraction.candidate_id),
        "gstr3b_monthly",
        "extracted",
    )
    assert payload["candidate"] == ANSWER
    for statement in (
        "UPDATE rule_extraction SET needs_review = false WHERE document_id = :id",
        "DELETE FROM rule_extraction WHERE document_id = :id",
    ):
        with pytest.raises(DBAPIError, match="kept as written"), engine.begin() as connection:
            connection.execute(text(statement), {"id": stored.document_id.value})


def test_downgrade_removes_everything(engine: Engine, migrated: Config) -> None:
    command.downgrade(migrated, "0003")
    try:
        tables = set(inspect(engine).get_table_names(schema=SCHEMA))
        assert not {"document_classification", "rule_extraction"} & tables
        with engine.connect() as connection:
            statuses = set(
                connection.execute(text("SELECT DISTINCT status FROM raw_document")).scalars()
            )
        assert statuses <= {"discovered", "parsed", "failed", "irrelevant"}
    finally:
        command.upgrade(migrated, "head")
    command.downgrade(migrated, "0002")
    try:
        assert "pipeline_task" not in inspect(engine).get_table_names(schema=SCHEMA)
        columns = {
            column["name"] for column in inspect(engine).get_columns("raw_document", schema=SCHEMA)
        }
        assert not {"parser_version", "doc_type", "transcript_key"} & columns
    finally:
        command.upgrade(migrated, "head")
    command.downgrade(migrated, "0001")
    try:
        names = {column["name"] for column in inspect(engine).get_columns("source", schema=SCHEMA)}
        assert "name" not in names
        indexes = {
            index["name"] for index in inspect(engine).get_indexes("raw_document", schema=SCHEMA)
        }
        assert "ix_raw_document_source_url" not in indexes
    finally:
        command.upgrade(migrated, "head")
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
