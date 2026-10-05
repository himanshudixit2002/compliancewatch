"""Alembic helpers for the two guards tenant tables repeat: row-level security and append-only.

A service migration calls them after it creates a table; each has a ``drop_*`` twin for the
downgrade. Table names are unqualified, like every table in the service migrations: the
``search_path`` puts them in the service's schema. A table outside that schema, such as
``audit.event``, which identity's migration creates, is named with ``schema=``.

- ``enable_tenant_rls(op, table)`` enables and forces row-level security and creates the
  ``<table>_tenant_isolation`` policy for all commands, whose USING and WITH CHECK compare
  ``tenant_id`` with the ``app.tenant_id`` setting the unit of work sets per transaction. FORCE
  makes the table owner obey the policy too, so tests and migrations run under the same rule.
  NULLIF against '' because once a session has used the setting, Postgres reports it as an
  empty string between transactions, and ``''::uuid`` would fail instead of matching nothing.
- ``create_append_only_guard(op, table)`` adds a BEFORE UPDATE OR DELETE trigger that raises
  ``restrict_violation``, calling a trigger function local to the schema,
  ``<schema>_append_only()`` (the pattern of rulebook migration 0004). With
  ``allow_erasure_delete`` it calls ``<schema>_append_only_erasable()`` instead, which lets a
  DELETE through only while the transaction has set ``app.erasure`` to ``on``, so a tenant's
  erasure can remove the rows; UPDATE is refused either way. Every table of a schema shares its
  function: the helper creates it, or replaces it with the same body, and the drop twin removes
  it once no trigger calls it any more. ``schema=`` names the table's schema, where the function
  lives too.

The catalog lint (``make migrations-catalog``, infra/scripts/check_migrations.py) checks the
policies these helpers create.
"""

import re

from alembic.operations import Operations
from sqlalchemy import text

TENANT_SETTING = "app.tenant_id"
"""The setting the tenant policy reads; the unit of work sets it per transaction."""

ERASURE_SETTING = "app.erasure"
"""Set to ``on`` for one transaction by a tenant erasure, which may then delete guarded rows."""

TENANT_MATCH = f"tenant_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid"

_IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]{0,62}")

_REFUSE = """
  RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = 'restrict_violation';"""

_ERASURE_DELETE = f"""
  IF TG_OP = 'DELETE' AND current_setting('{ERASURE_SETTING}', true) = 'on' THEN
    RETURN OLD;
  END IF;"""


def _identifier(name: str, what: str) -> str:
    """``name`` when it is a plain lower-case SQL identifier, which needs no quoting."""
    if not _IDENTIFIER.fullmatch(name):
        raise ValueError(f"{what} must be a lower-case SQL identifier, got {name!r}")
    return name


def _qualified(table: str, schema: str | None) -> str:
    """``table``, or ``schema.table`` when a schema is named."""
    name = _identifier(table, "table")
    return name if schema is None else f"{_identifier(schema, 'schema')}.{name}"


def tenant_policy_name(table: str) -> str:
    return f"{_identifier(table, 'table')}_tenant_isolation"


def append_only_trigger_name(table: str) -> str:
    return f"tr_{_identifier(table, 'table')}_append_only"


def append_only_function_name(schema: str, *, allow_erasure_delete: bool = False) -> str:
    """The trigger function of one schema, qualified: ``<schema>.<schema>_append_only``."""
    name = _identifier(schema, "schema")
    suffix = "_append_only_erasable" if allow_erasure_delete else "_append_only"
    return f"{name}.{name}{suffix}"


def enable_tenant_rls(op: Operations, table: str, *, schema: str | None = None) -> None:
    """Force row-level security on ``table`` and admit only the rows of the current tenant.
    ``schema`` names the table's schema when it is not the migration's own."""
    name = _qualified(table, schema)
    op.execute(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {tenant_policy_name(table)} ON {name} "
        f"USING ({TENANT_MATCH}) WITH CHECK ({TENANT_MATCH})"
    )


def drop_tenant_rls(op: Operations, table: str, *, schema: str | None = None) -> None:
    """Reverse ``enable_tenant_rls``: drop the policy and turn row-level security off."""
    name = _qualified(table, schema)
    op.execute(f"DROP POLICY IF EXISTS {tenant_policy_name(table)} ON {name}")
    op.execute(f"ALTER TABLE {name} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {name} DISABLE ROW LEVEL SECURITY")


def create_append_only_guard(
    op: Operations, table: str, *, allow_erasure_delete: bool = False, schema: str | None = None
) -> None:
    """Refuse UPDATE and DELETE on ``table``; with ``allow_erasure_delete``, DELETE is allowed
    while ``app.erasure`` is ``on``. ``schema`` names the schema of the table and of its trigger
    function; without it the table is found on the ``search_path`` and the function lives in
    the connection's current schema."""
    function = append_only_function_name(
        _schema(op, schema), allow_erasure_delete=allow_erasure_delete
    )
    body = (_ERASURE_DELETE if allow_erasure_delete else "") + _REFUSE
    op.execute(
        f"CREATE OR REPLACE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql AS $$\n"
        f"BEGIN{body}\nEND\n$$"
    )
    op.execute(
        f"CREATE TRIGGER {append_only_trigger_name(table)} BEFORE UPDATE OR DELETE ON "
        f"{_qualified(table, schema)} FOR EACH ROW EXECUTE FUNCTION {function}()"
    )


def drop_append_only_guard(
    op: Operations, table: str, *, allow_erasure_delete: bool = False, schema: str | None = None
) -> None:
    """Reverse ``create_append_only_guard``: drop the trigger, and the schema's function once no
    other trigger calls it."""
    function = append_only_function_name(
        _schema(op, schema), allow_erasure_delete=allow_erasure_delete
    )
    op.execute(
        f"DROP TRIGGER IF EXISTS {append_only_trigger_name(table)} ON {_qualified(table, schema)}"
    )
    op.execute(
        "DO $$\nBEGIN\n"
        f"  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgfoid = "
        f"to_regprocedure('{function}()')) THEN\n"
        f"    DROP FUNCTION IF EXISTS {function}();\n"
        "  END IF;\nEND\n$$"
    )


def _schema(op: Operations, schema: str | None) -> str:
    """The schema the trigger function lives in: the one given, or the current schema of the
    migration's connection (the first on its ``search_path``)."""
    if schema is not None:
        return _identifier(schema, "schema")
    if op.get_context().as_sql:
        raise ValueError("offline (--sql) migrations must pass schema= to the append-only guard")
    current: object = op.get_bind().execute(text("SELECT current_schema()")).scalar()
    if not isinstance(current, str):
        raise ValueError("the connection has no current schema; set search_path first")
    return _identifier(current, "schema")
