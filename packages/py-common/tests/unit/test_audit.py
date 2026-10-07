"""py_common.audit without Postgres: the actor and the correlation id of an entry, the memory
twin, the writer on SQLite and the SQL the table's helpers emit. The table on Postgres, with its
policies and its trigger, is tests/integration/test_audit_postgres.py."""

import io
import re
from collections.abc import Callable, Iterator
from datetime import timedelta
from uuid import UUID

import pytest
import structlog
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, select

from domain_kernel.access import ANONYMOUS, Principal, Role, Scope
from domain_kernel.audit import (
    CORRELATION_ID_PATTERN,
    MAX_REASON_CHARS,
    AuditActor,
    AuditActorKind,
    AuditEntry,
)
from domain_kernel.ids import TenantId, UserId
from py_common.audit import (
    CORRELATION_FIELD,
    MemoryAuditSink,
    audit_actor,
    current_correlation_id,
    masked_entry,
)
from py_common.audit.schema import (
    ACTION_TIME_INDEX,
    EXPORT_READ_POLICY,
    PLATFORM_INSERT_POLICY,
    PLATFORM_READ_POLICY,
    SUBJECT_TIME_INDEX,
    TENANT_TIME_INDEX,
    audit_event,
    create_audit_read_policies,
    create_audit_subject_index,
    create_audit_table,
    drop_audit_read_policies,
    drop_audit_subject_index,
    drop_audit_table,
    metadata,
)
from py_common.audit.testing import (
    SAMPLE_AT,
    SAMPLE_TENANT,
    audit_entry,
    read_audit_entries,
)
from py_common.audit.writer import AuditWriter, PostgresAuditSink, audit_row, entry_from_row
from py_common.auth.context import principal_bound
from py_common.request_context import REQUEST_ID_HEADER, REQUEST_ID_SHAPE, RequestContextMiddleware

SERVICE = "example-service"
NODE = "5a3c6a0e-0d7b-4f43-9a4e-234567890123"
"""A made-up UUID whose last group, on its own, would read as an Aadhaar number."""
DIGEST = "3f0c2a9876543210b7e1d4c5a6f8091e2d3c4b5a69788776655443322110fedc"
"""A made-up SHA-256 digest with a phone number's ten digits in it."""
USER = UserId(UUID("0b6f1e0a-3c9d-4f2a-8e57-6d1c2b3a4f50"))
OTHER_TENANT = TenantId(UUID("9c2e7d41-5a6b-4c3d-8e9f-0a1b2c3d4e5f"))


# ---------------------------------------------------------------------------- actor and request


def test_a_user_principal_acts_as_the_user_with_their_roles() -> None:
    principal = Principal.user(USER, SAMPLE_TENANT, [Role.REVIEWER, Role.ADMIN], mfa=True)
    actor = audit_actor(SERVICE, principal)
    assert (actor.kind, actor.id, actor.label) == (
        AuditActorKind.USER,
        str(USER),
        "admin, reviewer",
    )


def test_a_service_principal_acts_as_its_client() -> None:
    actor = audit_actor(SERVICE, Principal.service("pipeline", [Scope.TENANT_ACT]))
    assert actor == AuditActor.service("pipeline")


def test_anyone_else_is_the_system_named_for_the_service() -> None:
    assert audit_actor(SERVICE, ANONYMOUS) == AuditActor.system(SERVICE)
    assert audit_actor(SERVICE).label == f"system:{SERVICE}", "nothing bound outside a request"


def test_the_bound_principal_is_read_when_none_is_given() -> None:
    principal = Principal.user(USER, SAMPLE_TENANT, [Role.OWNER])
    with principal_bound(principal):
        assert audit_actor(SERVICE) == AuditActor.user(USER, [Role.OWNER])
    assert audit_actor(SERVICE) == AuditActor.system(SERVICE)


def test_the_correlation_id_is_the_one_bound_in_the_log_context() -> None:
    assert current_correlation_id() is None
    with structlog.contextvars.bound_contextvars(**{CORRELATION_FIELD: "request-7"}):
        assert current_correlation_id() == "request-7"
    with structlog.contextvars.bound_contextvars(**{CORRELATION_FIELD: "not a request id"}):
        assert current_correlation_id() is None, "a value of another shape is not kept"
    assert REQUEST_ID_SHAPE.pattern == CORRELATION_ID_PATTERN.pattern


@pytest.fixture
def echo() -> Iterator[TestClient]:
    """An app behind the request middleware whose sync route answers the audit context."""
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/who")
    def who() -> dict[str, str | None]:
        return {"correlation_id": current_correlation_id(), "actor": audit_actor(SERVICE).label}

    with TestClient(app) as client:
        yield client


def test_a_request_gives_its_correlation_id_to_the_entry(echo: TestClient) -> None:
    reused = echo.get("/who", headers={REQUEST_ID_HEADER: "web-request-42"}).json()
    assert reused == {"correlation_id": "web-request-42", "actor": f"system:{SERVICE}"}
    minted = echo.get("/who")
    assert minted.json()["correlation_id"] == minted.headers[REQUEST_ID_HEADER]
    assert CORRELATION_ID_PATTERN.fullmatch(minted.json()["correlation_id"])


# ------------------------------------------------------------------------------ the memory twin


def test_the_memory_sink_commits_or_drops_what_a_unit_wrote() -> None:
    log: list[AuditEntry] = []
    first, second = audit_entry(), audit_entry(subject_id="thing-2")
    sink = MemoryAuditSink(log, tenant_id=SAMPLE_TENANT)
    sink.write(first)
    sink.write(second)
    assert (log, sink.pending) == ([], [first, second])
    sink.commit()
    assert (log, sink.pending) == ([first, second], [])

    failed = MemoryAuditSink(log, tenant_id=SAMPLE_TENANT)
    failed.write(audit_entry())
    failed.rollback()
    failed.commit()
    assert log == [first, second], "a unit that failed adds nothing"


def test_the_memory_sink_refuses_what_the_table_refuses() -> None:
    log: list[AuditEntry] = []
    sink = MemoryAuditSink(log, tenant_id=SAMPLE_TENANT)
    with pytest.raises(ValueError, match="another tenant"):
        sink.write(audit_entry(tenant_id=OTHER_TENANT))
    platform = audit_entry(tenant_id=None)
    sink.write(platform)
    with pytest.raises(ValueError, match="stored already"):
        sink.write(platform)
    sink.commit()
    with pytest.raises(ValueError, match="stored already"):
        MemoryAuditSink(log).write(platform)

    no_tenant = MemoryAuditSink(log)
    with pytest.raises(ValueError, match="another tenant"):
        no_tenant.write(audit_entry())
    no_tenant.write(audit_entry(tenant_id=None))
    assert len(no_tenant.pending) == 1


def test_the_memory_sink_stores_what_the_table_would_hold_masked() -> None:
    """One function masks for both, so a memory store's tests see the row Postgres keeps."""
    log: list[AuditEntry] = []
    entry = audit_entry(
        reason="Example Owner asked on 9876543210 to correct PAN ABCDE1234F",
        before={"contact": {"email": "owner@example.com"}, "node_id": "234567890123"},
        after={"sha256": DIGEST, "reference": "234567890123"},
    )
    sink = MemoryAuditSink(log, tenant_id=SAMPLE_TENANT)
    sink.write(entry)
    sink.commit()
    [stored] = log
    assert stored == masked_entry(entry) == entry_from_row(audit_row(entry))
    assert stored.entry_id == entry.entry_id
    assert stored.reason == "Example Owner asked on [PHONE] to correct PAN [PAN]"
    assert stored.before == {"contact": {"email": "[EMAIL]"}, "node_id": "234567890123"}
    assert stored.after == {"sha256": DIGEST, "reference": "[AADHAAR]"}


def test_a_reason_that_masking_lengthens_past_the_limit_is_cut_and_masked() -> None:
    entry = audit_entry(reason="a@b.co " * 285)
    assert len(entry.reason) <= MAX_REASON_CHARS
    masked = masked_entry(entry)
    assert len(masked.reason) <= MAX_REASON_CHARS
    assert masked.reason.startswith("[EMAIL] [EMAIL] ")
    assert "a@b.co" not in masked.reason
    assert audit_row(entry)["reason"] == masked.reason


# ---------------------------------------------------------------------------- the writer, SQLite


@pytest.fixture
def engine() -> Iterator[Engine]:
    """SQLite with the audit schema mapped to its main database."""
    engine = create_engine("sqlite+pysqlite:///:memory:").execution_options(
        schema_translate_map={"audit": None}
    )
    metadata.create_all(engine)
    yield engine
    engine.dispose()


def test_the_row_holds_every_field_of_the_entry() -> None:
    entry = audit_entry(
        before={"items": ("a", {"b": 1})}, after=None, correlation_id="req-1", reason=""
    )
    row = audit_row(entry)
    assert row == {
        "id": entry.entry_id.value,
        "occurred_at": entry.occurred_at,
        "tenant_id": SAMPLE_TENANT.value,
        "action": "example.thing.change",
        "subject_type": "thing",
        "subject_id": "thing-1",
        "actor_kind": "user",
        "actor_id": entry.actor.id,
        "actor_label": "admin",
        "reason": "",
        "before": {"items": ["a", {"b": 1}]},
        "after": None,
        "correlation_id": "req-1",
    }
    assert type(row["before"]) is dict
    assert set(row) == {column.name for column in audit_event.columns}


def test_an_entry_commits_with_its_transaction_and_reads_back_whole(engine: Engine) -> None:
    first = audit_entry(before=None, after={"items": ["x", {"y": None}]}, correlation_id="r-1")
    second = audit_entry(
        tenant_id=None,
        actor=AuditActor.system(SERVICE),
        before=None,
        after=None,
        occurred_at=SAMPLE_AT + timedelta(minutes=1),
    )
    with engine.begin() as connection:
        AuditWriter().write(connection, first)
        PostgresAuditSink(connection).write(second)
    with engine.connect() as connection:
        assert read_audit_entries(connection) == [first, second]
        assert read_audit_entries(connection, action="other.thing.change") == []
        nulls = connection.execute(
            select(audit_event.c.id).where(audit_event.c.before.is_(None))
        ).all()
    assert len(nulls) == 2, "None is SQL NULL, not JSON null"


def test_a_rolled_back_transaction_writes_no_entry(engine: Engine) -> None:
    with engine.connect() as connection:
        transaction = connection.begin()
        AuditWriter().write(connection, audit_entry())
        transaction.rollback()
        assert read_audit_entries(connection) == []


def test_an_entry_read_from_a_zoneless_time_is_utc() -> None:
    entry = audit_entry()
    row = {**audit_row(entry), "occurred_at": entry.occurred_at.replace(tzinfo=None)}
    assert entry_from_row(row) == entry


def test_the_reason_and_the_state_are_masked_but_ids_and_the_actor_are_not() -> None:
    entry = audit_entry(
        subject_type="profile_node",
        subject_id=NODE,
        actor=AuditActor.service("client-9876543210"),
        reason=f"Example Owner asked on 9876543210 to correct PAN ABCDE1234F of {NODE}",
        before={
            "contact": {"email": "owner@example.com", "phones": ["+91 98765 43210"]},
            "node_id": "234567890123",
        },
        after={
            "gstin": "29ABCDE1234F1Z5",
            "registration_ids": ["234567890123"],
            "reference": "234567890123",
            "resolved_by": NODE,
            "count": 2,
        },
        correlation_id="234567890123",
    )
    row = audit_row(entry)
    assert row["reason"] == f"Example Owner asked on [PHONE] to correct PAN [PAN] of {NODE}"
    assert row["before"] == {
        "contact": {"email": "[EMAIL]", "phones": ["[PHONE]"]},
        "node_id": "234567890123",
    }
    assert row["after"] == {
        "gstin": "[GSTIN]",
        "registration_ids": ["234567890123"],
        "reference": "[AADHAAR]",
        "resolved_by": NODE,
        "count": 2,
    }
    assert (row["subject_id"], row["actor_id"], row["actor_label"], row["correlation_id"]) == (
        NODE,
        "client-9876543210",
        "service:client-9876543210",
        "234567890123",
    )
    assert entry.reason.startswith("Example Owner asked on 9876543210 to correct PAN ABCDE")
    assert entry.before is not None
    assert entry.before["contact"] == {
        "email": "owner@example.com",
        "phones": ("+91 98765 43210",),
    }, "the entry itself is unchanged"


def test_the_row_written_is_the_masked_one(engine: Engine) -> None:
    entry = audit_entry(
        reason="Mail from owner@example.com", before=None, after={"pan": "ABCDE1234F"}
    )
    with engine.begin() as connection:
        AuditWriter().write(connection, entry)
    with engine.connect() as connection:
        [stored] = read_audit_entries(connection)
    assert stored.entry_id == entry.entry_id
    assert stored.reason == "Mail from [EMAIL]"
    assert stored.after == {"pan": "[PAN]"}


# ------------------------------------------------------------------------- the table's helpers


def emitted(step: Callable[[Operations], None]) -> str:
    """The SQL ``step`` emits offline, whitespace collapsed."""
    buffer = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        dialect_opts={"paramstyle": "named"},
        opts={"as_sql": True, "output_buffer": buffer},
    )
    step(Operations(context))
    return re.sub(r"\s+", " ", buffer.getvalue())


def test_the_table_is_created_with_its_indexes_policies_and_trigger() -> None:
    sql = emitted(create_audit_table)
    assert sql.startswith("CREATE SCHEMA IF NOT EXISTS audit;")
    assert "CREATE TABLE audit.event (" in sql
    for column in (
        "id UUID NOT NULL",
        "occurred_at TIMESTAMP WITH TIME ZONE NOT NULL",
        "tenant_id UUID,",
        "action VARCHAR(120) NOT NULL",
        "actor_kind VARCHAR(16) NOT NULL",
        "reason TEXT DEFAULT '' NOT NULL",
        "before JSONB,",
        "after JSONB,",
        "correlation_id VARCHAR(64),",
        "CONSTRAINT pk_audit_event PRIMARY KEY (id)",
        "CONSTRAINT ck_audit_event_actor_kind CHECK (actor_kind IN ('user', 'service', 'system'))",
    ):
        assert column in sql, column
    assert f"CREATE INDEX {TENANT_TIME_INDEX} ON audit.event (tenant_id, occurred_at);" in sql
    assert f"CREATE INDEX {ACTION_TIME_INDEX} ON audit.event (action, occurred_at);" in sql
    assert "ALTER TABLE audit.event FORCE ROW LEVEL SECURITY;" in sql
    assert (
        "CREATE POLICY event_tenant_isolation ON audit.event "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);"
    ) in sql
    assert (
        f"CREATE POLICY {PLATFORM_INSERT_POLICY} ON audit.event FOR INSERT "
        "WITH CHECK (tenant_id IS NULL);"
    ) in sql
    assert "FOR SELECT" not in sql, "the read scopes come in a later migration of their own"
    assert (
        "CREATE TRIGGER tr_event_append_only BEFORE UPDATE OR DELETE ON audit.event "
        "FOR EACH ROW EXECUTE FUNCTION audit.audit_append_only();"
    ) in sql
    assert "app.erasure" not in sql, "rows outlive a tenant's erasure"


def test_the_drop_keeps_the_schema() -> None:
    statements = [s.strip() for s in emitted(drop_audit_table).split(";") if s.strip()]
    assert statements[0] == "DROP TRIGGER IF EXISTS tr_event_append_only ON audit.event"
    assert statements[-3:] == [
        f"DROP INDEX audit.{ACTION_TIME_INDEX}",
        f"DROP INDEX audit.{TENANT_TIME_INDEX}",
        "DROP TABLE audit.event",
    ]
    assert not [s for s in statements if s.startswith("DROP SCHEMA")]


def test_the_read_scopes_are_select_policies_on_the_audit_scope_setting() -> None:
    statements = [s.strip() for s in emitted(create_audit_read_policies).split(";") if s.strip()]
    assert statements == [
        f"CREATE POLICY {PLATFORM_READ_POLICY} ON audit.event FOR SELECT "
        "USING (tenant_id IS NULL AND current_setting('app.audit_scope', true) = 'regulatory')",
        f"CREATE POLICY {EXPORT_READ_POLICY} ON audit.event FOR SELECT "
        "USING (current_setting('app.audit_scope', true) = 'export')",
    ]
    dropped = [s.strip() for s in emitted(drop_audit_read_policies).split(";") if s.strip()]
    assert dropped == [
        f"DROP POLICY IF EXISTS {EXPORT_READ_POLICY} ON audit.event",
        f"DROP POLICY IF EXISTS {PLATFORM_READ_POLICY} ON audit.event",
    ]


def test_the_subject_index_comes_in_a_migration_of_its_own() -> None:
    assert SUBJECT_TIME_INDEX not in emitted(create_audit_table)
    created = [s.strip() for s in emitted(create_audit_subject_index).split(";") if s.strip()]
    assert created == [
        f"CREATE INDEX {SUBJECT_TIME_INDEX} ON audit.event (subject_type, subject_id, occurred_at)"
    ]
    dropped = [s.strip() for s in emitted(drop_audit_subject_index).split(";") if s.strip()]
    assert dropped == [f"DROP INDEX audit.{SUBJECT_TIME_INDEX}"]
    assert SUBJECT_TIME_INDEX in {index.name for index in audit_event.indexes}
