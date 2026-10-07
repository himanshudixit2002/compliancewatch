"""Migration 0003 on Postgres: tenants, users, the subject index, service clients and the outbox,
with row-level security on tenant and app_user checked through identity's own role. Needs Docker.

The role is ``cw_identity`` as infra/dev/postgres/roles.sql makes it, given to the database before
the migrations as on a fresh dev volume: it owns nothing and is not a superuser.
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
from sqlalchemy.exc import DBAPIError, IntegrityError
from testcontainers.community.postgres import PostgresContainer

from domain_kernel.access import ANONYMOUS, Role, Scope
from domain_kernel.ids import TenantId
from identity.application.bootstrap import (
    BootstrapInternalTenant,
    CreateServiceClient,
    ListServiceClients,
    RevokeServiceClient,
)
from identity.application.sessions import ExchangeSession, IssueServiceToken, user_principal
from identity.application.tenancy import (
    ChangeRoles,
    CreateTenant,
    DisableUser,
    InviteUser,
    ListUsers,
    admin_context,
)
from identity.domain.audit import AuditQuery, AuditScope
from identity.domain.errors import (
    InternalTenantExistsError,
    LastAdminError,
    SubjectRegisteredError,
    UserNotFoundError,
)
from identity.domain.events import RoleChangeReason, TenantCreated, UserRoleChanged, sorted_roles
from identity.domain.tenancy import Contact, SubjectEntry, Tenant, TenantKind, User
from identity.infrastructure.audit_reader import PostgresAuditReader
from identity.infrastructure.minter import IssuerMinter
from identity.infrastructure.models import Base
from identity.infrastructure.providers.fake import FakeIdentityProvider
from identity.infrastructure.repository import PostgresUnitOfWorkFactory
from py_common.auth import TokenIssuer
from py_common.auth.testing import TestIssuer
from py_common.db_roles import apply_roles, as_role

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "identity"
NEW_TABLES = ("tenant", "app_user", "user_subject", "service_client")
NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
PHONE = "+919876543210"


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    with PostgresContainer(IMAGE, driver="psycopg") as postgres:
        base_url = postgres.get_connection_url()
        admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
        admin.dispose()
        # The service's own role, as a fresh dev volume has it before the migrations:
        # the tables they create, again after a downgrade, reach it too.
        apply_roles(base_url)
        yield f"{base_url}?options=-csearch_path%3D{SCHEMA}%2Cpublic"


@pytest.fixture(scope="module")
def alembic_config(database_url: str) -> Iterator[Config]:
    with pytest.MonkeyPatch.context() as env:
        env.setenv("CW_DATABASE_URL", database_url)
        env.setenv("CW_DB_SCHEMA", SCHEMA)
        yield Config(str(SERVICE_DIR / "alembic.ini"))


@pytest.fixture(scope="module")
def engine(database_url: str, alembic_config: Config) -> Iterator[Engine]:
    command.upgrade(alembic_config, "head")
    engine = create_engine(database_url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def app_engine(database_url: str, engine: Engine) -> Iterator[Engine]:
    # Again after the migrations: identity's 0005 makes the audit schema, which the role must
    # be able to write to (USAGE and INSERT), as make migrate's db-roles step grants.
    apply_roles(database_url)
    engine = create_engine(as_role(database_url, SCHEMA))
    yield engine
    engine.dispose()


def tables(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names(schema=SCHEMA))


def new_tenant(kind: TenantKind = TenantKind.BUSINESS, name: str = "Acme Traders") -> Tenant:
    return Tenant(TenantId.new(), kind, name, NOW)


def first_user(tenant: Tenant, subject: str) -> User:
    return User.new(
        tenant,
        provider="fake",
        provider_subject=subject,
        contact=Contact(phone=PHONE),
        roles=[Role.OWNER if tenant.kind is TenantKind.BUSINESS else Role.ADMIN],
        at=NOW,
    )


def sign_up(factory: PostgresUnitOfWorkFactory, tenant: Tenant, user: User) -> None:
    with factory(tenant.id) as uow:
        uow.tenants.add(tenant)
        uow.users.add(user)
        uow.subjects.add(SubjectEntry.of(user))
        uow.events.publish(
            TenantCreated(
                tenant_id=tenant.id,
                kind=tenant.kind,
                region=tenant.region,
                created_by=user.id,
                created_at=NOW,
            )
        )
        uow.events.publish(
            UserRoleChanged(
                tenant_id=tenant.id,
                user_id=user.id,
                roles=sorted_roles(user.roles),
                previous_roles=(),
                reason=RoleChangeReason.CREATED,
                session_version=user.session_version,
                changed_by=user.id,
            )
        )


def outbox_topics(engine: Engine, tenant: Tenant) -> list[str]:
    with engine.connect() as connection:
        return list(
            connection.execute(
                text("SELECT topic FROM outbox_event WHERE tenant_id = :tenant ORDER BY topic"),
                {"tenant": tenant.id.value},
            ).scalars()
        )


def test_upgrade_downgrade_upgrade(alembic_config: Config, engine: Engine) -> None:
    assert set(NEW_TABLES) | {"outbox_event"} <= tables(engine)
    command.downgrade(alembic_config, "0002")
    assert tables(engine) == {"consent_record", "channel_consent", "alembic_version"}
    command.upgrade(alembic_config, "head")
    assert set(NEW_TABLES) | {"outbox_event"} <= tables(engine)


def test_models_and_migration_agree(engine: Engine) -> None:
    def only_new_tables(
        obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
    ) -> bool:
        table = name if type_ == "table" else getattr(getattr(obj, "table", None), "name", None)
        return table in NEW_TABLES

    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={
                "compare_type": True,
                "compare_server_default": True,
                "include_object": only_new_tables,
            },
        )
        assert compare_metadata(context, Base.metadata) == []
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT relname, relforcerowsecurity FROM pg_class c JOIN pg_namespace n "
                "ON n.oid = c.relnamespace WHERE n.nspname = :schema AND c.relkind = 'r'"
            ),
            {"schema": SCHEMA},
        )
        forced: dict[str, bool] = {row.relname: row.relforcerowsecurity for row in rows}
    assert forced["tenant"]
    assert forced["app_user"]
    assert not forced["user_subject"]
    assert not forced["service_client"]


def test_the_catalog_lint_passes_with_the_exemptions(engine: Engine) -> None:
    lint = importlib.import_module("check_migrations")  # infra/scripts, on the pytest path
    with engine.connect() as connection:
        raw = connection.connection.driver_connection
        catalog = [t for t in lint.read_tables(raw) if t.schema == SCHEMA]
    config = lint.load_config()
    for table in ("tenant", "user_subject", "service_client"):
        assert config.exemption_for(f"{SCHEMA}.{table}") is not None
    assert config.exemption_for(f"{SCHEMA}.app_user") is None
    assert [p for p in lint.catalog_problems(catalog, config) if p.startswith(f"{SCHEMA}.")] == []


def test_row_level_security_isolates_tenants_and_users(app_engine: Engine) -> None:
    factory = PostgresUnitOfWorkFactory(app_engine)
    acme, other = new_tenant(), new_tenant(name="Other Traders")
    owner, other_owner = first_user(acme, "rls-acme"), first_user(other, "rls-other")
    sign_up(factory, acme, owner)
    sign_up(factory, other, other_owner)
    with factory(acme.id) as uow:
        assert uow.tenants.get(acme.id) == acme
        assert uow.tenants.get(other.id) is None
        assert uow.users.list() == [owner]
        assert uow.users.get(other_owner.id) is None
    with factory(None) as uow:
        assert uow.tenants.get(acme.id) is None
        assert uow.users.list() == []
    with app_engine.connect() as connection:
        for table in ("tenant", "app_user"):
            assert connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0
    with pytest.raises(DBAPIError, match="row-level security"), factory(acme.id) as uow:
        uow.tenants.add(new_tenant(name="Smuggled"))


def test_reads_name_the_tenant_where_row_level_security_is_bypassed(engine: Engine) -> None:
    """The test database's user owns the tables and is a superuser, so row-level security does
    not apply to it, as for the dev stack's role: the queries' own tenant filter keeps tenants
    apart."""
    factory = PostgresUnitOfWorkFactory(engine)
    acme, other = new_tenant(), new_tenant(name="Other Traders")
    owner, other_owner = first_user(acme, "bypass-acme"), first_user(other, "bypass-other")
    sign_up(factory, acme, owner)
    sign_up(factory, other, other_owner)
    with factory(acme.id) as uow:
        assert uow.tenants.get(other.id) is None
        assert uow.users.get(other_owner.id) is None
        assert [user.id for user in uow.users.list()] == [owner.id]
    with factory(None) as uow:
        assert uow.tenants.get(acme.id) is None
        assert uow.users.get(owner.id) is None
        assert uow.users.list() == []
    as_acme = user_principal(owner, mfa=False)
    with pytest.raises(UserNotFoundError):
        ChangeRoles(factory).run(acme.id, as_acme, other_owner.id, [Role.STAFF])
    with pytest.raises(UserNotFoundError):
        DisableUser(factory).run(acme.id, as_acme, other_owner.id)
    assert [user.id for user in ListUsers(factory).run(acme.id, as_acme)] == [owner.id]
    with factory(other.id) as uow:
        assert uow.users.get(other_owner.id) == other_owner


def test_role_changes_are_saved_under_the_tenant(app_engine: Engine) -> None:
    factory = PostgresUnitOfWorkFactory(app_engine)
    acme = new_tenant()
    owner = first_user(acme, "save-acme")
    sign_up(factory, acme, owner)
    changed = owner.with_roles([Role.OWNER, Role.COMPLIANCE_LEAD], acme, colleagues=[], at=NOW)
    with factory(acme.id) as uow:
        uow.users.save(changed)
    with factory(acme.id) as uow:
        stored = uow.users.get(owner.id)
    assert stored == changed
    assert stored is not None
    assert stored.session_version == 1


def test_the_subject_index_answers_without_a_tenant(app_engine: Engine) -> None:
    factory = PostgresUnitOfWorkFactory(app_engine)
    acme = new_tenant()
    owner = first_user(acme, "subject-lookup")
    sign_up(factory, acme, owner)
    with factory(None) as uow:
        assert uow.subjects.find("fake", "subject-lookup") == SubjectEntry.of(owner)
        assert uow.subjects.find("fake", "nobody") is None


def test_the_outbox_rows_commit_and_roll_back_with_the_sign_up(
    app_engine: Engine, engine: Engine
) -> None:
    factory = PostgresUnitOfWorkFactory(app_engine)
    acme = new_tenant()
    owner = first_user(acme, "outbox-acme")
    sign_up(factory, acme, owner)
    assert outbox_topics(engine, acme) == ["tenant.created", "user.role.changed"]
    late = new_tenant(name="Late Traders")
    with pytest.raises(SubjectRegisteredError):
        sign_up(factory, late, first_user(late, "outbox-acme"))
    assert outbox_topics(engine, late) == []
    with factory(late.id) as uow:
        assert uow.tenants.get(late.id) is None
        assert uow.users.list() == []


def insert_user(app_engine: Engine, tenant: Tenant, **values: str) -> None:
    with app_engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant.id)}
        )
        connection.execute(
            text(
                "INSERT INTO app_user (id, tenant_id, provider, provider_subject, phone, roles, "
                "status, created_at, updated_at) VALUES (gen_random_uuid(), :tenant, 'fake', "
                ":subject, :phone, CAST(:roles AS varchar[]), :status, now(), now())"
            ),
            {"tenant": tenant.id.value, **values},
        )


@pytest.mark.parametrize(
    ("column", "value", "constraint"),
    [
        ("roles", "{partner}", "ck_app_user_roles"),
        ("roles", "{}", "ck_app_user_roles_present"),
        ("phone", "9876543210", "ck_app_user_phone"),
        ("status", "gone", "ck_app_user_status"),
    ],
)
def test_the_checks_refuse_what_the_domain_refuses(
    app_engine: Engine, column: str, value: str, constraint: str
) -> None:
    acme = new_tenant()
    sign_up(PostgresUnitOfWorkFactory(app_engine), acme, first_user(acme, f"checks-{constraint}"))
    values = {"roles": "{owner}", "phone": PHONE, "status": "active", column: value}
    subject = f"check-{constraint}"
    with pytest.raises(IntegrityError, match=constraint):
        insert_user(app_engine, acme, subject=subject, **values)


def test_there_is_one_internal_tenant(app_engine: Engine) -> None:
    factory = PostgresUnitOfWorkFactory(app_engine)
    provider = FakeIdentityProvider()
    bootstrap = BootstrapInternalTenant(factory, provider)
    tenant, admin = bootstrap.run("Regulatory team", Contact(email="admin@example.org"))
    with factory(tenant.id) as uow:
        assert uow.users.list() == [admin]
    second = Contact(email="second@example.org")
    with pytest.raises(InternalTenantExistsError):
        bootstrap.run("Second team", second)
    assert provider.lookup(provider.subject_for(second)) is None


def test_create_tenant_commits_its_outbox_rows_and_a_repeat_rolls_back(
    app_engine: Engine, engine: Engine
) -> None:
    factory = PostgresUnitOfWorkFactory(app_engine)
    provider = FakeIdentityProvider()
    issuer = TestIssuer()
    minter = IssuerMinter(
        TokenIssuer(issuer.keys, issuer=issuer.issuer_name, audience=issuer.audience)
    )
    create = CreateTenant(factory, provider, minter, ttl=timedelta(minutes=10))
    token = provider.issue(phone="+919800000001")
    created = create.run(token, TenantKind.BUSINESS, "Signed Up Traders")
    assert outbox_topics(engine, created.tenant) == ["tenant.created", "user.role.changed"]
    with pytest.raises(SubjectRegisteredError):
        create.run(token, TenantKind.BUSINESS, "Again Traders")
    session = ExchangeSession(factory, provider, minter, ttl=timedelta(minutes=10)).run(token)
    assert (session.tenant, session.user) == (created.tenant, created.user)
    with engine.connect() as connection:
        tenants: int = connection.execute(
            text("SELECT count(*) FROM tenant WHERE name = 'Again Traders'")
        ).scalar_one()
    assert tenants == 0


def test_service_clients_through_a_plain_role(app_engine: Engine) -> None:
    factory = PostgresUnitOfWorkFactory(app_engine)
    client, secret = CreateServiceClient(factory).run(
        "integration-client", frozenset({Scope.LLM_CALL})
    )
    issuer = TestIssuer()
    minter = IssuerMinter(
        TokenIssuer(issuer.keys, issuer=issuer.issuer_name, audience=issuer.audience)
    )
    issued = IssueServiceToken(factory, minter, ttl=timedelta(minutes=10)).run(
        "integration-client", secret
    )
    assert issued.principal.scopes == {Scope.LLM_CALL}
    revoked = RevokeServiceClient(factory).run("integration-client")
    assert revoked.revoked_at is not None
    listed = ListServiceClients(factory).run()
    assert [c.client_id for c in listed if c.client_id == client.client_id] == [client.client_id]
    with factory(None) as uow:
        stored = uow.service_clients.get("integration-client")
    assert stored == revoked
    platform = PostgresAuditReader(app_engine).page(
        AuditScope.REGULATORY, None, AuditQuery(subject_id="integration-client")
    )
    assert [entry.action for entry in platform] == [
        "service_client.revoked",
        "service_client.created",
    ]


def test_locking_a_tenant_makes_another_transaction_wait(app_engine: Engine) -> None:
    factory = PostgresUnitOfWorkFactory(app_engine)
    acme = new_tenant()
    sign_up(factory, acme, first_user(acme, "lock-acme"))
    tenant_setting = text("SELECT set_config('app.tenant_id', :tenant, true)")
    locked = text("SELECT id FROM tenant WHERE id = :tenant FOR UPDATE NOWAIT")
    with factory(acme.id) as uow:
        assert uow.tenants.lock(acme.id) == acme
        assert uow.tenants.lock(new_tenant().id) is None
        with app_engine.connect() as other:
            other.execute(tenant_setting, {"tenant": str(acme.id)})
            with pytest.raises(DBAPIError, match="could not obtain lock"):
                other.execute(locked, {"tenant": acme.id.value})
    with app_engine.connect() as other:
        other.execute(tenant_setting, {"tenant": str(acme.id)})
        assert other.execute(locked, {"tenant": acme.id.value}).scalar_one() == acme.id.value


def test_two_owners_demoted_at_once_leave_one_owner(app_engine: Engine) -> None:
    """The first demotion holds the tenant's lock while the second starts; the second waits,
    then sees the first and refuses to take the last owner."""
    factory = PostgresUnitOfWorkFactory(app_engine)
    provider = FakeIdentityProvider()
    issuer = TestIssuer()
    minter = IssuerMinter(
        TokenIssuer(issuer.keys, issuer=issuer.issuer_name, audience=issuer.audience)
    )
    created = CreateTenant(factory, provider, minter, ttl=timedelta(minutes=10)).run(
        provider.issue(phone="+919800000004"), TenantKind.BUSINESS, "Two Owners"
    )
    tenant, first = created.tenant, created.user
    second = InviteUser(factory, provider).run(
        tenant.id,
        created.session.principal,
        contact=Contact(phone="+919800000005"),
        roles=[Role.OWNER],
    )
    outcome: list[BaseException | User] = []

    def demote_the_first() -> None:
        try:
            outcome.append(ChangeRoles(factory).run(tenant.id, ANONYMOUS, first.id, [Role.STAFF]))
        except LastAdminError as exc:
            outcome.append(exc)

    racer = threading.Thread(target=demote_the_first)
    with factory(tenant.id) as uow:
        held, _ = admin_context(uow, tenant.id, ANONYMOUS, lock=True)
        stored = uow.users.get(second.id)
        assert stored is not None
        uow.users.save(stored.with_roles([Role.STAFF], held, colleagues=uow.users.list(), at=NOW))
        racer.start()
        racer.join(timeout=1.0)
        assert racer.is_alive(), "the second change waits for the tenant's lock"
    racer.join(timeout=30)
    assert not racer.is_alive()
    assert len(outcome) == 1
    assert isinstance(outcome[0], LastAdminError)
    with factory(tenant.id) as uow:
        owners = [user.id for user in uow.users.list() if Role.OWNER in user.roles]
    assert owners == [first.id]


def test_the_team_use_cases_through_a_plain_role(app_engine: Engine, engine: Engine) -> None:
    factory = PostgresUnitOfWorkFactory(app_engine)
    provider = FakeIdentityProvider()
    issuer = TestIssuer()
    minter = IssuerMinter(
        TokenIssuer(issuer.keys, issuer=issuer.issuer_name, audience=issuer.audience)
    )
    created = CreateTenant(factory, provider, minter, ttl=timedelta(minutes=10)).run(
        provider.issue(phone="+919800000002"), TenantKind.BUSINESS, "Team Traders"
    )
    owner = created.session.principal
    staff = InviteUser(factory, provider).run(
        created.tenant.id, owner, contact=Contact(phone="+919800000003"), roles=[Role.STAFF]
    )
    changed = ChangeRoles(factory).run(
        created.tenant.id, owner, staff.id, [Role.STAFF, Role.COMPLIANCE_LEAD]
    )
    disabled = DisableUser(factory).run(created.tenant.id, owner, staff.id)
    assert (changed.session_version, disabled.session_version) == (1, 2)
    users = ListUsers(factory).run(created.tenant.id, owner)
    assert [user.id for user in users] == [created.user.id, staff.id]
    assert users[1] == disabled
    with engine.connect() as connection:
        reasons: list[str] = list(
            connection.execute(
                text(
                    "SELECT message -> 'payload' ->> 'reason' FROM outbox_event "
                    "WHERE tenant_id = :tenant AND topic = 'user.role.changed' "
                    "ORDER BY created_at, message -> 'payload' ->> 'session_version'"
                ),
                {"tenant": created.tenant.id.value},
            ).scalars()
        )
    assert reasons == ["created", "invited", "roles_changed", "disabled"]
    # The audit entries, read back through identity's own role in the tenant's scope.
    trail = PostgresAuditReader(app_engine).page(
        AuditScope.TENANT, created.tenant.id, AuditQuery(limit=10)
    )
    assert [entry.action for entry in trail] == [
        "user.disabled",
        "user.roles_changed",
        "user.invited",
        "tenant.created",
    ]
    assert {entry.actor.id for entry in trail} == {str(created.user.id)}
