"""erased_tenant: the tenants the obligation has erased

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-08

Expand-only: a new table that nothing before this release reads. The obligation's erasure writes one
row per tenant it erased (tenant_id, erased_at, deletion_event_id) in the transaction of the erasure
(py_common.erasure). Its routes answer an erased tenant 410 tenant-erased, and its consumer of
applicability.decided writes nothing for one. No row-level security: every session, of any tenant or
none, must see the marker (the lint exemption *.erased_tenant). The downgrade drops it, and with it
what keeps an erased tenant's late events and tokens out.
"""

from collections.abc import Sequence

from alembic import op

from py_common.erasure import create_erased_tenant_table, drop_erased_tenant_table

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    create_erased_tenant_table(op)


def downgrade() -> None:
    drop_erased_tenant_table(op)
