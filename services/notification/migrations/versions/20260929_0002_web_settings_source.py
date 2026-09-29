"""channel_preference.source accepts web_settings (a change made on the web settings pages)

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-29

Expand-only: the check on channel_preference.source grows from four sources to five, matching
notification.domain.preferences.ConsentSource. Existing rows satisfy the wider check. The source
records how an opt-in or opt-out reached us, so the downgrade rewrites nothing: it restores the
four-source check and fails while a preference names web_settings.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "channel_preference"
CONSTRAINT = "ck_channel_preference_source"
OLD = ("whatsapp_keyword", "web_onboarding", "api", "support")
NEW = (*OLD, "web_settings")


def _swap_check(sources: tuple[str, ...]) -> None:
    op.drop_constraint(CONSTRAINT, TABLE, type_="check")
    op.create_check_constraint(
        CONSTRAINT,
        TABLE,
        f"source IS NULL OR source IN ({', '.join(f"'{source}'" for source in sources)})",
    )


def upgrade() -> None:
    _swap_check(NEW)


def downgrade() -> None:
    _swap_check(OLD)
