"""clause search index: full-text column on clause, clause_embedding with an HNSW index

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-29

Hand-written; mirrors rulebook.infrastructure.models. Expand-only:
- ``clause.search_vector`` is a stored generated column, ``to_tsvector('english', text)``, with a
  GIN index. Adding it rewrites the table and fills existing rows; that is not an UPDATE, so the
  append-only trigger on ``clause`` does not fire. English words are stemmed; a token outside the
  English dictionary, such as a Devanagari word, is kept as written.
- ``clause_embedding`` holds one vector per clause and model (pgvector ``vector(512)``, the
  kernel's EMBEDDING_DIMS) with an HNSW index for cosine distance. Rows are never updated (the
  0004 function ``rulebook_append_only`` refuses it): a new model means a new row. Deleting is
  allowed, so a retired model's rows can be pruned.

The pgvector extension goes into ``public``, which every service keeps on its search_path, so
``vector`` resolves unqualified. The dev stack creates it already (infra/dev/postgres/init.sql);
the downgrade leaves it, because other schemas may use it.
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DIMS = 512
SEARCH_VECTOR = "to_tsvector('english'::regconfig, text)"


class _Vector(sa.types.UserDefinedType[object]):
    cache_ok = True

    def get_col_spec(self, **kw: Any) -> str:
        return f"vector({DIMS})"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")

    op.add_column(
        "clause",
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(SEARCH_VECTOR, persisted=True),
            nullable=True,
        ),
    )
    op.create_index("ix_clause_search_vector", "clause", ["search_vector"], postgresql_using="gin")

    op.create_table(
        "clause_embedding",
        sa.Column("clause_id", sa.Uuid(), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("embedding", _Vector(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("clause_id", "model", name="pk_clause_embedding"),
        sa.ForeignKeyConstraint(
            ["clause_id"],
            ["clause.id"],
            name="fk_clause_embedding_clause_id_clause",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("length(model) > 0", name="ck_clause_embedding_model"),
        comment=(
            "Clause embeddings, one per clause and model; vectors from different models do not "
            "compare. Rows are never updated: a new model means a new row, and a retired "
            "model's rows may be deleted."
        ),
    )
    op.create_index(
        "ix_clause_embedding_hnsw",
        "clause_embedding",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.execute(
        "CREATE TRIGGER tr_clause_embedding_no_update BEFORE UPDATE ON clause_embedding"
        " FOR EACH ROW EXECUTE FUNCTION rulebook_append_only()"
    )


def downgrade() -> None:
    op.drop_index("ix_clause_embedding_hnsw", table_name="clause_embedding")
    op.drop_table("clause_embedding")
    op.drop_index("ix_clause_search_vector", table_name="clause")
    op.drop_column("clause", "search_vector")
