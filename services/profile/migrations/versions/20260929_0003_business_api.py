"""business api: idempotency keys for the creating routes, and the index the business list pages
on

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-29

``idempotency_key`` comes from py_common.idempotency (tenant policy forced, plus the purge policy
for expired rows). ``ix_profile_node_tenant_level_name`` serves ``GET /v1/businesses``, which
pages a tenant's entities by (name, id).
"""

from collections.abc import Sequence

from alembic import op

from py_common.idempotency.schema import create_idempotency_table, drop_idempotency_table

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NAME_INDEX = "ix_profile_node_tenant_level_name"


def upgrade() -> None:
    create_idempotency_table(op)
    op.create_index(NAME_INDEX, "profile_node", ["tenant_id", "level", "name", "id"])


def downgrade() -> None:
    op.drop_index(NAME_INDEX, table_name="profile_node")
    drop_idempotency_table(op)
