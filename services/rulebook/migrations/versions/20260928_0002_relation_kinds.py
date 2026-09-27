"""rule_relation: seven relation kinds (corrects, withdraws)

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-28

Expand-only: the vocabulary check on rule_relation.relation grows from five kinds to seven and
the pairing check names the two new kinds as rule-version-only, matching the kernel's
RelationKind and RULE_VERSION_ONLY (ADR-015). Existing rows satisfy both new constraints. The
downgrade restores the five-kind checks and fails while a row uses corrects or withdraws.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = ("supersedes", "amends", "refers_to", "exempts", "extends_deadline")
NEW_KINDS = (*OLD_KINDS, "corrects", "withdraws")
OLD_RULE_VERSION_ONLY = ("supersedes", "extends_deadline")
NEW_RULE_VERSION_ONLY = (*OLD_RULE_VERSION_ONLY, "corrects", "withdraws")


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _swap_checks(kinds: tuple[str, ...], rule_version_only: tuple[str, ...]) -> None:
    op.drop_constraint("ck_rule_relation_relation", "rule_relation", type_="check")
    op.drop_constraint("ck_rule_relation_pairing", "rule_relation", type_="check")
    op.create_check_constraint(
        "ck_rule_relation_relation", "rule_relation", f"relation IN ({_quoted(kinds)})"
    )
    op.create_check_constraint(
        "ck_rule_relation_pairing",
        "rule_relation",
        f"relation NOT IN ({_quoted(rule_version_only)}) OR to_kind = 'rule_version'",
    )


def upgrade() -> None:
    _swap_checks(NEW_KINDS, NEW_RULE_VERSION_ONLY)
    op.execute(
        sa.text(
            "COMMENT ON COLUMN rule_relation.relation IS "
            "'One of supersedes, amends, refers_to, exempts, extends_deadline, corrects, withdraws'"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("COMMENT ON COLUMN rule_relation.relation IS NULL"))
    _swap_checks(OLD_KINDS, OLD_RULE_VERSION_ONLY)
