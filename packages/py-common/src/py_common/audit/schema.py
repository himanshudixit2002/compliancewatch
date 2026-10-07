"""The ``audit.event`` table and the alembic helpers that create it.

Identity owns the table: its migration calls ``create_audit_table(op)``, and the downgrade
``drop_audit_table(op)``. Every service writes rows with ``py_common.audit.writer`` in the
transaction of the action they record; nothing updates or deletes one. The table is
schema-qualified (``audit.event``), unlike a service's own tables, because every service writes
to the one table.

- The schema ``audit`` is created when it is missing: ``infra/dev/postgres/init.sql`` makes it
  in the dev stack, the migration in every other environment. The downgrade keeps it.
- Indexes: (tenant_id, occurred_at) for a tenant's trail, (action, occurred_at) for one kind of
  action across tenants.
- Row-level security, enabled and forced. ``event_tenant_isolation``
  (``py_common.migrations.enable_tenant_rls``) admits the rows of the tenant ``app.tenant_id``
  names, to read and to write; ``event_platform_insert`` lets any session insert a row of no
  tenant, a platform-wide action. The migration lint exempts the table, whose tenant_id may be
  null (infra/scripts/migration_lint.toml).
- Read scopes (``create_audit_read_policies``, identity's migration 0006), both FOR SELECT only:
  ``event_platform_read`` admits the rows of no tenant while ``app.audit_scope`` is
  ``regulatory``, and ``event_export_read`` admits every row while it is ``export``. Permissive
  policies combine with OR, so a regulatory session that also names a tenant reads that tenant's
  rows and the platform's. Only identity sets the scope, after its own role checks (the audit
  trail route and ``identity-admin audit-export``), and only ``cw_identity`` holds SELECT on the
  table among the service roles (infra/dev/postgres/roles.sql); a writer's role reads nothing.
- Append-only: a trigger refuses UPDATE and DELETE (``create_append_only_guard`` without the
  erasure exception). Rows outlive a tenant's erasure, which will pseudonymise them rather than
  delete them (not built yet); the guide keeps them seven years (section 9).

A later change to the table goes in a helper of its own, called from a new migration, so
identity's migration keeps creating the table it created.
"""

from typing import Final

from alembic.operations import Operations
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Index,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql.schema import SchemaItem
from sqlalchemy.types import JSON

from domain_kernel.audit import (
    MAX_ACTION_CHARS,
    MAX_ACTOR_ID_CHARS,
    MAX_ACTOR_LABEL_CHARS,
    MAX_SUBJECT_ID_CHARS,
    MAX_SUBJECT_TYPE_CHARS,
    AuditActorKind,
)
from py_common.migrations import (
    create_append_only_guard,
    drop_append_only_guard,
    enable_tenant_rls,
)

AUDIT_SCHEMA: Final = "audit"
AUDIT_TABLE: Final = "event"
QUALIFIED_TABLE: Final = f"{AUDIT_SCHEMA}.{AUDIT_TABLE}"
TENANT_TIME_INDEX: Final = "ix_audit_event_tenant_time"
ACTION_TIME_INDEX: Final = "ix_audit_event_action_time"
PLATFORM_INSERT_POLICY: Final = "event_platform_insert"
PLATFORM_ROW: Final = "tenant_id IS NULL"
"""The WITH CHECK of ``event_platform_insert``: a row of no tenant."""
AUDIT_SCOPE_SETTING: Final = "app.audit_scope"
"""The setting the read policies compare: ``regulatory`` or ``export``; identity sets it per
transaction, after its own role checks."""
REGULATORY_SCOPE: Final = "regulatory"
EXPORT_SCOPE: Final = "export"
PLATFORM_READ_POLICY: Final = "event_platform_read"
EXPORT_READ_POLICY: Final = "event_export_read"
MAX_CORRELATION_ID_CHARS: Final = 64
ACTOR_KINDS: Final = tuple(kind.value for kind in AuditActorKind)
AUDIT_COMMENT: Final = (
    "The audit log: one row per audited action, written in the transaction of the action and "
    "never changed (a trigger refuses UPDATE and DELETE); kept seven years. Row-level security: "
    "a session reads and writes its tenant's rows and may add rows of no tenant."
)

metadata = MetaData()


def _state() -> JSON:
    """JSONB on Postgres, JSON elsewhere (SQLite in unit tests); None is SQL NULL."""
    return JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql")


def _columns() -> list[SchemaItem]:
    kinds = ", ".join(f"'{kind}'" for kind in ACTOR_KINDS)
    return [
        Column("id", Uuid(), nullable=False, comment="The entry id"),
        Column("occurred_at", DateTime(timezone=True), nullable=False),
        Column(
            "tenant_id",
            Uuid(),
            nullable=True,
            comment="The tenant whose data the action touched; null for a platform-wide action",
        ),
        Column(
            "action",
            String(MAX_ACTION_CHARS),
            nullable=False,
            comment="A dotted name, such as applicability.review.resolve",
        ),
        Column("subject_type", String(MAX_SUBJECT_TYPE_CHARS), nullable=False),
        Column("subject_id", String(MAX_SUBJECT_ID_CHARS), nullable=False),
        Column("actor_kind", String(16), nullable=False),
        Column(
            "actor_id",
            String(MAX_ACTOR_ID_CHARS),
            nullable=False,
            comment="A user id, a service client id, or the service that acted for nobody",
        ),
        Column(
            "actor_label",
            String(MAX_ACTOR_LABEL_CHARS),
            nullable=False,
            comment="A user's roles, service:<client> or system:<service>; never a name",
        ),
        Column("reason", Text(), nullable=False, server_default=""),
        Column("before", _state(), nullable=True, comment="The state the action changed"),
        Column("after", _state(), nullable=True, comment="The state the action left"),
        Column(
            "correlation_id",
            String(MAX_CORRELATION_ID_CHARS),
            nullable=True,
            comment="The request or event behind the action",
        ),
        PrimaryKeyConstraint("id", name="pk_audit_event"),
        CheckConstraint(f"actor_kind IN ({kinds})", name="ck_audit_event_actor_kind"),
    ]


audit_event = Table(AUDIT_TABLE, metadata, *_columns(), schema=AUDIT_SCHEMA, comment=AUDIT_COMMENT)
Index(TENANT_TIME_INDEX, audit_event.c.tenant_id, audit_event.c.occurred_at)
Index(ACTION_TIME_INDEX, audit_event.c.action, audit_event.c.occurred_at)


def create_audit_table(op: Operations) -> None:
    """Create the schema when missing, then ``audit.event`` with its indexes, its forced
    policies and its append-only trigger. Call from identity's migration."""
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {AUDIT_SCHEMA}")
    op.create_table(AUDIT_TABLE, *_columns(), schema=AUDIT_SCHEMA, comment=AUDIT_COMMENT)
    op.create_index(
        TENANT_TIME_INDEX, AUDIT_TABLE, ["tenant_id", "occurred_at"], schema=AUDIT_SCHEMA
    )
    op.create_index(ACTION_TIME_INDEX, AUDIT_TABLE, ["action", "occurred_at"], schema=AUDIT_SCHEMA)
    enable_tenant_rls(op, AUDIT_TABLE, schema=AUDIT_SCHEMA)
    op.execute(
        f"CREATE POLICY {PLATFORM_INSERT_POLICY} ON {QUALIFIED_TABLE} "
        f"FOR INSERT WITH CHECK ({PLATFORM_ROW})"
    )
    create_append_only_guard(op, AUDIT_TABLE, schema=AUDIT_SCHEMA)


def _scope_is(scope: str) -> str:
    return f"current_setting('{AUDIT_SCOPE_SETTING}', true) = '{scope}'"


def create_audit_read_policies(op: Operations) -> None:
    """The read scopes: the rows of no tenant under ``app.audit_scope = 'regulatory'``, every row
    under ``'export'``. Both FOR SELECT, so neither admits a write. Call from identity's
    migration 0006, after ``create_audit_table``."""
    op.execute(
        f"CREATE POLICY {PLATFORM_READ_POLICY} ON {QUALIFIED_TABLE} FOR SELECT "
        f"USING ({PLATFORM_ROW} AND {_scope_is(REGULATORY_SCOPE)})"
    )
    op.execute(
        f"CREATE POLICY {EXPORT_READ_POLICY} ON {QUALIFIED_TABLE} FOR SELECT "
        f"USING ({_scope_is(EXPORT_SCOPE)})"
    )


def drop_audit_read_policies(op: Operations) -> None:
    """Reverse ``create_audit_read_policies``."""
    op.execute(f"DROP POLICY IF EXISTS {EXPORT_READ_POLICY} ON {QUALIFIED_TABLE}")
    op.execute(f"DROP POLICY IF EXISTS {PLATFORM_READ_POLICY} ON {QUALIFIED_TABLE}")


def drop_audit_table(op: Operations) -> None:
    """Reverse ``create_audit_table``; the policies go with the table and the schema stays."""
    drop_append_only_guard(op, AUDIT_TABLE, schema=AUDIT_SCHEMA)
    op.drop_index(ACTION_TIME_INDEX, table_name=AUDIT_TABLE, schema=AUDIT_SCHEMA)
    op.drop_index(TENANT_TIME_INDEX, table_name=AUDIT_TABLE, schema=AUDIT_SCHEMA)
    op.drop_table(AUDIT_TABLE, schema=AUDIT_SCHEMA)
