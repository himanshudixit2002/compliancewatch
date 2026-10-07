"""a tenant's erasure: the consumer inbox, the consent records' guard and an erased tenant's name

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-07

Hand-written; mirrors identity.infrastructure.models. Expand-only for the code before this
release, which neither erases nor writes an empty name.

- processed_event (py_common.outbox): the inbox of identity's two consumers, identity.erasure
  (tenant.deletion.requested) and identity.erasure-records (tenant.data.erased).
- consent_record gets its guard, tr_consent_record_guard calling identity.consent_record_guard():
  a DELETE is always refused, and an UPDATE only passes while the transaction has set
  app.erasure to on and changes nothing but subject, evidence and recorded_by: what a tenant's
  erasure pseudonymises. Every other change raises restrict_violation. The records were
  append-only by convention until now; nothing updated or deleted them.
- ck_tenant_name admits the empty name of an erased tenant: btrim(name) <> '' OR status =
  'erased'.

The downgrade drops the guard, the function and the inbox, and puts the old check back; it
fails while an erased tenant (whose name is empty) exists, since the old check refuses it.
"""

from collections.abc import Sequence

from alembic import op

from py_common.outbox import create_processed_event_table, drop_processed_event_table

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "consent_record"
FUNCTION = "consent_record_guard"
TRIGGER = "tr_consent_record_guard"
NAME_CHECK = "ck_tenant_name"
GUARD = """
CREATE FUNCTION consent_record_guard() RETURNS trigger LANGUAGE plpgsql AS $$
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
    create_processed_event_table(op)
    op.execute(GUARD)
    op.execute(
        f"CREATE TRIGGER {TRIGGER} BEFORE UPDATE OR DELETE ON {TABLE} "
        f"FOR EACH ROW EXECUTE FUNCTION {FUNCTION}()"
    )
    op.drop_constraint(NAME_CHECK, "tenant", type_="check")
    op.create_check_constraint(NAME_CHECK, "tenant", "btrim(name) <> '' OR status = 'erased'")


def downgrade() -> None:
    op.drop_constraint(NAME_CHECK, "tenant", type_="check")
    op.create_check_constraint(NAME_CHECK, "tenant", "btrim(name) <> ''")
    op.execute(f"DROP TRIGGER IF EXISTS {TRIGGER} ON {TABLE}")
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}()")
    drop_processed_event_table(op)
