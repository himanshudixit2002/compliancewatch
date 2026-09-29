"""consent_record.source accepts web_settings (a change made on the web settings pages)

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-29

Expand-only: the check on consent_record.source grows from four sources to five, matching
identity.domain.consent.ConsentSource. Existing rows satisfy the wider check. Consent records are
append-only evidence, so the downgrade deletes nothing: it restores the four-source check and
fails while a row names web_settings.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "consent_record"
CONSTRAINT = "ck_consent_record_source"
OLD = ("web_onboarding", "whatsapp_keyword", "api", "support")
NEW = (*OLD, "web_settings")


def _swap_check(sources: tuple[str, ...]) -> None:
    op.drop_constraint(CONSTRAINT, TABLE, type_="check")
    op.create_check_constraint(
        CONSTRAINT, TABLE, f"source IN ({', '.join(f"'{source}'" for source in sources)})"
    )


def upgrade() -> None:
    _swap_check(NEW)


def downgrade() -> None:
    _swap_check(OLD)
