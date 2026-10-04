"""audit.event: the audit log every service writes, append-only

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-04

Identity owns the audit log (guide sections 9 and 16): one row per audited action, which every
service writes in the transaction of the action through py_common.audit. The table lives in the
schema ``audit`` rather than ``identity`` because every service writes to it. The migration
creates the schema when it is missing (infra/dev/postgres/init.sql makes it in the dev stack),
and the downgrade drops the table and keeps the schema.

Expand-only: a new table, which nothing reads before this release. Its shape is
py_common.audit.schema's (``create_audit_table``):

- indexes on (tenant_id, occurred_at) and (action, occurred_at);
- forced row-level security: ``event_tenant_isolation``, the tenant policy of
  py_common.migrations.enable_tenant_rls, admits the rows of the tenant ``app.tenant_id`` names,
  to read and to write; ``event_platform_insert`` lets a session insert a row of no tenant, a
  platform-wide action. No policy reads the rows of no tenant: a route scoped to the regulatory
  team will (not built yet). tenant_id may be null, so infra/scripts/migration_lint.toml exempts
  the table and says why;
- a trigger that refuses UPDATE and DELETE (py_common.migrations.create_append_only_guard,
  without the erasure exception): rows outlive a tenant's erasure, which will pseudonymise them
  (not built yet).
"""

from collections.abc import Sequence

from alembic import op

from py_common.audit.schema import create_audit_table, drop_audit_table

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    create_audit_table(op)


def downgrade() -> None:
    drop_audit_table(op)
