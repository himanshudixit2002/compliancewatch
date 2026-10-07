"""The services' database roles (``infra/dev/postgres/roles.sql``) on every schema. Needs Docker.

The database starts as a fresh dev volume does: pgvector and every schema from init.sql, then
roles.sql and dev-passwords.sql, before any migration. Every service then migrates as the owner
(``cw-mvp migrate``), and roles.sql runs again, as ``make migrate`` and ``make dev`` run it.

- each ``cw_<schema>`` logs in with its dev password and holds no attribute but LOGIN: not a
  superuser, no row-level security bypass, NOINHERIT;
- it reads and writes the tables of its own schema, the tables migrations add later included,
  but never writes its ``alembic_version`` (the first migration's copy is taken back by the
  second run), and it uses no other service's schema;
- it may add rows to ``audit.event`` of its tenant or of none, under row-level security, and only
  ``cw_identity`` reads them: its tenant's, and the platform's under the regulatory scope;
- running the file again changes no privilege, and a role made by hand with more is cut back;
- the identity directory: the NOLOGIN role cw_identity_directory owns
  identity.data_requests_open(), which only cw_identity (and cw_app) may run, and it counts every
  tenant's open requests that row-level security hides from cw_identity itself. It holds no
  attribute, and its only member, if any, is the owner, which does not inherit it.

A second database is a deployment's: its schemas belong to a login that may create roles but is
not a superuser. That owner runs roles.sql, identity's migrations, roles.sql again and
50-app-role.sql (make product-role), and PUBLIC still cannot run the function: the grants are made
as the function's owner, since the owner in its own role holds no grant option on it.
"""

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from testcontainers.community.postgres import PostgresContainer

from cw_mvp.migrate import migrate
from cw_mvp.settings import ReleaseSettings
from domain_kernel.ids import TenantId
from py_common.audit.testing import audit_entry
from py_common.audit.writer import AuditWriter
from py_common.db_roles import (
    AUDIT_READER,
    SERVICE_SCHEMAS,
    apply_roles,
    as_role,
    role_name,
    sql_dir,
)

pytestmark = pytest.mark.integration

POSTGRES_IMAGE = "pgvector/pgvector:0.8.6-pg16"
RUNTIME = "postgresql+psycopg://cw_app:cw_app@localhost:5432/compliancewatch"
AUDIT = "audit"
VERSION_TABLE = "alembic_version"
WRITES = ("INSERT", "UPDATE", "DELETE")
INSUFFICIENT_PRIVILEGE = "42501"
"""SQLSTATE of a privilege the role lacks, and of a row a policy refuses."""
FLAGS = ("rolsuper", "rolbypassrls", "rolreplication", "rolcreatedb", "rolcreaterole", "rolinherit")
"""The attributes no service role may hold."""


@pytest.fixture(scope="module")
def owner_url() -> Iterator[str]:
    with PostgresContainer(POSTGRES_IMAGE, driver="psycopg") as container:
        url = container.get_connection_url()
        engine = create_engine(url, isolation_level="AUTOCOMMIT")
        with engine.connect() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            for schema in (*SERVICE_SCHEMAS, AUDIT):
                connection.execute(text(f"CREATE SCHEMA {schema}"))
        engine.dispose()
        yield url


@pytest.fixture(scope="module")
def owner(owner_url: str) -> Iterator[Engine]:
    engine = create_engine(owner_url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def first_migration_writes(owner_url: str, owner: Engine) -> dict[str, bool]:
    """A fresh volume's order: the roles, every migration, then the roles again. Returns whether
    each role could write its ``alembic_version`` between the migrations and the second run."""
    apply_roles(owner_url)
    settings = ReleaseSettings(
        _env_file=None,
        service_name="cw-mvp-release",
        env="test",
        log_level="WARNING",
        database_url=RUNTIME,
        migration_database_url=SecretStr(owner_url),
    )
    migrate(settings)
    with owner.connect() as connection:
        writes = {
            schema: _has_table(connection, schema, f"{schema}.{VERSION_TABLE}", "INSERT")
            for schema in SERVICE_SCHEMAS
            if _exists(connection, f"{schema}.{VERSION_TABLE}")
        }
    apply_roles(owner_url)
    return writes


def _exists(connection: Connection, table: str) -> bool:
    found = connection.execute(text("SELECT to_regclass(:t) IS NOT NULL"), {"t": table})
    return bool(found.scalar_one())


def _has_table(connection: Connection, schema: str, table: str, privilege: str) -> bool:
    return bool(
        connection.execute(
            text("SELECT has_table_privilege(:role, :table, :privilege)"),
            {"role": role_name(schema), "table": table, "privilege": privilege},
        ).scalar_one()
    )


def _has_schema(connection: Connection, schema: str, target: str) -> bool:
    return bool(
        connection.execute(
            text("SELECT has_schema_privilege(:role, :target, 'USAGE')"),
            {"role": role_name(schema), "target": target},
        ).scalar_one()
    )


def _tables(connection: Connection, schema: str) -> list[str]:
    return list(
        connection.execute(
            text(
                "SELECT format('%I.%I', schemaname, tablename) FROM pg_tables "
                "WHERE schemaname = :schema ORDER BY tablename"
            ),
            {"schema": schema},
        ).scalars()
    )


def _privileges(connection: Connection) -> list[tuple[Any, ...]]:
    """Every grant on the schemas, their tables and the default privileges, sorted."""
    rows = connection.execute(
        text(
            """
            SELECT 'schema', nspname, coalesce(nspacl::text, '') FROM pg_namespace
             WHERE nspname = ANY(:schemas)
            UNION ALL
            SELECT 'table', n.nspname || '.' || c.relname, coalesce(c.relacl::text, '')
              FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = ANY(:schemas)
            UNION ALL
            SELECT 'default', coalesce(n.nspname, ''), d.defaclacl::text
              FROM pg_default_acl d LEFT JOIN pg_namespace n ON n.oid = d.defaclnamespace
            """
        ),
        {"schemas": [*SERVICE_SCHEMAS, AUDIT, "public"]},
    )
    return sorted(tuple(row) for row in rows)


def test_each_role_logs_in_with_its_dev_password_and_has_no_other_attribute(
    owner_url: str, owner: Engine, first_migration_writes: dict[str, bool]
) -> None:
    with owner.connect() as connection:
        found = {
            row.rolname: row
            for row in connection.execute(
                text(
                    "SELECT rolname, rolcanlogin, rolsuper, rolbypassrls, rolcreatedb, "
                    "rolcreaterole, rolinherit, rolreplication FROM pg_roles "
                    "WHERE rolname LIKE 'cw\\_%' AND rolcanlogin"
                )
            )
        }
    assert sorted(found) == sorted(role_name(schema) for schema in SERVICE_SCHEMAS)
    for name, row in found.items():
        assert row.rolcanlogin, name
        granted = [flag for flag in FLAGS if getattr(row, flag)]
        assert granted == [], name
    for schema in SERVICE_SCHEMAS:
        engine = create_engine(as_role(owner_url, schema))
        with engine.connect() as connection:
            assert connection.execute(text("SELECT current_user")).scalar_one() == role_name(schema)
        engine.dispose()


def test_each_role_has_its_own_schema_and_no_other(
    owner: Engine, first_migration_writes: dict[str, bool]
) -> None:
    with owner.connect() as connection:
        for schema in SERVICE_SCHEMAS:
            assert _has_schema(connection, schema, "public"), schema
            assert _has_schema(connection, schema, AUDIT), schema
            others = [
                s for s in SERVICE_SCHEMAS if s != schema and _has_schema(connection, schema, s)
            ]
            assert others == [], schema
            assert _has_schema(connection, schema, schema), schema
            for table in _tables(connection, schema):
                version = table.endswith(f".{VERSION_TABLE}")
                assert _has_table(connection, schema, table, "SELECT"), table
                for privilege in WRITES:
                    assert _has_table(connection, schema, table, privilege) is not version, (
                        table,
                        privilege,
                    )
                assert not _has_table(connection, schema, table, "TRUNCATE"), table


def test_the_first_migration_s_version_table_is_taken_back_by_the_second_run(
    first_migration_writes: dict[str, bool],
) -> None:
    """The default privileges reach the version table a schema's first migration makes, which
    is why make migrate and make dev run roles.sql again."""
    assert first_migration_writes, "no schema made its alembic_version"
    assert all(first_migration_writes.values()), first_migration_writes


def test_tables_made_after_the_roles_reach_their_schema_s_role_only(
    owner: Engine, first_migration_writes: dict[str, bool]
) -> None:
    with owner.begin() as connection:
        connection.execute(text("CREATE TABLE eval.roles_probe (id integer)"))
        connection.execute(text("CREATE TABLE audit.roles_probe (id integer)"))
        for privilege in ("SELECT", *WRITES):
            assert _has_table(connection, "eval", "eval.roles_probe", privilege), privilege
            assert not _has_table(connection, "pipeline", "eval.roles_probe", privilege), privilege
        for schema in SERVICE_SCHEMAS:
            assert _has_table(connection, schema, "audit.roles_probe", "INSERT"), schema
            reads = role_name(schema) == AUDIT_READER
            assert _has_table(connection, schema, "audit.roles_probe", "SELECT") is reads, schema
            assert not _has_table(connection, schema, "audit.roles_probe", "UPDATE"), schema
        connection.execute(text("DROP TABLE eval.roles_probe, audit.roles_probe"))


def _refused(connection: Connection, sql: str, values: dict[str, Any] | None = None) -> str:
    """The SQLSTATE the statement fails with, in a savepoint so the transaction goes on."""
    savepoint = connection.begin_nested()
    try:
        connection.execute(text(sql), values or {})
    except DBAPIError as error:
        savepoint.rollback()
        return str(getattr(error.orig, "sqlstate", ""))
    savepoint.rollback()
    raise AssertionError(f"not refused: {sql}")


def _as_tenant(connection: Connection, tenant: TenantId) -> None:
    connection.execute(
        text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant.value)}
    )


def test_a_service_role_adds_audit_rows_that_only_identity_reads(
    owner_url: str, owner: Engine, first_migration_writes: dict[str, bool]
) -> None:
    tenant, other = TenantId(uuid4()), TenantId(uuid4())
    action = f"roles.check.run_{uuid4().hex[:8]}"
    with owner.begin() as connection:
        AuditWriter().write(connection, audit_entry(tenant_id=tenant, action=action))
        AuditWriter().write(connection, audit_entry(tenant_id=None, action=action))

    profile = create_engine(as_role(owner_url, "profile"))
    with profile.connect() as connection, connection.begin():
        _as_tenant(connection, tenant)
        AuditWriter().write(connection, audit_entry(tenant_id=tenant, action=action))
        AuditWriter().write(connection, audit_entry(tenant_id=None, action=action))
        row = {"id": uuid4(), "tenant": other.value}
        assert (
            _refused(
                connection,
                "INSERT INTO audit.event (id, occurred_at, tenant_id, action, subject_type, "
                "subject_id, actor_kind, actor_id, actor_label, reason, correlation_id) VALUES "
                "(:id, now(), :tenant, 'roles.check.other', 'thing', 'x', 'system', 'test', '', "
                "'', '')",
                row,
            )
            == INSUFFICIENT_PRIVILEGE
        ), "another tenant's row passes the policy"
        assert _refused(connection, "SELECT count(*) FROM audit.event") == INSUFFICIENT_PRIVILEGE
        assert (
            _refused(connection, "UPDATE audit.event SET reason = 'changed'")
            == INSUFFICIENT_PRIVILEGE
        )
        assert _refused(connection, "SELECT count(*) FROM identity.tenant") == (
            INSUFFICIENT_PRIVILEGE
        )
    profile.dispose()

    identity = create_engine(as_role(owner_url, "identity"))
    count = "SELECT count(*) FROM audit.event WHERE action = :action"
    with identity.connect() as connection, connection.begin():
        assert connection.execute(text(count), {"action": action}).scalar_one() == 0
        _as_tenant(connection, tenant)
        assert connection.execute(text(count), {"action": action}).scalar_one() == 2
        # The regulatory scope adds the rows of no tenant (identity migration 0006).
        connection.execute(text("SELECT set_config('app.audit_scope', 'regulatory', true)"))
        assert connection.execute(text(count), {"action": action}).scalar_one() == 4
        assert (
            _refused(
                connection,
                "UPDATE identity.alembic_version SET version_num = version_num",
            )
            == INSUFFICIENT_PRIVILEGE
        )
        assert connection.execute(
            text("SELECT count(*) FROM identity.alembic_version")
        ).scalar_one()
    identity.dispose()


def test_running_the_file_again_changes_nothing_and_cuts_a_widened_role_back(
    owner_url: str, owner: Engine, first_migration_writes: dict[str, bool]
) -> None:
    with owner.connect() as connection:
        before = _privileges(connection)
    apply_roles(owner_url)
    with owner.connect() as connection:
        assert _privileges(connection) == before

    with owner.begin() as connection:
        connection.execute(text("ALTER ROLE cw_eval SUPERUSER BYPASSRLS CREATEDB INHERIT"))
    apply_roles(owner_url)
    with owner.connect() as connection:
        row = connection.execute(
            text(
                "SELECT rolsuper, rolbypassrls, rolcreatedb, rolinherit, rolcanlogin "
                "FROM pg_roles WHERE rolname = 'cw_eval'"
            )
        ).one()
        assert tuple(row) == (False, False, False, False, True)
        assert _privileges(connection) == before


DIRECTORY_ROLE = "cw_identity_directory"


def test_the_identity_directory_counts_across_tenants_for_identity_only(
    owner_url: str, owner: Engine, first_migration_writes: dict[str, bool]
) -> None:
    with owner.connect() as connection:
        _check_the_directory_role(connection, owner_of(connection))
    tenants = [TenantId(uuid4()), TenantId(uuid4())]
    identity = create_engine(as_role(owner_url, "identity"))
    count = "SELECT coalesce(sum(open), 0) FROM identity.data_requests_open()"
    with identity.connect() as connection, connection.begin():
        before = connection.execute(text(count)).scalar_one()
        for tenant in tenants:
            _as_tenant(connection, tenant)
            connection.execute(
                text(
                    "INSERT INTO identity.data_request (id, tenant_id, kind, source, "
                    "requested_at, deadline_at, status) VALUES (:id, :tenant, 'export', "
                    "'self_service', now() - interval '40 days', now() - interval '10 days', "
                    "'received')"
                ),
                {"id": uuid4(), "tenant": tenant.value},
            )
        assert connection.execute(text(count)).scalar_one() == before + 2
        assert (
            connection.execute(text("SELECT count(*) FROM identity.data_request")).scalar_one() == 1
        ), "the role itself reads its current tenant's requests only"
        connection.rollback()
    identity.dispose()
    profile = create_engine(as_role(owner_url, "profile"))
    with profile.connect() as connection, connection.begin():
        assert _refused(connection, count) == INSUFFICIENT_PRIVILEGE
    profile.dispose()


def owner_of(connection: Connection) -> str:
    return str(connection.execute(text("SELECT current_user")).scalar_one())


def _check_the_directory_role(connection: Connection, owner: str) -> None:
    """NOLOGIN with no attribute at all, and no member but the owner, which does not inherit."""
    role = connection.execute(
        text(
            "SELECT rolcanlogin, rolsuper, rolbypassrls, rolinherit, rolcreatedb, rolcreaterole, "
            "rolreplication FROM pg_roles WHERE rolname = :r"
        ),
        {"r": DIRECTORY_ROLE},
    ).one()
    assert tuple(role) == (False,) * 7, "NOLOGIN, NOINHERIT and nothing else"
    members = connection.execute(
        text(
            "SELECT m.rolname, a.inherit_option FROM pg_auth_members a "
            "JOIN pg_roles m ON m.oid = a.member WHERE a.roleid = to_regrole(:r)"
        ),
        {"r": DIRECTORY_ROLE},
    ).all()
    assert {name for name, _ in members} <= {owner}, members
    assert not any(inherits for _, inherits in members), "the owner never inherits its reads"


FUNCTION = "identity.data_requests_open()"
DEPLOYMENT_OWNER = "cw_owner"
APP_ROLE = "cw_app"


def _psql(container: PostgresContainer, database: str, user: str, *args: str) -> str:
    """psql inside the container as ``user`` (the image trusts local connections)."""
    result = container.exec(
        ["psql", "-q", "-v", "ON_ERROR_STOP=1", "-U", user, "-d", database, *args]
    )
    output = result.output.decode()
    assert result.exit_code == 0, output
    return output


@pytest.fixture(scope="module")
def deployment() -> Iterator[tuple[PostgresContainer, str]]:
    """A database whose schemas belong to a login that may create roles but is neither a
    superuser nor bypasses row-level security, as a managed Postgres gives a deployment; the
    platform installed pgvector. The owner runs the role files and identity's migrations."""
    container = PostgresContainer(POSTGRES_IMAGE, driver="psycopg").with_volume_mapping(
        str(sql_dir()), "/role-files", "ro"
    )
    with container:
        superuser = container.get_connection_url()
        admin = create_engine(superuser, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(
                text(
                    f"CREATE ROLE {DEPLOYMENT_OWNER} LOGIN PASSWORD '{DEPLOYMENT_OWNER}' "
                    "NOSUPERUSER NOBYPASSRLS CREATEROLE"
                )
            )
            connection.execute(text(f"CREATE DATABASE deployment OWNER {DEPLOYMENT_OWNER}"))
        admin.dispose()
        url = (
            make_url(superuser)
            .set(username=DEPLOYMENT_OWNER, password=DEPLOYMENT_OWNER, database="deployment")
            .render_as_string(hide_password=False)
        )
        platform = create_engine(
            make_url(superuser).set(database="deployment"), isolation_level="AUTOCOMMIT"
        )
        with platform.connect() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        platform.dispose()
        engine = create_engine(url, isolation_level="AUTOCOMMIT")
        with engine.connect() as connection:
            for schema in (*SERVICE_SCHEMAS, AUDIT):
                connection.execute(text(f"CREATE SCHEMA {schema}"))
        engine.dispose()
        apply_roles(url)
        settings = ReleaseSettings(
            _env_file=None,
            service_name="cw-mvp-release",
            env="test",
            log_level="WARNING",
            database_url=RUNTIME,
            migration_database_url=SecretStr(url),
        )
        migrate(settings, services=["identity"])
        apply_roles(url)
        _psql(
            container,
            "deployment",
            DEPLOYMENT_OWNER,
            "-v",
            f"app_user={APP_ROLE}",
            "-v",
            f"app_password={APP_ROLE}",
            "-f",
            "/role-files/50-app-role.sql",
        )
        apply_roles(url)
        yield container, url


def test_with_an_owner_that_is_not_a_superuser_public_cannot_count(
    deployment: tuple[PostgresContainer, str],
) -> None:
    _, url = deployment
    owner = create_engine(url)
    try:
        with owner.connect() as connection:
            _check_the_directory_role(connection, DEPLOYMENT_OWNER)
            function_owner, acl = connection.execute(
                text(
                    "SELECT proowner::regrole::text, proacl::text FROM pg_proc "
                    f"WHERE oid = '{FUNCTION}'::regprocedure"
                )
            ).one()
            assert function_owner == DIRECTORY_ROLE
            grantees = {entry.split("=")[0] for entry in acl.strip("{}").split(",")}
            assert grantees == {DIRECTORY_ROLE, "cw_identity", APP_ROLE}, "no PUBLIC entry"
            runs = {
                role: connection.execute(
                    text("SELECT has_function_privilege(:role, :function, 'EXECUTE')"),
                    {"role": role, "function": FUNCTION},
                ).scalar_one()
                for role in ("cw_identity", APP_ROLE, "cw_profile", "cw_obligation")
            }
            assert runs == {
                "cw_identity": True,
                APP_ROLE: True,
                "cw_profile": False,
                "cw_obligation": False,
            }
    finally:
        owner.dispose()


def test_with_an_owner_that_is_not_a_superuser_the_rows_are_read_only_through_the_role(
    deployment: tuple[PostgresContainer, str],
) -> None:
    _, url = deployment
    tenants = [TenantId(uuid4()), TenantId(uuid4())]
    identity = create_engine(as_role(url, "identity"))
    owner = create_engine(url)
    count = "SELECT coalesce(sum(open), 0) FROM identity.data_requests_open()"
    try:
        with identity.begin() as connection:
            for tenant in tenants:
                _as_tenant(connection, tenant)
                connection.execute(
                    text(
                        "INSERT INTO identity.data_request (id, tenant_id, kind, source, "
                        "requested_at, deadline_at, status) VALUES (:id, :tenant, 'deletion', "
                        "'self_service', now() - interval '40 days', "
                        "now() - interval '10 days', 'received')"
                    ),
                    {"id": uuid4(), "tenant": tenant.value},
                )
        with identity.connect() as connection:
            assert connection.execute(text(count)).scalar_one() == 2
            seen = connection.execute(text("SELECT count(*) FROM identity.data_request"))
            assert seen.scalar_one() == 0, "without a tenant, row-level security hides every row"
        with owner.connect() as connection:
            seen = connection.execute(text("SELECT count(*) FROM identity.data_request"))
            assert seen.scalar_one() == 0, "the owner does not inherit the directory's reads"
        with owner.connect() as connection, connection.begin():
            # It may SET ROLE to read through the policy, as the runbook does: it owns the
            # tables and could switch their row-level security off anyway.
            connection.execute(text(f"SET LOCAL ROLE {DIRECTORY_ROLE}"))
            seen = connection.execute(text("SELECT count(*) FROM identity.data_request"))
            assert seen.scalar_one() == 2
            assert (
                _refused(connection, "DELETE FROM identity.data_request") == INSUFFICIENT_PRIVILEGE
            ), "the directory role only reads"
    finally:
        identity.dispose()
        owner.dispose()
