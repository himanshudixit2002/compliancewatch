"""tenants, users and roles, the subject index, service clients and the outbox

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-29

Hand-written; mirrors identity.infrastructure.models. Expand-only: new tables that nothing reads
before this release.

- tenant: row-level security enabled and forced, with a policy on the tenant's own id, so a unit
  of work sees and writes the tenant its app.tenant_id setting names and no other. A partial
  unique index allows one internal tenant.
- app_user: row-level security by tenant_id (py_common.migrations.enable_tenant_rls). The roles
  column holds known roles only, and each user has an email address or a phone number.
- user_subject: which user and tenant an identity provider's subject signs in as. No row-level
  security: the session exchange reads it before it knows the tenant, and it holds ids only.
- service_client: the clients that get service tokens, with the SHA-256 of each secret. No
  row-level security: a client belongs to no tenant.
- outbox_event, for tenant.created and user.role.changed (py_common.outbox).

infra/scripts/migration_lint.toml exempts tenant (its policy is on id, not tenant_id),
user_subject and service_client, each with the reason.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from py_common.migrations import drop_tenant_rls, enable_tenant_rls
from py_common.outbox import create_outbox_table, drop_outbox_table

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_KINDS = ("business", "ca_firm", "internal")
TENANT_STATUSES = ("active", "deletion_requested", "erased")
REGIONS = ("in",)
USER_STATUSES = ("active", "disabled")
ROLES = (
    "owner",
    "staff",
    "ca_admin",
    "ca_staff",
    "compliance_lead",
    "analyst",
    "reviewer",
    "admin",
)
TENANT_POLICY = "tenant_tenant_isolation"
TENANT_MATCH = "id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"

NO_RLS = "No row-level security: "
SUBJECT_COMMENT = (
    NO_RLS + "which user, in which tenant, an identity provider's subject signs in as. The "
    "session exchange reads it before it knows the tenant, so no tenant setting can apply; it "
    "holds ids only."
)
SERVICE_CLIENT_COMMENT = (
    NO_RLS + "service clients belong to no tenant. It holds client ids, the SHA-256 of each "
    "secret and the scopes; the secret itself is never stored."
)


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(f"'{value}'" for value in values)})"


def _subset(column: str, values: tuple[str, ...]) -> str:
    return f"{column} <@ ARRAY[{', '.join(f"'{value}'" for value in values)}]::varchar[]"


def upgrade() -> None:
    op.create_table(
        "tenant",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("region", sa.String(length=8), nullable=False, server_default="in"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_tenant"),
        sa.CheckConstraint(_in_list("kind", TENANT_KINDS), name="ck_tenant_kind"),
        sa.CheckConstraint(_in_list("status", TENANT_STATUSES), name="ck_tenant_status"),
        sa.CheckConstraint(_in_list("region", REGIONS), name="ck_tenant_region"),
        sa.CheckConstraint("btrim(name) <> ''", name="ck_tenant_name"),
        comment="Tenants; row-level security admits the tenant the setting names (by id)",
    )
    op.create_index(
        "ux_tenant_internal",
        "tenant",
        ["kind"],
        unique=True,
        postgresql_where=sa.text("kind = 'internal'"),
    )
    op.execute("ALTER TABLE tenant ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {TENANT_POLICY} ON tenant "
        f"USING ({TENANT_MATCH}) WITH CHECK ({TENANT_MATCH})"
    )

    op.create_table(
        "app_user",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_subject", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False, server_default=""),
        sa.Column("phone", sa.String(length=16), nullable=False, server_default=""),
        sa.Column("display_name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("roles", postgresql.ARRAY(sa.String(length=32)), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("session_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_app_user"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name="fk_app_user_tenant"),
        sa.UniqueConstraint(
            "tenant_id", "provider", "provider_subject", name="uq_app_user_provider_subject"
        ),
        sa.CheckConstraint(_subset("roles", ROLES), name="ck_app_user_roles"),
        sa.CheckConstraint("cardinality(roles) > 0", name="ck_app_user_roles_present"),
        sa.CheckConstraint(_in_list("status", USER_STATUSES), name="ck_app_user_status"),
        sa.CheckConstraint("session_version >= 0", name="ck_app_user_session_version"),
        sa.CheckConstraint("email <> '' OR phone <> ''", name="ck_app_user_contact"),
        sa.CheckConstraint(
            "phone = '' OR phone ~ '^\\+[1-9][0-9]{7,14}$'", name="ck_app_user_phone"
        ),
        comment="Users of a tenant and their roles; row-level security by tenant_id",
    )
    op.create_index("ix_app_user_tenant_created", "app_user", ["tenant_id", "created_at"])
    enable_tenant_rls(op, "app_user")

    op.create_table(
        "user_subject",
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_subject", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("provider", "provider_subject", name="pk_user_subject"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app_user.id"], name="fk_user_subject_user", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name="fk_user_subject_tenant"),
        comment=SUBJECT_COMMENT,
    )
    op.create_index("ux_user_subject_user", "user_subject", ["user_id"], unique=True)

    op.create_table(
        "service_client",
        sa.Column("client_id", sa.String(length=128), nullable=False),
        sa.Column("secret_sha256", sa.String(length=64), nullable=False),
        sa.Column("scopes", postgresql.ARRAY(sa.String(length=64)), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("client_id", name="pk_service_client"),
        sa.CheckConstraint("client_id ~ '^[a-z0-9][a-z0-9._-]*$'", name="ck_service_client_id"),
        sa.CheckConstraint("secret_sha256 ~ '^[0-9a-f]{64}$'", name="ck_service_client_secret"),
        comment=SERVICE_CLIENT_COMMENT,
    )

    create_outbox_table(op)


def downgrade() -> None:
    drop_outbox_table(op)
    op.drop_table("service_client")
    op.drop_index("ux_user_subject_user", table_name="user_subject")
    op.drop_table("user_subject")
    drop_tenant_rls(op, "app_user")
    op.drop_index("ix_app_user_tenant_created", table_name="app_user")
    op.drop_table("app_user")
    op.execute(f"DROP POLICY IF EXISTS {TENANT_POLICY} ON tenant")
    op.drop_index("ux_tenant_internal", table_name="tenant")
    op.drop_table("tenant")
