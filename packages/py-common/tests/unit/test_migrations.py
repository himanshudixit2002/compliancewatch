"""The migration helpers emit the SQL they promise; rendered offline, as ``alembic --sql`` does.
Their behaviour on Postgres is checked in tests/integration/test_migrations_postgres.py."""

import io
import re
from collections.abc import Callable

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations

from py_common.migrations import (
    TENANT_MATCH,
    append_only_function_name,
    append_only_trigger_name,
    create_append_only_guard,
    drop_append_only_guard,
    drop_tenant_rls,
    enable_tenant_rls,
    tenant_policy_name,
)

TABLE = "obligation_change"
SCHEMA = "obligation"


def emitted(step: Callable[[Operations], None]) -> str:
    """The SQL ``step`` emits, whitespace collapsed. The named paramstyle is what the services'
    migrations/env.py uses offline; the default one would double every % sign."""
    buffer = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        dialect_opts={"paramstyle": "named"},
        opts={"as_sql": True, "output_buffer": buffer},
    )
    step(Operations(context))
    return re.sub(r"[ \t]+", " ", buffer.getvalue())


def test_tenant_rls_enables_and_forces_it_with_the_nullif_policy() -> None:
    sql = emitted(lambda op: enable_tenant_rls(op, TABLE))
    assert "ALTER TABLE obligation_change ENABLE ROW LEVEL SECURITY;" in sql
    assert "ALTER TABLE obligation_change FORCE ROW LEVEL SECURITY;" in sql
    assert (
        "CREATE POLICY obligation_change_tenant_isolation ON obligation_change "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);"
    ) in sql
    assert tenant_policy_name(TABLE) == "obligation_change_tenant_isolation"
    assert sql.count(TENANT_MATCH) == 2


def test_a_table_of_another_schema_is_named_with_it() -> None:
    sql = emitted(lambda op: enable_tenant_rls(op, "event", schema="audit"))
    assert "ALTER TABLE audit.event ENABLE ROW LEVEL SECURITY;" in sql
    assert "ALTER TABLE audit.event FORCE ROW LEVEL SECURITY;" in sql
    assert "CREATE POLICY event_tenant_isolation ON audit.event USING (" in sql
    dropped = [
        line
        for line in emitted(lambda op: drop_tenant_rls(op, "event", schema="audit")).splitlines()
        if line.strip()
    ]
    assert dropped == [
        "DROP POLICY IF EXISTS event_tenant_isolation ON audit.event;",
        "ALTER TABLE audit.event NO FORCE ROW LEVEL SECURITY;",
        "ALTER TABLE audit.event DISABLE ROW LEVEL SECURITY;",
    ]


def test_drop_tenant_rls_reverses_it() -> None:
    sql = emitted(lambda op: drop_tenant_rls(op, TABLE))
    statements = [line for line in sql.splitlines() if line.strip()]
    assert statements == [
        "DROP POLICY IF EXISTS obligation_change_tenant_isolation ON obligation_change;",
        "ALTER TABLE obligation_change NO FORCE ROW LEVEL SECURITY;",
        "ALTER TABLE obligation_change DISABLE ROW LEVEL SECURITY;",
    ]


def test_append_only_guard_refuses_update_and_delete_through_the_schema_function() -> None:
    sql = emitted(lambda op: create_append_only_guard(op, TABLE, schema=SCHEMA))
    assert (
        "CREATE OR REPLACE FUNCTION obligation.obligation_append_only() RETURNS trigger "
        "LANGUAGE plpgsql AS $$"
    ) in sql
    assert (
        "RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = 'restrict_violation';"
    ) in sql
    assert "app.erasure" not in sql
    assert (
        "CREATE TRIGGER tr_obligation_change_append_only BEFORE UPDATE OR DELETE ON "
        "obligation.obligation_change FOR EACH ROW EXECUTE FUNCTION "
        "obligation.obligation_append_only();"
    ) in sql


def test_erasure_variant_lets_only_a_delete_through_while_app_erasure_is_on() -> None:
    sql = emitted(
        lambda op: create_append_only_guard(op, TABLE, allow_erasure_delete=True, schema=SCHEMA)
    )
    function = "obligation.obligation_append_only_erasable"
    assert f"CREATE OR REPLACE FUNCTION {function}() RETURNS trigger" in sql
    assert "IF TG_OP = 'DELETE' AND current_setting('app.erasure', true) = 'on' THEN" in sql
    assert "RETURN OLD;" in sql
    assert sql.index("RETURN OLD;") < sql.index("RAISE EXCEPTION")
    assert f"FOR EACH ROW EXECUTE FUNCTION {function}();" in sql
    assert append_only_function_name(SCHEMA, allow_erasure_delete=True) == function


@pytest.mark.parametrize("allow_erasure_delete", [False, True])
def test_drop_append_only_guard_drops_the_trigger_and_an_unused_function(
    allow_erasure_delete: bool,
) -> None:
    sql = emitted(
        lambda op: drop_append_only_guard(
            op, TABLE, allow_erasure_delete=allow_erasure_delete, schema=SCHEMA
        )
    )
    function = append_only_function_name(SCHEMA, allow_erasure_delete=allow_erasure_delete)
    assert sql.startswith(
        f"DROP TRIGGER IF EXISTS {append_only_trigger_name(TABLE)} ON obligation.obligation_change;"
    )
    assert f"tgfoid = to_regprocedure('{function}()')" in sql
    assert f"DROP FUNCTION IF EXISTS {function}();" in sql


@pytest.mark.parametrize(
    "bad", ["Obligation", "obligation change", "obligation;drop", "1table", "", "x" * 64]
)
def test_names_must_be_plain_identifiers(bad: str) -> None:
    with pytest.raises(ValueError, match="identifier"):
        emitted(lambda op: enable_tenant_rls(op, bad))
    with pytest.raises(ValueError, match="identifier"):
        emitted(lambda op: create_append_only_guard(op, TABLE, schema=bad))
    with pytest.raises(ValueError, match="identifier"):
        emitted(lambda op: enable_tenant_rls(op, TABLE, schema=bad))


def test_offline_migrations_must_name_the_schema() -> None:
    with pytest.raises(ValueError, match="schema="):
        emitted(lambda op: create_append_only_guard(op, TABLE))
