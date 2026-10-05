"""applicability_decision: an index for the latest decision of a rule version per business

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-06

Hand-written; mirrors applicability_engine.infrastructure.models. Expand-only: one index.

``ix_applicability_decision_impact`` (tenant_id, rule_version_id, business_id, decided_at, id)
serves the impact of a change on a tenant (``GET /v1/changes/{rule_version_id}/impact``): the
latest decision of one rule version for each of the tenant's businesses, which the repository
reads with ``DISTINCT ON (business_id)`` from a backward scan of the index. The index on
(tenant_id, business_id, rule_version_id, decided_at) serves one business's decisions instead.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "applicability_decision"
INDEX = "ix_applicability_decision_impact"


def upgrade() -> None:
    op.create_index(
        INDEX, TABLE, ["tenant_id", "rule_version_id", "business_id", "decided_at", "id"]
    )


def downgrade() -> None:
    op.drop_index(INDEX, table_name=TABLE)
