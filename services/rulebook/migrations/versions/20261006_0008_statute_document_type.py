"""statute document type: ck_document_doc_type admits statute

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-06

Hand-written; mirrors rulebook.infrastructure.models. Expand only: the kernel's DocumentType gained
``statute`` (an Act or the Rules made under it, which an analyst uploads to the pipeline), so the
check on ``document.doc_type`` admits it. The image before this one never writes it; the
downgrade fails while a statute is stored, rather than dropping it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BEFORE = ("notification", "circular", "press_release", "act_amendment")
AFTER = (*BEFORE, "statute")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(f"'{value}'" for value in values)})"


def upgrade() -> None:
    op.drop_constraint("ck_document_doc_type", "document", type_="check")
    op.create_check_constraint("ck_document_doc_type", "document", _in_list("doc_type", AFTER))


def downgrade() -> None:
    op.drop_constraint("ck_document_doc_type", "document", type_="check")
    op.create_check_constraint("ck_document_doc_type", "document", _in_list("doc_type", BEFORE))
