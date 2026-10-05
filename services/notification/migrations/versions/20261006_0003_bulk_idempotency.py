"""idempotency keys for the bulk notification route

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-06

Expand-only: ``idempotency_key`` from ``py_common.idempotency`` for ``POST
/v1/notification/bulk``, which answers a retry with the same key and body with its first answer
for 24 hours. Row-level security is forced with the tenant policy, beside the purge policy of the
daily purge. Nothing that runs today reads the table. The downgrade drops it with the keys it
holds; a retry after that runs its request again, and the change cards' dedupe keys still queue
nothing twice.
"""

from collections.abc import Sequence

from alembic import op

from py_common.idempotency.schema import create_idempotency_table, drop_idempotency_table

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    create_idempotency_table(op)


def downgrade() -> None:
    drop_idempotency_table(op)
