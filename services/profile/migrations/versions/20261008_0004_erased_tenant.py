"""erased_tenant: the tenants the profile has erased

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-08

Expand-only: a new table that nothing before this release reads. The profile's erasure writes one
row per tenant it erased (tenant_id, erased_at, deletion_event_id) in the transaction of the erasure
(py_common.erasure). Its routes answer an erased tenant 410 tenant-erased. No row-level security:
every session, of any tenant or none, must see the marker (the lint exemption *.erased_tenant). The
downgrade drops it, and with it what keeps an erased tenant's late events and tokens out.
"""

from collections.abc import Sequence

from alembic import op

from py_common.erasure import create_erased_tenant_table, drop_erased_tenant_table

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    create_erased_tenant_table(op)


def downgrade() -> None:
    drop_erased_tenant_table(op)
