"""crawl runs name their trigger and workflow; a person's retries of a document

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-06

Hand-written; mirrors pipeline.infrastructure.models. Expand only: the image before it never
writes the new columns or the new table and reads none of them, so it starts on this schema. It
does not keep working beside the image that came with it, or after it, without care
(infra/deploy/README.md, "Promotion and rollback"):

- the new image's workflow and activity inputs carry fields the old models refuse (they forbid
  extra fields): a crawl's ``backfill`` trigger and window, the listing's window, the finish's
  ``trigger`` and ``deferred``, the ingest's ``reclassify``, the classify step's ``fresh``. An old
  worker fails each task of a workflow the new image started, so old and new pipeline workers
  must never poll the ``pipeline`` task queue at the same time: stop the old workers before the
  new ones start, and on a rollback let every workflow the new image started end (or terminate
  it) before an old worker starts;
- a type a person gave on a retry is a ``document_classification`` row by ``retry`` with the
  person in ``decided_by``, which the old ``Classification`` refuses ("only a triage is decided
  by a person"): the old image fails on each such document. Roll forward once one is stored.

- ``crawl_run.trigger`` (``schedule``, ``manual`` or ``backfill``) and ``crawl_run.workflow_id``
  say why a run ran and which workflow ran it; both are null on the runs recorded before.
  ``ix_crawl_run_started`` serves the list of every source's runs, the latest first
  (``GET /v1/pipeline/runs``), and ``ix_raw_document_fetched`` the list of every source's
  documents, the latest fetch first (``GET /v1/pipeline/documents``).
- ``document_retry``: one row per retry a person asks for (``POST
  /v1/pipeline/documents/{id}/retry``): the document's attempt number, the stage its ingest starts
  again from, the type the person gave it, why and by whom, the request's Idempotency-Key with the
  fingerprint of its body (a request sent again finds its attempt), and the ingest's workflow id.
  A trigger keeps it as written.
- ``document_classification``: a classification a person decided may be a ``retry``'s (the type
  a person gave on a retry) as well as a ``triage``'s.

Regulatory data, no tenant: ``pipeline`` is a global schema in infra/scripts/migration_lint.toml.
The downgrade refuses while a retry or a retry's classification is stored, so it never drops a
person's decision; with none, it drops the table, the columns and the indexes.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRIGGERS = ("schedule", "manual", "backfill")
STAGES = ("parse", "classify", "extract")
DOCUMENT_TYPES = ("notification", "circular", "press_release", "act_amendment", "statute")
DECIDING_AFTER = ("retry", "triage")
MAX_WORKFLOW_ID_CHARS = 200
MAX_KEY_CHARS = 128
MAX_REASON_CHARS = 2_000

RETRY_GUARD = """
CREATE FUNCTION pipeline_document_retry_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'a document_retry row is kept as written' USING ERRCODE = 'restrict_violation';
END
$$
"""
STORED = (
    "SELECT (SELECT count(*) FROM document_retry), "
    "(SELECT count(*) FROM document_classification WHERE classifier = 'retry')"
)


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(f"'{value}'" for value in values)})"


DECIDED_BY_BEFORE = "decided_by IS NULL OR classifier = 'triage'"
DECIDED_BY_AFTER = f"decided_by IS NULL OR {_in_list('classifier', DECIDING_AFTER)}"


def upgrade() -> None:
    op.add_column("crawl_run", sa.Column("trigger", sa.String(length=16), nullable=True))
    op.add_column(
        "crawl_run",
        sa.Column("workflow_id", sa.String(length=MAX_WORKFLOW_ID_CHARS), nullable=True),
    )
    op.create_check_constraint(
        "ck_crawl_run_trigger", "crawl_run", f"trigger IS NULL OR {_in_list('trigger', TRIGGERS)}"
    )
    op.create_index("ix_crawl_run_started", "crawl_run", ["started_at", "id"])
    op.create_index("ix_raw_document_fetched", "raw_document", ["fetched_at", "id"])

    op.drop_constraint(
        "ck_document_classification_decided_by", "document_classification", type_="check"
    )
    op.create_check_constraint(
        "ck_document_classification_decided_by",
        "document_classification",
        DECIDED_BY_AFTER,
    )

    op.create_table(
        "document_retry",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(length=16), nullable=False),
        sa.Column("doc_type", sa.String(length=16), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=MAX_KEY_CHARS), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("workflow_id", sa.String(length=MAX_WORKFLOW_ID_CHARS), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_document_retry"),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["raw_document.id"],
            name="fk_document_retry_document_id_raw_document",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("document_id", "attempt", name="uq_document_retry_attempt"),
        sa.UniqueConstraint("document_id", "idempotency_key", name="uq_document_retry_key"),
        sa.CheckConstraint("attempt >= 1", name="ck_document_retry_attempt"),
        sa.CheckConstraint(_in_list("stage", STAGES), name="ck_document_retry_stage"),
        sa.CheckConstraint(
            f"doc_type IS NULL OR {_in_list('doc_type', DOCUMENT_TYPES)}",
            name="ck_document_retry_doc_type",
        ),
        sa.CheckConstraint(
            f"length(reason) BETWEEN 1 AND {MAX_REASON_CHARS}", name="ck_document_retry_reason"
        ),
        sa.CheckConstraint(
            f"length(idempotency_key) BETWEEN 8 AND {MAX_KEY_CHARS}",
            name="ck_document_retry_key",
        ),
        sa.CheckConstraint("fingerprint ~ '^[0-9a-f]{64}$'", name="ck_document_retry_fingerprint"),
        sa.CheckConstraint("length(workflow_id) > 0", name="ck_document_retry_workflow_id"),
        comment=(
            "A person's retry of a stored document: its attempt, the stage its ingest starts "
            "again from, the type the person gave it, why and by whom, the request's "
            "Idempotency-Key and the ingest's workflow id. Kept as written "
            "(pipeline_document_retry_guard). Regulatory data, no tenant."
        ),
    )
    op.execute(RETRY_GUARD)
    op.execute(
        "CREATE TRIGGER tr_document_retry_guard BEFORE UPDATE OR DELETE ON document_retry"
        " FOR EACH ROW EXECUTE FUNCTION pipeline_document_retry_guard()"
    )


def downgrade() -> None:
    retries, given = op.get_bind().execute(sa.text(STORED)).one()
    if retries or given:
        raise RuntimeError(
            f"0005 drops document_retry and the retry classifier, and found {retries} retries "
            f"and {given} classifications a person gave on a retry; the downgrade never drops a "
            "person's decision, so it stops before it changes anything"
        )
    op.execute("DROP TRIGGER tr_document_retry_guard ON document_retry")
    op.execute("DROP FUNCTION pipeline_document_retry_guard()")
    op.drop_table("document_retry")
    op.drop_constraint(
        "ck_document_classification_decided_by", "document_classification", type_="check"
    )
    op.create_check_constraint(
        "ck_document_classification_decided_by",
        "document_classification",
        DECIDED_BY_BEFORE,
    )
    op.drop_index("ix_raw_document_fetched", table_name="raw_document")
    op.drop_index("ix_crawl_run_started", table_name="crawl_run")
    op.drop_constraint("ck_crawl_run_trigger", "crawl_run", type_="check")
    op.drop_column("crawl_run", "workflow_id")
    op.drop_column("crawl_run", "trigger")
