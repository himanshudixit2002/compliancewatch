"""Migration 0007 on Postgres: ``error_report`` with forced row-level security, its index and its
checks, and the use cases on the Postgres unit of work as obligation's own role (cw_obligation,
neither a superuser nor the owner, so the policy applies): a report kept as written with its
masked event in the outbox and its audit row, invisible to another tenant, listed newest first in
keyset pages and in the export, and a decision applied once on the locked row. Needs Docker."""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from testcontainers.community.postgres import PostgresContainer

from domain_kernel.ids import BusinessId, DecisionId, EventId, ObligationId, RuleVersionId, TenantId
from obligation.application.error_reports import (
    DECIDED_ACTION,
    SUBMITTED_ACTION,
    ApplyErrorDecision,
    ErrorDecision,
    ListErrorReports,
    NewErrorReport,
    ReportError,
)
from obligation.application.export import ExportTenantData
from obligation.application.materialise import MaterialiseObligations, MaterialiseRequest
from obligation.application.tracking import Acting
from obligation.domain.error_reports import (
    ErrorCategory,
    ErrorOutcome,
    ErrorReport,
    ErrorReportStatus,
)
from obligation.domain.errors import (
    ErrorReportNotFoundError,
    ErrorReportsDisabledError,
    ObligationNotFoundError,
)
from obligation.domain.flags import ERROR_REPORTS
from obligation.domain.repository import ReportAfter
from obligation.infrastructure.flags import StaticFlags
from obligation.infrastructure.repository import PostgresUnitOfWorkFactory
from obligation.testing import rule
from py_common.audit import audit_actor
from py_common.audit.testing import install_audit_table
from py_common.db_roles import apply_roles, as_role

pytestmark = pytest.mark.integration

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "obligation"
TABLE = "error_report"
NOW = datetime(2000, 2, 3, 5, 15, tzinfo=UTC)
TEXT = (
    "Example: the example monthly statement shows the 20th as its due date, but the example "
    "notice gives the 25th. Call us on +91 98765 43210."
)
CHECKS = {
    "ck_error_report_category",
    "ck_error_report_status",
    "ck_error_report_description",
    "ck_error_report_notes",
    "ck_error_report_state",
}


class Clock:
    def __init__(self, start: datetime = NOW) -> None:
        self.now = start

    def __call__(self) -> datetime:
        self.now += timedelta(minutes=1)
        return self.now


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    with PostgresContainer(IMAGE, driver="psycopg") as postgres:
        base_url = postgres.get_connection_url()
        admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
            install_audit_table(connection)
        admin.dispose()
        database_url = f"{base_url}?options=-csearch_path%3D{SCHEMA}%2Cpublic"
        with pytest.MonkeyPatch.context() as env:
            env.setenv("CW_DATABASE_URL", database_url)
            env.setenv("CW_DB_SCHEMA", SCHEMA)
            command.upgrade(Config(str(SERVICE_DIR / "alembic.ini")), "head")
        apply_roles(database_url)
        yield database_url


@pytest.fixture(scope="module")
def owner(database_url: str) -> Iterator[Engine]:
    """The container's superuser: the catalog and every row, whatever the policy says."""
    engine = create_engine(database_url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def engine(database_url: str) -> Iterator[Engine]:
    engine = create_engine(as_role(database_url, SCHEMA))
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def factory(engine: Engine) -> PostgresUnitOfWorkFactory:
    return PostgresUnitOfWorkFactory(engine)


def acting(tenant: TenantId) -> Acting:
    return Acting(tenant_id=tenant, actor=audit_actor(SCHEMA))


def an_obligation(factory: PostgresUnitOfWorkFactory, tenant: TenantId) -> ObligationId:
    """One obligation of a monthly rule materialised for ``tenant``."""
    made = MaterialiseObligations(factory, window=1).run(
        MaterialiseRequest(tenant, BusinessId.new(), DecisionId.new(), rule(), date(2026, 9, 28))
    )
    return made.created[0]


def report_error(
    factory: PostgresUnitOfWorkFactory,
    tenant: TenantId,
    obligation_id: ObligationId,
    description: str = TEXT,
    *,
    clock: Clock | None = None,
    on: bool = True,
) -> ErrorReport:
    flags = StaticFlags(ERROR_REPORTS) if on else StaticFlags()
    use_case = ReportError(factory, flags, clock=clock or Clock())
    return use_case.run(
        NewErrorReport(acting(tenant), obligation_id, ErrorCategory.DUE_DATE, description)
    )


def test_the_table_has_forced_row_level_security_its_index_and_its_checks(owner: Engine) -> None:
    inspector = inspect(owner)
    assert TABLE in inspector.get_table_names(schema=SCHEMA)
    assert {c["name"] for c in inspector.get_check_constraints(TABLE, schema=SCHEMA)} >= CHECKS
    assert {i["name"] for i in inspector.get_indexes(TABLE, schema=SCHEMA)} == {
        "ix_error_report_tenant_status"
    }
    (foreign_key,) = inspector.get_foreign_keys(TABLE, schema=SCHEMA)
    assert (foreign_key["referred_table"], foreign_key["options"].get("ondelete")) == (
        "obligation",
        "RESTRICT",
    )
    with owner.connect() as connection:
        rls = connection.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname = :table AND relnamespace = CAST(:schema AS regnamespace)"
            ),
            {"table": TABLE, "schema": SCHEMA},
        ).one()
        policies = list(
            connection.execute(
                text("SELECT policyname FROM pg_policies WHERE tablename = :table"),
                {"table": TABLE},
            ).scalars()
        )
    assert tuple(rls) == (True, True)
    assert policies == ["error_report_tenant_isolation"]


def test_a_report_is_kept_as_written_leaves_masked_and_stays_the_tenants(
    factory: PostgresUnitOfWorkFactory, owner: Engine
) -> None:
    tenant, other = TenantId.new(), TenantId.new()
    obligation_id = an_obligation(factory, tenant)

    with pytest.raises(ErrorReportsDisabledError):
        report_error(factory, tenant, obligation_id, on=False)
    with pytest.raises(ObligationNotFoundError):
        report_error(factory, other, obligation_id), "another tenant's obligation"
    report = report_error(factory, tenant, obligation_id)

    assert (report.tenant_id, report.obligation_id, report.status) == (
        tenant,
        obligation_id,
        ErrorReportStatus.SUBMITTED,
    )
    with factory(tenant) as uow:
        stored = uow.error_reports.get(report.id)
        assert stored == report
        assert stored.description == TEXT, "the tenant's own row keeps the text"
    with factory(other) as uow:
        assert uow.error_reports.get(report.id) is None, "row-level security"
    assert ListErrorReports(factory).run(other) == []
    assert [r.id for r in ListErrorReports(factory).run(tenant)] == [report.id]

    with owner.connect() as connection:
        (message,) = connection.execute(
            text(
                "SELECT message FROM outbox_event "
                "WHERE tenant_id = :t AND topic = 'error_report.submitted'"
            ),
            {"t": tenant.value},
        ).scalars()
        entries = connection.execute(
            text("SELECT action, after FROM audit.event WHERE subject_id = :id ORDER BY id"),
            {"id": str(report.id)},
        ).all()
    payload = message["payload"]
    assert (payload["report_id"], payload["category"]) == (str(report.id), "due_date")
    assert "[PHONE]" in payload["description"]
    assert "98765" not in payload["description"]
    assert [(action, after["status"]) for action, after in entries] == [
        (SUBMITTED_ACTION, "submitted")
    ]
    assert "98765" not in str(entries[0][1]), "the audit row names no text"


def test_the_list_pages_newest_first_and_the_export_lists_them(
    factory: PostgresUnitOfWorkFactory,
) -> None:
    tenant = TenantId.new()
    obligation_id = an_obligation(factory, tenant)
    clock = Clock(NOW + timedelta(days=1))
    made = [
        report_error(factory, tenant, obligation_id, f"Example {n}", clock=clock) for n in range(3)
    ]
    newest_first = sorted(made, key=lambda r: (r.submitted_at, r.id.value), reverse=True)
    listing = ListErrorReports(factory)

    first = listing.run(tenant, limit=2)
    assert first == newest_first[:2]
    rest = listing.run(tenant, after=ReportAfter(first[-1].submitted_at, first[-1].id), limit=2)
    assert rest == newest_first[2:]
    assert listing.run(tenant, status=ErrorReportStatus.CONFIRMED) == []
    assert listing.run(tenant, status=ErrorReportStatus.SUBMITTED) == newest_first

    exported = ExportTenantData(factory, lambda: NOW).run(tenant).sections["error_reports"]
    assert [row["id"] for row in exported] == [str(r.id.value) for r in reversed(newest_first)]
    assert exported[0]["description"] == "Example 0"


def test_a_decision_is_applied_once_on_the_locked_row(
    factory: PostgresUnitOfWorkFactory, owner: Engine
) -> None:
    tenant, other = TenantId.new(), TenantId.new()
    report = report_error(factory, tenant, an_obligation(factory, tenant))
    correcting = RuleVersionId.new()

    def decision(for_tenant: TenantId, outcome: ErrorOutcome) -> ErrorDecision:
        return ErrorDecision(
            event_id=EventId.new(),
            tenant_id=for_tenant,
            report_id=report.id,
            rule_version_id=report.rule_version_id,
            outcome=outcome,
            notes="Example: version 2 corrects it.",
            correcting_rule_version_id=correcting if outcome is ErrorOutcome.CONFIRMED else None,
            decided_at=NOW + timedelta(days=2),
        )

    with pytest.raises(ErrorReportNotFoundError):
        ApplyErrorDecision().run(decision(other, ErrorOutcome.REJECTED), factory)
    applied = ApplyErrorDecision().run(decision(tenant, ErrorOutcome.CONFIRMED), factory)
    assert applied.changed
    assert (applied.report.status, applied.report.correcting_rule_version_id) == (
        ErrorReportStatus.CONFIRMED,
        correcting,
    )
    again = ApplyErrorDecision().run(decision(tenant, ErrorOutcome.REJECTED), factory)
    assert not again.changed
    assert again.report == applied.report, "a decision is final"
    with owner.connect() as connection:
        actions = list(
            connection.execute(
                text("SELECT action FROM audit.event WHERE subject_id = :id ORDER BY id"),
                {"id": str(report.id)},
            ).scalars()
        )
    assert actions == [SUBMITTED_ACTION, DECIDED_ACTION]


def test_the_state_check_refuses_a_confirmation_without_its_version(
    factory: PostgresUnitOfWorkFactory, owner: Engine
) -> None:
    tenant = TenantId.new()
    report = report_error(factory, tenant, an_obligation(factory, tenant))
    with pytest.raises(IntegrityError, match="ck_error_report_state"), owner.begin() as connection:
        connection.execute(
            text("UPDATE error_report SET status = 'confirmed', decided_at = :at WHERE id = :id"),
            {"id": report.id.value, "at": NOW},
        )
    with (
        pytest.raises(IntegrityError, match="ck_error_report_category"),
        owner.begin() as connection,
    ):
        connection.execute(
            text("UPDATE error_report SET category = 'typo' WHERE id = :id"),
            {"id": report.id.value},
        )
    assert isinstance(report.id.value, UUID)
