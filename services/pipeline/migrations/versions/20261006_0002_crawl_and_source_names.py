"""source names and the index the crawl looks known URLs up by

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-06

Hand-written; mirrors pipeline.infrastructure.models. Expand only, so the image before it keeps
working: ``source.name`` is what people call a source, empty for the rows stored before (the
worker names the built-in ones when it starts), and ``ix_raw_document_source_url`` serves the
crawl's question of which listed URLs of a source are stored already
(``RawDocumentRepository.known_urls`` and ``find_by_url``).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MAX_NAME_CHARS = 200


def upgrade() -> None:
    op.add_column("source", sa.Column("name", sa.Text(), server_default="", nullable=False))
    op.create_check_constraint(
        "ck_source_name_length", "source", f"length(name) <= {MAX_NAME_CHARS}"
    )
    op.create_index("ix_raw_document_source_url", "raw_document", ["source_key", "source_url"])


def downgrade() -> None:
    op.drop_index("ix_raw_document_source_url", table_name="raw_document")
    op.drop_constraint("ck_source_name_length", "source", type_="check")
    op.drop_column("source", "name")
