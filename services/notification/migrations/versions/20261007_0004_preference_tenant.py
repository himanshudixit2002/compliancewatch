"""channel_preference.set_for_tenant_id: the tenant a web opt-in or opt-out was given for

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-07

Expand-only: a nullable uuid column on channel_preference, and a check that only a web source
(web_onboarding, web_settings) names one. Preferences belong to no tenant and keep no row-level
security; the column only says which tenant's user set the row on the web, so that tenant's data
export may show it and no other tenant's does. Existing rows keep NULL: nobody can say which
tenant set them, so no export shows them. The downgrade drops the check and the column, and the
exports then show no preference at all until it is made again.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "channel_preference"
COLUMN = "set_for_tenant_id"
CHECK = "ck_channel_preference_set_for_tenant"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column(COLUMN, sa.Uuid(), nullable=True))
    op.create_check_constraint(
        CHECK, TABLE, f"{COLUMN} IS NULL OR source IN ('web_onboarding', 'web_settings')"
    )


def downgrade() -> None:
    op.drop_constraint(CHECK, TABLE, type_="check")
    op.drop_column(TABLE, COLUMN)
