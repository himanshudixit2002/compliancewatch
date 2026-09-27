"""The knowledge schema migration against a real Postgres.

Marked ``integration`` by the root conftest (directory name); needs Docker. One container per
module, the pgvector image the dev stack uses, and the ``rulebook`` schema created up front the
way infra/dev/postgres/init.sql does it. Alembic runs the way ``make migrate`` runs it: the URL
carries the search_path and CW_DB_SCHEMA names the schema that holds alembic_version.
"""

from collections.abc import Iterator, Sequence
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Engine, create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from testcontainers.community.postgres import PostgresContainer

from rulebook.infrastructure.models import (
    ENTITY_TYPES,
    RELATION_KINDS,
    TARGET_KINDS,
    Base,
    CanonicalEntityRow,
    ClauseEntityRow,
    RuleRelationRow,
)

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "rulebook"
KNOWLEDGE_TABLES = {"canonical_entity", "clause_entity", "rule_relation"}
ALL_TABLES = KNOWLEDGE_TABLES | {"alembic_version"}


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    with PostgresContainer(IMAGE, driver="psycopg") as postgres:
        base_url = postgres.get_connection_url()
        admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
        admin.dispose()
        yield f"{base_url}?options=-csearch_path%3D{SCHEMA}%2Cpublic"


@pytest.fixture(scope="module")
def alembic_config(database_url: str) -> Iterator[Config]:
    with pytest.MonkeyPatch.context() as env:
        env.setenv("CW_DATABASE_URL", database_url)
        env.setenv("CW_DB_SCHEMA", SCHEMA)
        yield Config(str(SERVICE_DIR / "alembic.ini"))


@pytest.fixture(scope="module")
def engine(database_url: str) -> Iterator[Engine]:
    engine = create_engine(database_url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def migrated(alembic_config: Config) -> Config:
    command.upgrade(alembic_config, "head")
    return alembic_config


def _table_names(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names(schema=SCHEMA))


def _insert(engine: Engine, *rows: Base) -> None:
    """Commit the rows; instances stay readable afterwards (no expiry on commit)."""
    with Session(engine, expire_on_commit=False) as session, session.begin():
        session.add_all(rows)


def _delete_entity(engine: Engine, entity_id: UUID) -> None:
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM canonical_entity WHERE id = :id"), {"id": entity_id})


def _entity(entity_type: str, aliases: list[str] | None = None) -> CanonicalEntityRow:
    return CanonicalEntityRow(
        id=uuid4(),
        type=entity_type,
        canonical_name=f"{entity_type}-{uuid4().hex[:8]}",
        aliases=aliases if aliases is not None else [],
    )


def _mention(entity: CanonicalEntityRow, span_start: int, span_end: int) -> ClauseEntityRow:
    return ClauseEntityRow(
        clause_id=uuid4(),
        entity_id=entity.id,
        mention_text=entity.canonical_name,
        span_start=span_start,
        span_end=span_end,
    )


def _relation(entity: CanonicalEntityRow, kind: str, to_kind: str) -> RuleRelationRow:
    return RuleRelationRow(
        id=uuid4(),
        from_rule_version_id=uuid4(),
        relation=kind,
        to_kind=to_kind,
        to_ref=entity.canonical_name,
        to_entity_id=entity.id,
        clause_id=uuid4(),
    )


def test_upgrade_head_creates_the_knowledge_tables(migrated: Config, engine: Engine) -> None:
    assert _table_names(engine) == ALL_TABLES
    with engine.connect() as connection:
        version: str = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
    assert version == "0002"


def test_indexes_by_name_and_access_method(migrated: Config, engine: Engine) -> None:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT tablename, indexname, indexdef FROM pg_indexes"
                " WHERE schemaname = :schema ORDER BY indexname"
            ),
            {"schema": SCHEMA},
        ).all()
    by_table: dict[str, set[str]] = {}
    definitions: dict[str, str] = {}
    for table, name, definition in rows:
        by_table.setdefault(table, set()).add(name)
        definitions[name] = definition
    assert by_table["canonical_entity"] == {
        "pk_canonical_entity",
        "uq_canonical_entity_type_canonical_name",
        "ix_canonical_entity_aliases",
    }
    assert by_table["clause_entity"] == {"pk_clause_entity", "ix_clause_entity_entity"}
    assert by_table["rule_relation"] == {
        "pk_rule_relation",
        "uq_rule_relation_edge",
        "ix_rule_relation_target",
        "ix_rule_relation_source",
    }
    assert "USING gin (aliases)" in definitions["ix_canonical_entity_aliases"]
    assert "USING btree (entity_id)" in definitions["ix_clause_entity_entity"]
    assert "USING btree (relation, to_ref)" in definitions["ix_rule_relation_target"]
    assert "USING btree (from_rule_version_id)" in definitions["ix_rule_relation_source"]


def test_check_constraints_carry_the_fixed_vocabulary(migrated: Config, engine: Engine) -> None:
    inspector = inspect(engine)

    def checks(table: str) -> dict[str, str]:
        return {
            str(check["name"]): check["sqltext"]
            for check in inspector.get_check_constraints(table, schema=SCHEMA)
        }

    entity_checks = checks("canonical_entity")
    assert set(entity_checks) == {"ck_canonical_entity_type"}
    for entity_type in ENTITY_TYPES:
        assert f"'{entity_type}'" in entity_checks["ck_canonical_entity_type"]

    mention_checks = checks("clause_entity")
    assert set(mention_checks) == {"ck_clause_entity_span_start", "ck_clause_entity_span_end"}
    assert "span_start >= 0" in mention_checks["ck_clause_entity_span_start"]
    assert "span_end > span_start" in mention_checks["ck_clause_entity_span_end"]

    relation_checks = checks("rule_relation")
    assert set(relation_checks) == {
        "ck_rule_relation_relation",
        "ck_rule_relation_to_kind",
        "ck_rule_relation_pairing",
        "ck_rule_relation_target_entity",
        "ck_rule_relation_not_self",
    }
    for relation in RELATION_KINDS:
        assert f"'{relation}'" in relation_checks["ck_rule_relation_relation"]
    for to_kind in TARGET_KINDS:
        assert f"'{to_kind}'" in relation_checks["ck_rule_relation_to_kind"]
    assert len(TARGET_KINDS) == 11

    assert len(RELATION_KINDS) == 7
    assert "'corrects'" in relation_checks["ck_rule_relation_relation"]
    assert "'withdraws'" in relation_checks["ck_rule_relation_relation"]
    pairing = relation_checks["ck_rule_relation_pairing"]
    for kind in ("supersedes", "extends_deadline", "corrects", "withdraws"):
        assert f"'{kind}'" in pairing
    assert "'amends'" not in pairing
    assert "'rule_version'" in pairing
    target = relation_checks["ck_rule_relation_target_entity"]
    assert "'rule_version'" in target
    assert "to_entity_id IS NULL" in target
    not_self = relation_checks["ck_rule_relation_not_self"]
    assert "NOT" in not_self
    assert "to_ref = from_rule_version_id::text" in not_self


def test_keys_unique_constraints_and_deferred_foreign_keys(
    migrated: Config, engine: Engine
) -> None:
    inspector = inspect(engine)

    def primary_key(table: str) -> list[str]:
        return inspector.get_pk_constraint(table, schema=SCHEMA)["constrained_columns"]

    def uniques(table: str) -> dict[str, list[str]]:
        return {
            str(unique["name"]): unique["column_names"]
            for unique in inspector.get_unique_constraints(table, schema=SCHEMA)
        }

    assert primary_key("canonical_entity") == ["id"]
    assert primary_key("clause_entity") == ["clause_id", "entity_id", "span_start"]
    assert primary_key("rule_relation") == ["id"]

    assert uniques("canonical_entity") == {
        "uq_canonical_entity_type_canonical_name": ["type", "canonical_name"]
    }
    assert uniques("clause_entity") == {}
    assert uniques("rule_relation") == {
        "uq_rule_relation_edge": [
            "from_rule_version_id",
            "relation",
            "to_kind",
            "to_ref",
            "clause_id",
        ]
    }

    mention_fks = inspector.get_foreign_keys("clause_entity", schema=SCHEMA)
    assert [fk["name"] for fk in mention_fks] == ["fk_clause_entity_entity_id_canonical_entity"]
    assert mention_fks[0]["constrained_columns"] == ["entity_id"]
    assert mention_fks[0]["referred_table"] == "canonical_entity"
    assert mention_fks[0]["options"] == {"ondelete": "RESTRICT"}

    relation_fks = inspector.get_foreign_keys("rule_relation", schema=SCHEMA)
    assert [fk["name"] for fk in relation_fks] == ["fk_rule_relation_to_entity_id_canonical_entity"]
    assert relation_fks[0]["constrained_columns"] == ["to_entity_id"]
    assert relation_fks[0]["options"] == {"ondelete": "RESTRICT"}

    for table in ("clause_entity", "rule_relation"):
        comment = inspector.get_table_comment(table, schema=SCHEMA)["text"]
        assert comment is not None
        assert "no foreign key" in comment


def test_models_and_migration_agree(migrated: Config, engine: Engine) -> None:
    # Autogenerate compares tables, columns, types, nullability, server defaults, indexes,
    # unique constraints and foreign keys. It does not compare CHECK constraint bodies, so the
    # inspector-based vocabulary test above is the guard for those.
    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection, opts={"compare_type": True, "compare_server_default": True}
        )
        assert compare_metadata(context, Base.metadata) == []


def test_insert_entity_mention_and_relation_then_query(migrated: Config, engine: Engine) -> None:
    entity = CanonicalEntityRow(
        id=uuid4(),
        type="notification",
        canonical_name="17/2026-central tax",
        aliases=["Notification No. 17/2026-Central Tax", "Notfn. 17/2026-CT"],
    )
    bare = _entity("form")
    clause_id = uuid4()
    from_version = uuid4()
    superseded_version = uuid4()
    _insert(
        engine,
        entity,
        bare,
        ClauseEntityRow(
            clause_id=clause_id,
            entity_id=entity.id,
            mention_text="Notification No. 17/2026-Central Tax",
            span_start=12,
            span_end=48,
        ),
        RuleRelationRow(
            id=uuid4(),
            from_rule_version_id=from_version,
            relation="supersedes",
            to_kind="rule_version",
            to_ref=str(superseded_version),
            to_entity_id=None,
            clause_id=clause_id,
        ),
        RuleRelationRow(
            id=uuid4(),
            from_rule_version_id=from_version,
            relation="refers_to",
            to_kind="notification",
            to_ref=entity.canonical_name,
            to_entity_id=entity.id,
            clause_id=clause_id,
        ),
    )

    with engine.connect() as connection:
        by_alias: Sequence[UUID] = (
            connection.execute(
                text(
                    "SELECT id FROM canonical_entity WHERE aliases @> ARRAY[CAST(:alias AS text)]"
                ),
                {"alias": "Notfn. 17/2026-CT"},
            )
            .scalars()
            .all()
        )
        assert by_alias == [entity.id]

        by_target = connection.execute(
            text(
                "SELECT from_rule_version_id, to_entity_id FROM rule_relation"
                " WHERE relation = :relation AND to_ref = :to_ref"
            ),
            {"relation": "refers_to", "to_ref": "17/2026-central tax"},
        ).all()
        assert [tuple(row) for row in by_target] == [(from_version, entity.id)]

        superseded = connection.execute(
            select(RuleRelationRow.to_ref).where(
                RuleRelationRow.from_rule_version_id == from_version,
                RuleRelationRow.relation == "supersedes",
            )
        ).scalar_one()
        assert UUID(superseded) == superseded_version

        stored = connection.execute(
            select(CanonicalEntityRow.aliases, CanonicalEntityRow.created_at).where(
                CanonicalEntityRow.id == bare.id
            )
        ).one()
        assert stored.aliases == []
        assert stored.created_at.tzinfo is not None

        span = connection.execute(
            select(ClauseEntityRow.span_start, ClauseEntityRow.span_end).where(
                ClauseEntityRow.clause_id == clause_id
            )
        ).one()
        assert tuple(span) == (12, 48)


def test_duplicate_type_and_canonical_name_is_rejected(migrated: Config, engine: Engine) -> None:
    first = CanonicalEntityRow(id=uuid4(), type="form", canonical_name="GSTR-3B")
    second = CanonicalEntityRow(id=uuid4(), type="form", canonical_name="GSTR-3B")
    with pytest.raises(IntegrityError, match="uq_canonical_entity_type_canonical_name"):
        _insert(engine, first, second)


@pytest.mark.parametrize(("span_start", "span_end"), [(5, 5), (5, 4), (-1, 3)])
def test_mention_span_must_be_ordered_and_non_negative(
    migrated: Config, engine: Engine, span_start: int, span_end: int
) -> None:
    entity = _entity("section")
    with pytest.raises(IntegrityError, match="ck_clause_entity_span"):
        _insert(engine, entity, _mention(entity, span_start, span_end))


def test_vocabulary_checks_reject_unknown_values(migrated: Config, engine: Engine) -> None:
    with pytest.raises(IntegrityError, match="ck_canonical_entity_type"):
        _insert(engine, _entity("colour"))

    entity = _entity("circular")
    _insert(engine, entity)
    with pytest.raises(IntegrityError, match="ck_rule_relation_relation"):
        _insert(engine, _relation(entity, "replaces", "circular"))
    with pytest.raises(IntegrityError, match="ck_rule_relation_to_kind"):
        _insert(engine, _relation(entity, "refers_to", "clause"))


@pytest.mark.parametrize("relation", ["supersedes", "extends_deadline"])
def test_rule_version_only_relations_cannot_target_an_entity(
    migrated: Config, engine: Engine, relation: str
) -> None:
    entity = _entity("form")
    _insert(engine, entity)
    with pytest.raises(IntegrityError, match="ck_rule_relation_pairing"):
        _insert(engine, _relation(entity, relation, "form"))


def test_to_entity_id_is_set_exactly_when_the_target_is_an_entity(
    migrated: Config, engine: Engine
) -> None:
    entity = _entity("section")
    _insert(engine, entity)
    with pytest.raises(IntegrityError, match="ck_rule_relation_target_entity"):
        _insert(
            engine,
            RuleRelationRow(
                id=uuid4(),
                from_rule_version_id=uuid4(),
                relation="amends",
                to_kind="rule_version",
                to_ref=str(uuid4()),
                to_entity_id=entity.id,
                clause_id=uuid4(),
            ),
        )
    with pytest.raises(IntegrityError, match="ck_rule_relation_target_entity"):
        _insert(
            engine,
            RuleRelationRow(
                id=uuid4(),
                from_rule_version_id=uuid4(),
                relation="refers_to",
                to_kind="section",
                to_ref=entity.canonical_name,
                to_entity_id=None,
                clause_id=uuid4(),
            ),
        )


def test_a_rule_version_cannot_relate_to_itself(migrated: Config, engine: Engine) -> None:
    version = uuid4()
    with pytest.raises(IntegrityError, match="ck_rule_relation_not_self"):
        _insert(
            engine,
            RuleRelationRow(
                id=uuid4(),
                from_rule_version_id=version,
                relation="supersedes",
                to_kind="rule_version",
                to_ref=str(version),
                to_entity_id=None,
                clause_id=uuid4(),
            ),
        )


def test_aliases_default_to_an_empty_array(migrated: Config, engine: Engine) -> None:
    entity = CanonicalEntityRow(id=uuid4(), type="state", canonical_name=f"state-{uuid4().hex[:8]}")
    _insert(engine, entity)
    with engine.connect() as connection:
        aliases = connection.execute(
            select(CanonicalEntityRow.aliases).where(CanonicalEntityRow.id == entity.id)
        ).scalar_one()
    assert aliases == []


def test_alias_lookup_uses_the_gin_index(migrated: Config, engine: Engine) -> None:
    alias = f"Notfn. {uuid4().hex[:6]}"
    _insert(engine, _entity("notification", aliases=[alias]))
    with engine.connect() as connection:
        connection.execute(text("SET LOCAL enable_seqscan = off"))
        plan_lines: Sequence[str] = (
            connection.execute(
                text(
                    "EXPLAIN SELECT id FROM canonical_entity"
                    " WHERE aliases @> ARRAY[CAST(:alias AS text)]"
                ),
                {"alias": alias},
            )
            .scalars()
            .all()
        )
    assert "ix_canonical_entity_aliases" in "\n".join(plan_lines)


def test_entity_referenced_by_a_mention_cannot_be_deleted(migrated: Config, engine: Engine) -> None:
    entity = _entity("hsn_code")
    _insert(engine, entity, _mention(entity, 0, 4))
    with pytest.raises(IntegrityError, match="fk_clause_entity_entity_id_canonical_entity"):
        _delete_entity(engine, entity.id)


def test_downgrade_to_base_drops_everything_and_upgrade_restores_it(
    migrated: Config, engine: Engine
) -> None:
    command.downgrade(migrated, "base")
    assert _table_names(engine) == {"alembic_version"}
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM alembic_version")).scalar_one() == 0

    command.upgrade(migrated, "head")
    assert _table_names(engine) == ALL_TABLES
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM canonical_entity")).scalar_one() == 0
