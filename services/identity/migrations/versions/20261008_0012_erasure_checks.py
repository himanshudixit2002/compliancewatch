"""the erasure's checks: the event a deletion was sent as, its second pass, the erased marker, the
consent guard by allowlist and the erased tenant's empty name

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-08

Hand-written; mirrors identity.infrastructure.models. Expand-only for the code before this
release, which writes no erased tenant with a name and changes no consent record but under an
erasure.

- data_request gets deletion_event_id (the tenant.deletion.requested identity last sent for a
  deletion, which every service checks before it erases), second_pass_at (when its second pass
  goes out, once every service answered the first) and second_pass_done (the services that
  answered the second pass), with checks: only a deletion is sent, and a second pass is answered
  only once it is scheduled.
- erased_tenant (py_common.erasure): the marker identity's erasure writes, which its tenant routes
  answer 410 by. No row-level security (the lint exemption *.erased_tenant).
- consent_record_guard() compares whole rows: an UPDATE under app.erasure passes only when the
  row without subject, evidence and recorded_by is unchanged, so a column added later is guarded
  without being named (0011 named the columns that may not change).
- ck_tenant_name: an erased tenant's name is empty and any other tenant's is not
  (0011 allowed an erased tenant to keep a name).

The downgrade puts 0011's guard and check back and drops the marker and the columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from py_common.erasure import create_erased_tenant_table, drop_erased_tenant_table

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "data_request"
SENT_CHECK = "ck_data_request_sent"
SECOND_PASS_CHECK = "ck_data_request_second_pass"
NAME_CHECK = "ck_tenant_name"
ERASED_NAME = "CASE WHEN status = 'erased' THEN name = '' ELSE btrim(name) <> '' END"
GUARD = """
CREATE OR REPLACE FUNCTION consent_record_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'consent_record is append-only: a record is never deleted'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF current_setting('app.erasure', true) IS DISTINCT FROM 'on' THEN
    RAISE EXCEPTION 'consent_record is append-only: only a tenant''s erasure changes a record'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF to_jsonb(NEW) - 'subject' - 'evidence' - 'recorded_by'
     IS DISTINCT FROM to_jsonb(OLD) - 'subject' - 'evidence' - 'recorded_by' THEN
    RAISE EXCEPTION 'an erasure changes only subject, evidence and recorded_by of consent_record'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END
$$
"""
GUARD_0011 = """
CREATE OR REPLACE FUNCTION consent_record_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'consent_record is append-only: a record is never deleted'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF current_setting('app.erasure', true) IS DISTINCT FROM 'on' THEN
    RAISE EXCEPTION 'consent_record is append-only: only a tenant''s erasure changes a record'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF (NEW.id, NEW.tenant_id, NEW.purpose, NEW.granted, NEW.source, NEW.notice_version,
      NEW.recorded_at)
     IS DISTINCT FROM
     (OLD.id, OLD.tenant_id, OLD.purpose, OLD.granted, OLD.source, OLD.notice_version,
      OLD.recorded_at) THEN
    RAISE EXCEPTION 'an erasure changes only subject, evidence and recorded_by of consent_record'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END
$$
"""


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("deletion_event_id", sa.Uuid(), nullable=True))
    op.add_column(TABLE, sa.Column("second_pass_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        TABLE,
        sa.Column(
            "second_pass_done",
            postgresql.ARRAY(sa.String(length=64)),
            nullable=False,
            server_default="{}",
        ),
    )
    op.create_check_constraint(
        SENT_CHECK,
        TABLE,
        "kind = 'deletion' OR (deletion_event_id IS NULL AND second_pass_at IS NULL)",
    )
    op.create_check_constraint(
        SECOND_PASS_CHECK,
        TABLE,
        "second_pass_at IS NOT NULL OR cardinality(second_pass_done) = 0",
    )
    create_erased_tenant_table(op)
    op.execute(GUARD)
    op.drop_constraint(NAME_CHECK, "tenant", type_="check")
    op.create_check_constraint(NAME_CHECK, "tenant", ERASED_NAME)


def downgrade() -> None:
    op.drop_constraint(NAME_CHECK, "tenant", type_="check")
    op.create_check_constraint(NAME_CHECK, "tenant", "btrim(name) <> '' OR status = 'erased'")
    op.execute(GUARD_0011)
    drop_erased_tenant_table(op)
    op.drop_constraint(SECOND_PASS_CHECK, TABLE, type_="check")
    op.drop_constraint(SENT_CHECK, TABLE, type_="check")
    op.drop_column(TABLE, "second_pass_done")
    op.drop_column(TABLE, "second_pass_at")
    op.drop_column(TABLE, "deletion_event_id")
