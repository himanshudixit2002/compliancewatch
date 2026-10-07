"""Migration 0010 on Postgres: data_request under forced row-level security, written and read by
the use cases through identity's own role and the product's, and every tenant's open requests
counted through ``identity.data_requests_open()``, which infra/dev/postgres/roles.sql makes and
gives to the NOLOGIN role cw_identity_directory. Needs Docker.

Two databases: the first as the dev volume has it (the container's superuser owns the schemas
and runs roles.sql), the second as a deployment has it, where the owner of the schemas is not a
superuser but may create roles, and runs the migrations and roles.sql itself.
"""

import importlib
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from testcontainers.community.postgres import PostgresContainer

from domain_kernel.access import ANONYMOUS
from domain_kernel.ids import TenantId
from identity.application.data_requests import ExportTenantData, RequestExport
from identity.domain.data_requests import (
    DataRequest,
    DataRequestKind,
    DataRequestSource,
    DataRequestStatus,
    OpenRequests,
    SourceSection,
)
from identity.domain.tenancy import Tenant, TenantKind
from identity.infrastructure.models import Base
from identity.infrastructure.repository import (
    PostgresDataRequestDirectory,
    PostgresUnitOfWorkFactory,
)
from py_common.db_roles import apply_roles, as_role

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "identity"
TABLE = "data_request"
DIRECTORY_ROLE = "cw_identity_directory"
FUNCTION = "identity.data_requests_open()"
NOW = datetime(2000, 6, 1, 9, 0, tzinfo=UTC)
APP_ROLE = "cw_app"
APP_ROLE_SQL = (
    f"CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{APP_ROLE}' NOSUPERUSER NOBYPASSRLS",
    f"GRANT USAGE ON SCHEMA {SCHEMA}, audit TO {APP_ROLE}",
    f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {SCHEMA}, audit TO {APP_ROLE}",
    f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {SCHEMA} TO {APP_ROLE}",
)
OWNER = "cw_owner"
INSUFFICIENT_PRIVILEGE = "42501"


def with_schema(url: str) -> str:
    return f"{url}?options=-csearch_path%3D{SCHEMA}%2Cpublic"


def migrate(url: str) -> None:
    with pytest.MonkeyPatch.context() as env:
        env.setenv("CW_DATABASE_URL", url)
        env.setenv("CW_DB_SCHEMA", SCHEMA)
        command.upgrade(Config(str(SERVICE_DIR / "alembic.ini")), "head")


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    """The dev volume's order: the schema, roles.sql, the migrations, roles.sql again, then the
    product's role as make product-role leaves it, and roles.sql once more (make migrate)."""
    with PostgresContainer(IMAGE, driver="psycopg") as postgres:
        base_url = postgres.get_connection_url()
        admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
        apply_roles(base_url)
        migrate(with_schema(base_url))
        apply_roles(base_url)
        with admin.connect() as connection:
            for statement in APP_ROLE_SQL:
                connection.execute(text(statement))
        admin.dispose()
        apply_roles(base_url)
        yield with_schema(base_url)


@pytest.fixture(scope="module")
def engine(database_url: str) -> Iterator[Engine]:
    engine = create_engine(database_url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module", params=[SCHEMA, APP_ROLE])
def role_engine(request: pytest.FixtureRequest, database_url: str) -> Iterator[Engine]:
    if request.param == APP_ROLE:
        url = (
            make_url(database_url)
            .set(username=APP_ROLE, password=APP_ROLE)
            .render_as_string(hide_password=False)
        )
    else:
        url = as_role(database_url, SCHEMA)
    role_engine = create_engine(url)
    yield role_engine
    role_engine.dispose()


def add_tenant(factory: PostgresUnitOfWorkFactory, tenant: TenantId) -> None:
    with factory(tenant) as uow:
        uow.tenants.add(Tenant(tenant, TenantKind.BUSINESS, "Example Traders", NOW))


def request_of(
    tenant: TenantId, *, at: datetime = NOW, kind: DataRequestKind = DataRequestKind.EXPORT
) -> DataRequest:
    return DataRequest.new(
        tenant,
        kind,
        DataRequestSource.SELF_SERVICE,
        requested_by="",
        reason="Example reason",
        at=at,
    )


def test_models_and_migration_agree(engine: Engine) -> None:
    def only_the_table(
        obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
    ) -> bool:
        table = name if type_ == "table" else getattr(getattr(obj, "table", None), "name", None)
        return table == TABLE

    assert TABLE in set(inspect(engine).get_table_names(schema=SCHEMA))
    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={
                "compare_type": True,
                "compare_server_default": True,
                "include_object": only_the_table,
            },
        )
        assert compare_metadata(context, Base.metadata) == []


def test_the_catalog_lint_accepts_the_table_without_exemptions(engine: Engine) -> None:
    lint = importlib.import_module("check_migrations")  # infra/scripts, on the pytest path
    with engine.connect() as connection:
        raw = connection.connection.driver_connection
        catalog = [t for t in lint.read_tables(raw) if t.schema == SCHEMA and t.name == TABLE]
    config = lint.load_config()
    assert len(catalog) == 1
    assert config.exemption_for(catalog[0].qualified) is None
    assert (catalog[0].row_security, catalog[0].force_row_security) == (True, True)
    assert [p for p in lint.catalog_problems(catalog, config) if p.startswith(f"{SCHEMA}.")] == []


def test_the_use_cases_keep_each_tenant_s_requests_apart(role_engine: Engine) -> None:
    factory = PostgresUnitOfWorkFactory(role_engine)
    tenant, other = TenantId.new(), TenantId.new()
    for each in (tenant, other):
        add_tenant(factory, each)
    made = RequestExport(factory, clock=lambda: NOW).run(ANONYMOUS, tenant, reason="Example reason")
    assert made.deadline_at == NOW + timedelta(days=30)
    with factory(other) as uow:
        assert uow.data_requests.get(made.id) is None
        assert uow.data_requests.list() == []
    bundle = ExportTenantData(factory, clock=lambda: NOW).run(ANONYMOUS, tenant, made.id)
    assert bundle.request.status is DataRequestStatus.COMPLETED
    with factory(tenant) as uow:
        (stored,) = uow.data_requests.list()
    assert stored == bundle.request
    assert stored.services_done == ("identity",)
    with role_engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(other)}
        )
        assert connection.execute(text(f"SELECT count(*) FROM {TABLE}")).scalar_one() == 0


def counts(engine: Engine) -> dict[DataRequestKind, OpenRequests]:
    return {entry.kind: entry for entry in PostgresDataRequestDirectory(engine).open_counts()}


def test_the_directory_function_counts_every_tenant_s_open_requests(
    engine: Engine, role_engine: Engine
) -> None:
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {TABLE}"))
    factory = PostgresUnitOfWorkFactory(role_engine)
    first, second = TenantId.new(), TenantId.new()
    long_ago = datetime.now(UTC) - timedelta(days=45)
    deletion = DataRequestKind.DELETION
    with factory(first) as uow:
        uow.data_requests.add(request_of(first, at=long_ago, kind=deletion))
        uow.data_requests.add(request_of(first, at=datetime.now(UTC), kind=deletion))
        uow.data_requests.add(request_of(first, at=datetime.now(UTC)))
    with factory(second) as uow:
        uow.data_requests.add(request_of(second, at=long_ago, kind=deletion))
        uow.data_requests.add(request_of(second, at=long_ago))
        done = request_of(second, at=long_ago)
        uow.data_requests.add(done.record_answers(["identity"], ["identity"], long_ago))
    found = counts(role_engine)
    assert found[DataRequestKind.DELETION] == OpenRequests(DataRequestKind.DELETION, 3, 2), (
        "never answered: open, and overdue past the deadline"
    )
    assert found[DataRequestKind.EXPORT] == OpenRequests(DataRequestKind.EXPORT, 1, 0), (
        "an offered export is open until its deadline, then expires quietly; never overdue"
    )
    with role_engine.connect() as connection:
        visible = connection.execute(text(f"SELECT count(*) FROM {TABLE}")).scalar_one()
    assert visible == 0, "without a tenant, row-level security still hides every request"


def refused(engine: Engine, sql: str) -> str:
    with engine.connect() as connection:
        try:
            connection.execute(text(sql))
        except DBAPIError as error:
            return str(getattr(error.orig, "sqlstate", ""))
    raise AssertionError(f"not refused: {sql}")


def test_only_identity_and_the_product_may_count_and_nobody_logs_in_as_the_directory(
    database_url: str, engine: Engine
) -> None:
    profile = create_engine(as_role(database_url, "profile"))
    try:
        assert refused(profile, f"SELECT * FROM {FUNCTION}") == INSUFFICIENT_PRIVILEGE
    finally:
        profile.dispose()
    with engine.connect() as connection:
        role = connection.execute(
            text(
                "SELECT rolcanlogin, rolsuper, rolbypassrls, rolinherit FROM pg_roles "
                "WHERE rolname = :role"
            ),
            {"role": DIRECTORY_ROLE},
        ).one()
        assert tuple(role) == (False, False, False, False)
        owner, definer, acl = connection.execute(
            text(
                "SELECT proowner::regrole::text, prosecdef, proacl::text FROM pg_proc "
                f"WHERE oid = '{FUNCTION}'::regprocedure"
            )
        ).one()
        assert (owner, definer) == (DIRECTORY_ROLE, True)
        grantees = {entry.split("=")[0] for entry in acl.strip("{}").split(",")}
        assert grantees == {DIRECTORY_ROLE, "cw_identity", APP_ROLE}, "no PUBLIC, no other role"
        creates = connection.execute(
            text("SELECT has_schema_privilege(:role, 'identity', 'CREATE')"),
            {"role": DIRECTORY_ROLE},
        ).scalar_one()
        assert creates is False


def test_running_roles_sql_again_changes_nothing(database_url: str, engine: Engine) -> None:
    def snapshot() -> list[tuple[object, ...]]:
        with engine.connect() as connection:
            return [
                tuple(row)
                for row in connection.execute(
                    text(
                        "SELECT p.proowner::regrole::text, p.proacl::text, "
                        "(SELECT array_agg(policyname ORDER BY policyname) FROM pg_policies "
                        " WHERE tablename = 'data_request'), "
                        "(SELECT nspacl::text FROM pg_namespace WHERE nspname = 'identity') "
                        f"FROM pg_proc p WHERE p.oid = '{FUNCTION}'::regprocedure"
                    )
                )
            ]

    before = snapshot()
    apply_roles(database_url.split("?")[0])
    assert snapshot() == before


@pytest.fixture(scope="module")
def deployment_url() -> Iterator[str]:
    """A database whose schemas belong to a login that is neither a superuser nor bypasses
    row-level security but may create roles, as a managed Postgres gives a deployment."""
    with PostgresContainer(IMAGE, driver="psycopg") as postgres:
        superuser = postgres.get_connection_url()
        admin = create_engine(superuser, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(
                text(
                    f"CREATE ROLE {OWNER} LOGIN PASSWORD '{OWNER}' NOSUPERUSER NOBYPASSRLS "
                    "CREATEROLE"
                )
            )
            connection.execute(text(f"CREATE DATABASE deployment OWNER {OWNER}"))
        admin.dispose()
        owner_url = (
            make_url(superuser)
            .set(username=OWNER, password=OWNER, database="deployment")
            .render_as_string(hide_password=False)
        )
        owner = create_engine(owner_url, isolation_level="AUTOCOMMIT")
        with owner.connect() as connection:
            connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
        owner.dispose()
        apply_roles(owner_url)
        migrate(with_schema(owner_url))
        apply_roles(owner_url)
        apply_roles(owner_url)
        yield owner_url


def test_a_non_superuser_owner_makes_the_directory_and_never_reads_through_it(
    deployment_url: str,
) -> None:
    owner = create_engine(with_schema(deployment_url))
    identity = create_engine(as_role(with_schema(deployment_url), SCHEMA))
    try:
        tenant = TenantId.new()
        with PostgresUnitOfWorkFactory(identity)(tenant) as uow:
            uow.data_requests.add(request_of(tenant, at=datetime.now(UTC) - timedelta(days=31)))
        assert counts(identity)[DataRequestKind.EXPORT] == OpenRequests(
            DataRequestKind.EXPORT, 0, 0
        ), "an offered export past its deadline has expired"
        with PostgresUnitOfWorkFactory(identity)(tenant) as uow:
            uow.data_requests.add(
                request_of(
                    tenant,
                    at=datetime.now(UTC) - timedelta(days=31),
                    kind=DataRequestKind.DELETION,
                )
            )
        assert counts(identity)[DataRequestKind.DELETION] == OpenRequests(
            DataRequestKind.DELETION, 1, 1
        )
        with owner.connect() as connection:
            member = connection.execute(
                text(
                    "SELECT pg_has_role(:owner, :role, 'SET'), pg_has_role(:owner, :role, 'USAGE')"
                ),
                {"owner": OWNER, "role": DIRECTORY_ROLE},
            ).one()
            assert tuple(member) == (True, False), "it acts as the role, it never inherits it"
            assert connection.execute(text(f"SELECT count(*) FROM {TABLE}")).scalar_one() == 0
            owner_of = connection.execute(
                text(
                    "SELECT proowner::regrole::text FROM pg_proc "
                    f"WHERE oid = '{FUNCTION}'::regprocedure"
                )
            ).scalar_one()
            assert owner_of == DIRECTORY_ROLE
            acl = connection.execute(
                text(f"SELECT proacl::text FROM pg_proc WHERE oid = '{FUNCTION}'::regprocedure")
            ).scalar_one()
            grantees = {entry.split("=")[0] for entry in acl.strip("{}").split(",")}
            assert "" not in grantees, "PUBLIC may not run it, whoever owns the schemas"
            assert grantees == {DIRECTORY_ROLE, "cw_identity"}
            public = connection.execute(
                text("SELECT has_function_privilege('cw_profile', :f, 'EXECUTE')"),
                {"f": FUNCTION},
            ).scalar_one()
            assert public is False
    finally:
        owner.dispose()
        identity.dispose()
    with pytest.MonkeyPatch.context() as env:
        env.setenv("CW_DATABASE_URL", with_schema(deployment_url))
        env.setenv("CW_DB_SCHEMA", SCHEMA)
        command.downgrade(Config(str(SERVICE_DIR / "alembic.ini")), "0009")
        command.upgrade(Config(str(SERVICE_DIR / "alembic.ini")), "head")
    apply_roles(deployment_url)
    identity = create_engine(as_role(with_schema(deployment_url), SCHEMA))
    try:
        assert counts(identity)[DataRequestKind.DELETION] == OpenRequests(
            DataRequestKind.DELETION, 0, 0
        ), "the downgrade dropped the function and the table; roles.sql made it again"
    finally:
        identity.dispose()


class AnsweringSource:
    """A source that answers ``service``'s part, after ``gate`` opens when one is given."""

    def __init__(self, service: str, gate: threading.Event | None = None) -> None:
        self._service = service
        self._gate = gate

    @property
    def service(self) -> str:
        return self._service

    def export(self, tenant_id: TenantId) -> SourceSection:
        if self._gate is not None:
            self._gate.wait(10)
        return SourceSection(
            self._service,
            {
                "service": self._service,
                "tenant_id": str(tenant_id),
                "generated_at": NOW.isoformat(),
                "sections": {},
            },
        )


class SilentSource(AnsweringSource):
    def export(self, tenant_id: TenantId) -> SourceSection:
        return SourceSection(self.service, None, "answered 503")


def test_two_downloads_at_once_each_keep_the_services_that_answered(
    role_engine: Engine,
) -> None:
    """One download holds the request's row while it records profile; the other, whose
    obligation answered, waits for it (FOR UPDATE) and then adds its own, so neither is lost."""
    factory = PostgresUnitOfWorkFactory(role_engine)
    tenant = TenantId.new()
    add_tenant(factory, tenant)
    made = RequestExport(factory, clock=lambda: NOW).run(ANONYMOUS, tenant, reason="Example reason")
    expected = ("identity", "obligation", "profile")
    second = ExportTenantData(
        factory, [SilentSource("profile"), AnsweringSource("obligation")], clock=lambda: NOW
    )
    finished: list[DataRequest] = []
    with factory(tenant) as uow:
        held = uow.data_requests.lock(made.id)
        assert held is not None
        uow.data_requests.save(held.record_answers(["identity", "profile"], expected, NOW))
        worker = threading.Thread(
            target=lambda: finished.append(second.run(ANONYMOUS, tenant, made.id).request)
        )
        worker.start()
        worker.join(1.0)
        assert worker.is_alive(), "the second download waits for the row"
    worker.join(10)
    assert not worker.is_alive()
    (request,) = finished
    assert request.services_done == expected
    assert request.status is DataRequestStatus.COMPLETED
    with factory(tenant) as uow:
        stored = uow.data_requests.get(made.id)
    assert stored is not None
    assert stored.services_done == expected


def test_identity_s_own_data_reads_a_page_at_a_time_on_postgres(role_engine: Engine) -> None:
    factory = PostgresUnitOfWorkFactory(role_engine)
    tenant = TenantId.new()
    add_tenant(factory, tenant)
    made = [
        RequestExport(factory, clock=lambda: NOW).run(ANONYMOUS, tenant, reason="Example reason")
        for _ in range(3)
    ]
    paged = ExportTenantData(factory, clock=lambda: NOW, page_size=1).run(
        ANONYMOUS, tenant, made[0].id
    )
    rows = paged.document()["services"]["identity"]["sections"]["data_requests"]
    assert sorted(row["id"] for row in rows) == sorted(str(request.id) for request in made)
    assert [row["id"] for row in rows] == sorted(str(request.id) for request in made)
