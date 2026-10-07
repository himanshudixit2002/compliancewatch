"""audit.event: the regulatory and export read scopes

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-07

Two policies on ``audit.event``, both FOR SELECT, so neither admits a write
(py_common.audit.schema, ``create_audit_read_policies``):

- ``event_platform_read`` admits the rows of no tenant, platform-wide actions such as a publish
  or a fan-out control, while the transaction's ``app.audit_scope`` is ``regulatory``;
- ``event_export_read`` admits every row while it is ``export``.

Permissive policies combine with OR, so a session that names a tenant and the regulatory scope
reads that tenant's rows and the platform's, and still no other tenant's. Only identity sets the
scope, after its own role checks: the audit trail route (``GET /v1/identity/audit``) for the
regulatory team, and ``identity-admin audit-export``. Among the service roles only cw_identity
may SELECT the table (infra/dev/postgres/roles.sql), so a writer's role reads nothing whatever
it sets.

Expand-only: new policies on an existing table. The downgrade drops them, and the rows of no
tenant are readable by nobody again.
"""

from collections.abc import Sequence

from alembic import op

from py_common.audit.schema import create_audit_read_policies, drop_audit_read_policies

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    create_audit_read_policies(op)


def downgrade() -> None:
    drop_audit_read_policies(op)
