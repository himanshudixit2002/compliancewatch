"""audit.event: an index on (subject_type, subject_id, occurred_at)

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-07

One subject's history, such as the admin screen's history of a rule version
(``GET /v1/identity/audit?subject_type=rule_version&subject_id=...``), reads through
``ix_audit_event_subject_time`` rather than scanning every row of seven years: the indexes on
(tenant_id, occurred_at) and (action, occurred_at) serve neither a filter by subject nor the
regulatory scope's ``tenant_id IS NULL OR tenant_id = <internal>`` well
(py_common.audit.schema, ``create_audit_subject_index``).

Expand-only: a new index on an existing table. ``CREATE INDEX`` locks writes to ``audit.event``
while it builds; the table is young, so that is brief. The downgrade drops the index.
"""

from collections.abc import Sequence

from alembic import op

from py_common.audit.schema import create_audit_subject_index, drop_audit_subject_index

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    create_audit_subject_index(op)


def downgrade() -> None:
    drop_audit_subject_index(op)
