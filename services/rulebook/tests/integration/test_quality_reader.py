"""The data-quality reader on a migrated rulebook schema: the loaded seed calendar is clean, and
rows planted by SQL trip each check. Needs Docker."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.exc import IntegrityError
from testcontainers.community.postgres import PostgresContainer

import ontology as ontology_package
from domain_kernel.ontology import Ontology
from domain_kernel.status import RuleVersionStatus
from rulebook.application.quality import RunDataQualityChecks
from rulebook.application.seed_loader import load_calendar
from rulebook.domain.quality import QualityCheck
from rulebook.infrastructure.quality_reader import SqlQualityReader
from rulebook.infrastructure.seed_repository import SqlAlchemySeedRepository

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "rulebook"
SHA256 = "ab" * 32
DOCUMENT_ID = UUID(SHA256[:32])
CLAUSE_ID = uuid4()


@pytest.fixture(scope="module")
def base_url() -> Iterator[str]:
    with PostgresContainer(IMAGE, driver="psycopg") as postgres:
        url = postgres.get_connection_url()
        admin = create_engine(url, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
        admin.dispose()
        yield url


@pytest.fixture(scope="module")
def engine(base_url: str) -> Iterator[Engine]:
    database_url = f"{base_url}?options=-csearch_path%3D{SCHEMA}%2Cpublic"
    with pytest.MonkeyPatch.context() as env:
        env.setenv("CW_DATABASE_URL", database_url)
        env.setenv("CW_DB_SCHEMA", SCHEMA)
        command.upgrade(Config(str(SERVICE_DIR / "alembic.ini")), "head")
    engine = create_engine(database_url)
    SqlAlchemySeedRepository(engine).apply(
        load_calendar(ontology_package.load()), now=datetime(2026, 9, 29, tzinfo=UTC)
    )
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def ontology() -> Ontology:
    return ontology_package.load()


def version_id(connection: Connection, rule_key: str, version: int = 1) -> UUID:
    found: UUID = connection.execute(
        text(
            "SELECT rv.id FROM rule_version rv JOIN rule r ON r.id = rv.rule_id"
            " WHERE r.rule_key = :key AND rv.version = :version"
        ),
        {"key": rule_key, "version": version},
    ).scalar_one()
    return found


def test_the_seed_calendar_is_clean(engine: Engine, ontology: Ontology) -> None:
    reader = SqlQualityReader(engine)
    facts = reader.read()
    assert len(facts.versions) == 13
    assert {version.status for version in facts.versions} == {RuleVersionStatus.DRAFT}
    assert all(version.citations == 0 for version in facts.versions)
    assert facts.relations == ()
    # The job-work predicate of both ITC-04 rules names an attribute ontology 0.2.0 lacks; their
    # open analyst question keeps it on record without failing the check.
    assert {"itc04_half_yearly", "itc04_annual"} <= {
        version.rule_key for version in facts.versions if version.open_questions
    }
    report = RunDataQualityChecks(reader, ontology).run()
    assert report.ok, report.violations


def test_the_schema_argument_sets_the_search_path(base_url: str) -> None:
    reader = SqlQualityReader.from_url(base_url, schema=SCHEMA)
    assert len(reader.read().versions) == 13


def test_planted_rows_trip_each_check(engine: Engine, ontology: Ontology) -> None:
    with engine.begin() as connection:
        monthly = version_id(connection, "gstr3b_monthly")
        gstr1 = version_id(connection, "gstr1_monthly")
        connection.execute(
            text(
                "INSERT INTO document (id, source_id, sha256, regulator, doc_type, url, language,"
                " media_type, parser_version, fetched_at)"
                " VALUES (:id, :source, :sha, 'cbic', 'notification', 'https://example.invalid/n',"
                " 'en', 'application/pdf', 'pdf@1', now())"
            ),
            {"id": DOCUMENT_ID, "source": uuid4(), "sha": SHA256},
        )
        connection.execute(
            text(
                "INSERT INTO clause (id, document_id, clause_ref, ordinal, text, text_sha256)"
                " VALUES (:id, :document, 'en.p1', 1, 'clause text', :sha)"
            ),
            {"id": CLAUSE_ID, "document": DOCUMENT_ID, "sha": SHA256},
        )
        # gstr3b_monthly@1 in force with no citation; gstr1_monthly@1 with one of two verified.
        connection.execute(
            text("UPDATE rule_version SET status = 'published' WHERE id IN (:a, :b)"),
            {"a": monthly, "b": gstr1},
        )
        connection.execute(
            text(
                "INSERT INTO citation (id, rule_version_id, clause_id, quote, verified,"
                " match_score, verified_at) VALUES"
                " (:v, :rv, :clause, 'quoted', true, 0.95, now()),"
                " (:u, :rv, :clause, 'quoted too', false, NULL, NULL)"
            ),
            {"v": uuid4(), "u": uuid4(), "rv": gstr1, "clause": CLAUSE_ID},
        )
        # A second published version of gstr3b_monthly from 1 July: v1 was never closed.
        later = uuid4()
        connection.execute(
            text(
                "INSERT INTO rule_version (id, rule_id, version, status, title, specification,"
                " obligation_template, effective_from)"
                " SELECT :id, rule_id, 2, 'published', title, specification, obligation_template,"
                " DATE '2026-07-01' FROM rule_version WHERE id = :monthly"
            ),
            {"id": later, "monthly": monthly},
        )
        # v2 supersedes v1, and v1 corrects v2: a cycle.
        for source, relation, target in (
            (later, "supersedes", monthly),
            (monthly, "corrects", later),
        ):
            connection.execute(
                text(
                    "INSERT INTO rule_relation (id, from_rule_version_id, relation, to_kind,"
                    " to_ref, to_rule_version_id, clause_id)"
                    " VALUES (:id, :source, :relation, 'rule_version', :target_text, :target,"
                    " :clause)"
                ),
                {
                    "id": uuid4(),
                    "source": source,
                    "relation": relation,
                    "target_text": str(target),
                    "target": target,
                    "clause": CLAUSE_ID,
                },
            )
        connection.execute(
            text(
                "UPDATE rule_version SET specification ="
                ' \'{"attribute": "no_such_attribute", "operator": "eq", "value": "x"}\''
                " WHERE id = :id"
            ),
            {"id": version_id(connection, "gstr9_annual")},
        )

    # ck_rule_version_effective refuses disordered dates; the check stands behind it.
    with pytest.raises(IntegrityError, match="ck_rule_version_effective"), engine.begin() as c:
        c.execute(
            text("UPDATE rule_version SET effective_to = effective_from WHERE id = :id"),
            {"id": version_id(c, "eway_bill")},
        )
    with engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE rule_version DROP CONSTRAINT ck_rule_version_effective")
        )
        connection.execute(
            text("UPDATE rule_version SET effective_to = effective_from WHERE id = :id"),
            {"id": version_id(connection, "eway_bill")},
        )

    try:
        report = RunDataQualityChecks(SqlQualityReader(engine), ontology).run()
    finally:
        with engine.begin() as connection:
            connection.execute(text("UPDATE rule_version SET effective_to = NULL"))
            connection.execute(
                text(
                    "ALTER TABLE rule_version ADD CONSTRAINT ck_rule_version_effective"
                    " CHECK (effective_to IS NULL OR effective_to > effective_from)"
                )
            )

    assert report.versions_checked == 14
    assert report.relations_checked == 2
    found = {check: [(v.subject, v.detail) for v in report.of(check)] for check in QualityCheck}
    assert found[QualityCheck.IN_FORCE_WITHOUT_VERIFIED_CITATION] == [
        ("gstr1_monthly@1", "published with 1 of 2 citations not verified"),
        ("gstr3b_monthly@1", "published with no citation"),
        ("gstr3b_monthly@2", "published with no citation"),
    ]
    assert found[QualityCheck.OVERLAPPING_IN_FORCE_PERIODS] == [
        (
            "gstr3b_monthly@1 and gstr3b_monthly@2",
            "[2026-04-01, open) overlaps [2026-07-01, open)",
        )
    ]
    [(cycle, detail)] = found[QualityCheck.SUPERSESSION_CYCLE]
    nodes = cycle.split(" -> ")
    assert len(nodes) == 3
    assert nodes[0] == nodes[-1]
    assert sorted(nodes[:-1]) == ["gstr3b_monthly@1", "gstr3b_monthly@2"]
    assert detail == "2 versions replace each other in a cycle"
    assert found[QualityCheck.UNKNOWN_PREDICATE_ATTRIBUTE] == [
        ("gstr9_annual@1", f"not in ontology {ontology.version}: no_such_attribute")
    ]
    assert found[QualityCheck.EFFECTIVE_DATES_DISORDERED] == [
        ("eway_bill@1", "effective_to 2026-04-01 is not after effective_from 2026-04-01")
    ]
