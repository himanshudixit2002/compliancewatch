"""SQLAlchemy rows of the identity service; mirrored by the migrations."""

import uuid
from datetime import datetime
from typing import Final

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from domain_kernel.access import MAX_CLIENT_ID_CHARS, Role
from identity.domain.billing import SubscriptionStatus
from identity.domain.channel_consent import (
    CHANNEL_PURPOSES,
    CHANNEL_SOURCES,
    MESSAGE_ID_MAX_LENGTH,
    ConsentChannel,
)
from identity.domain.consent import ConsentPurpose, ConsentSource
from identity.domain.tenancy import (
    MAX_EMAIL_CHARS,
    MAX_NAME_CHARS,
    MAX_PROVIDER_CHARS,
    MAX_SUBJECT_CHARS,
    REGIONS,
    TenantKind,
    TenantStatus,
    UserStatus,
)

PURPOSES: Final[tuple[str, ...]] = tuple(p.value for p in ConsentPurpose)
SOURCES: Final[tuple[str, ...]] = tuple(s.value for s in ConsentSource)
TENANT_SETTING: Final[str] = "app.tenant_id"
CHANNELS: Final[tuple[str, ...]] = tuple(c.value for c in ConsentChannel)
CHANNEL_PURPOSE_VALUES: Final[tuple[str, ...]] = tuple(
    dict.fromkeys(p.value for purposes in CHANNEL_PURPOSES.values() for p in purposes)
)
CHANNEL_SOURCE_VALUES: Final[tuple[str, ...]] = tuple(
    dict.fromkeys(s.value for sources in CHANNEL_SOURCES.values() for s in sources)
)
CHANNEL_SUBJECT_PATTERN: Final[str] = "^[1-9][0-9]{7,14}$"
TENANT_KINDS: Final[tuple[str, ...]] = tuple(k.value for k in TenantKind)
TENANT_STATUSES: Final[tuple[str, ...]] = tuple(s.value for s in TenantStatus)
USER_STATUSES: Final[tuple[str, ...]] = tuple(s.value for s in UserStatus)
ROLES: Final[tuple[str, ...]] = tuple(r.value for r in Role)
USER_PHONE_PATTERN: Final[str] = "^\\+[1-9][0-9]{7,14}$"
SECRET_SHA256_PATTERN: Final[str] = "^[0-9a-f]{64}$"
CLIENT_ID_PATTERN: Final[str] = "^[a-z0-9][a-z0-9._-]*$"
NO_RLS: Final[str] = "No row-level security: "
INTERNAL_TENANT_INDEX: Final[str] = "ux_tenant_internal"
SUBSCRIPTION_STATUSES: Final[tuple[str, ...]] = tuple(s.value for s in SubscriptionStatus)
BILLING_EVENT_DIGEST: Final[str] = "uq_billing_event_body"
PROVIDER_ID_CHARS: Final = 64
START_KEY_CHARS: Final = 128
"""py_common.idempotency's longest key."""


def sql_in_list(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"


def sql_subset(column: str, values: tuple[str, ...]) -> str:
    """``column``, a text array, holds only ``values``."""
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} <@ ARRAY[{quoted}]::varchar[]"


class Base(DeclarativeBase):
    pass


class ConsentRow(Base):
    __tablename__ = "consent_record"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_consent_record"),
        CheckConstraint(sql_in_list("purpose", PURPOSES), name="ck_consent_record_purpose"),
        CheckConstraint(sql_in_list("source", SOURCES), name="ck_consent_record_source"),
        CheckConstraint(
            "NOT granted OR notice_version <> ''", name="ck_consent_record_notice_version"
        ),
        Index("ix_consent_record_subject", "tenant_id", "subject", "recorded_at"),
        {"comment": "Append-only consent records; row-level security by tenant_id"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid())
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(), nullable=False)
    subject: Mapped[str] = mapped_column(String(length=254), nullable=False)
    purpose: Mapped[str] = mapped_column(String(length=32), nullable=False)
    granted: Mapped[bool] = mapped_column(Boolean(), nullable=False)
    source: Mapped[str] = mapped_column(String(length=32), nullable=False)
    notice_version: Mapped[str] = mapped_column(String(length=40), nullable=False, default="")
    evidence: Mapped[str] = mapped_column(Text(), nullable=False, default="")
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ChannelConsentRow(Base):
    __tablename__ = "channel_consent"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_channel_consent"),
        CheckConstraint(sql_in_list("channel", CHANNELS), name="ck_channel_consent_channel"),
        CheckConstraint(
            f"subject ~ '{CHANNEL_SUBJECT_PATTERN}'", name="ck_channel_consent_subject"
        ),
        CheckConstraint(
            sql_in_list("purpose", CHANNEL_PURPOSE_VALUES), name="ck_channel_consent_purpose"
        ),
        CheckConstraint(
            sql_in_list("source", CHANNEL_SOURCE_VALUES), name="ck_channel_consent_source"
        ),
        CheckConstraint(
            "NOT granted OR notice_version <> ''", name="ck_channel_consent_notice_version"
        ),
        Index(
            "ux_channel_consent_message",
            "channel",
            "message_id",
            unique=True,
            postgresql_where=text("message_id <> ''"),
        ),
        Index("ix_channel_consent_subject", "channel", "subject", "recorded_at"),
        {
            "comment": (
                "Append-only consents typed on a channel, keyed by phone number before any "
                "tenant owns it; no tenant_id"
            )
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid())
    channel: Mapped[str] = mapped_column(String(length=16), nullable=False)
    subject: Mapped[str] = mapped_column(String(length=16), nullable=False)
    purpose: Mapped[str] = mapped_column(String(length=32), nullable=False)
    granted: Mapped[bool] = mapped_column(Boolean(), nullable=False)
    source: Mapped[str] = mapped_column(String(length=32), nullable=False)
    notice_version: Mapped[str] = mapped_column(
        String(length=40), nullable=False, default="", server_default=""
    )
    evidence: Mapped[str] = mapped_column(Text(), nullable=False, default="", server_default="")
    message_id: Mapped[str] = mapped_column(
        String(length=MESSAGE_ID_MAX_LENGTH), nullable=False, default="", server_default=""
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TenantRow(Base):
    __tablename__ = "tenant"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_tenant"),
        CheckConstraint(sql_in_list("kind", TENANT_KINDS), name="ck_tenant_kind"),
        CheckConstraint(sql_in_list("status", TENANT_STATUSES), name="ck_tenant_status"),
        CheckConstraint(sql_in_list("region", REGIONS), name="ck_tenant_region"),
        CheckConstraint("btrim(name) <> ''", name="ck_tenant_name"),
        Index(
            INTERNAL_TENANT_INDEX,
            "kind",
            unique=True,
            postgresql_where=text("kind = 'internal'"),
        ),
        {"comment": "Tenants; row-level security admits the tenant the setting names (by id)"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid())
    kind: Mapped[str] = mapped_column(String(length=16), nullable=False)
    name: Mapped[str] = mapped_column(String(length=MAX_NAME_CHARS), nullable=False)
    region: Mapped[str] = mapped_column(String(length=8), nullable=False, server_default="in")
    status: Mapped[str] = mapped_column(String(length=24), nullable=False, server_default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class UserRow(Base):
    __tablename__ = "app_user"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_app_user"),
        ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name="fk_app_user_tenant"),
        UniqueConstraint(
            "tenant_id", "provider", "provider_subject", name="uq_app_user_provider_subject"
        ),
        CheckConstraint(sql_subset("roles", ROLES), name="ck_app_user_roles"),
        CheckConstraint("cardinality(roles) > 0", name="ck_app_user_roles_present"),
        CheckConstraint(sql_in_list("status", USER_STATUSES), name="ck_app_user_status"),
        CheckConstraint("session_version >= 0", name="ck_app_user_session_version"),
        CheckConstraint("email <> '' OR phone <> ''", name="ck_app_user_contact"),
        CheckConstraint(f"phone = '' OR phone ~ '{USER_PHONE_PATTERN}'", name="ck_app_user_phone"),
        Index("ix_app_user_tenant_created", "tenant_id", "created_at"),
        {"comment": "Users of a tenant and their roles; row-level security by tenant_id"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid())
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(), nullable=False)
    provider: Mapped[str] = mapped_column(String(length=MAX_PROVIDER_CHARS), nullable=False)
    provider_subject: Mapped[str] = mapped_column(String(length=MAX_SUBJECT_CHARS), nullable=False)
    email: Mapped[str] = mapped_column(
        String(length=MAX_EMAIL_CHARS), nullable=False, default="", server_default=""
    )
    phone: Mapped[str] = mapped_column(
        String(length=16), nullable=False, default="", server_default=""
    )
    display_name: Mapped[str] = mapped_column(
        String(length=MAX_NAME_CHARS), nullable=False, default="", server_default=""
    )
    roles: Mapped[list[str]] = mapped_column(ARRAY(String(length=32)), nullable=False)
    status: Mapped[str] = mapped_column(String(length=16), nullable=False, server_default="active")
    session_version: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


SUBJECT_COMMENT: Final[str] = (
    NO_RLS + "which user, in which tenant, an identity provider's subject signs in as. The "
    "session exchange reads it before it knows the tenant, so no tenant setting can apply; it "
    "holds ids only."
)
SERVICE_CLIENT_COMMENT: Final[str] = (
    NO_RLS + "service clients belong to no tenant. It holds client ids, the SHA-256 of each "
    "secret and the scopes; the secret itself is never stored."
)


class UserSubjectRow(Base):
    __tablename__ = "user_subject"
    __table_args__ = (
        PrimaryKeyConstraint("provider", "provider_subject", name="pk_user_subject"),
        ForeignKeyConstraint(
            ["user_id"], ["app_user.id"], name="fk_user_subject_user", ondelete="CASCADE"
        ),
        ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name="fk_user_subject_tenant"),
        Index("ux_user_subject_user", "user_id", unique=True),
        {"comment": SUBJECT_COMMENT},
    )

    provider: Mapped[str] = mapped_column(String(length=MAX_PROVIDER_CHARS))
    provider_subject: Mapped[str] = mapped_column(String(length=MAX_SUBJECT_CHARS))
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(), nullable=False)


class ServiceClientRow(Base):
    __tablename__ = "service_client"
    __table_args__ = (
        PrimaryKeyConstraint("client_id", name="pk_service_client"),
        CheckConstraint(f"client_id ~ '{CLIENT_ID_PATTERN}'", name="ck_service_client_id"),
        CheckConstraint(
            f"secret_sha256 ~ '{SECRET_SHA256_PATTERN}'", name="ck_service_client_secret"
        ),
        {"comment": SERVICE_CLIENT_COMMENT},
    )

    client_id: Mapped[str] = mapped_column(String(length=MAX_CLIENT_ID_CHARS))
    secret_sha256: Mapped[str] = mapped_column(String(length=64), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String(length=64)), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BillingCustomerRow(Base):
    __tablename__ = "billing_customer"
    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", name="pk_billing_customer"),
        {"comment": "A tenant's customer at the billing provider; row-level security by tenant_id"},
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid())
    provider: Mapped[str] = mapped_column(String(length=32), nullable=False)
    provider_customer_id: Mapped[str] = mapped_column(
        String(length=PROVIDER_ID_CHARS), nullable=False
    )
    email: Mapped[str] = mapped_column(String(length=MAX_EMAIL_CHARS), nullable=False)
    name: Mapped[str] = mapped_column(String(length=MAX_NAME_CHARS), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BillingSubscriptionRow(Base):
    __tablename__ = "billing_subscription"
    __table_args__ = (
        PrimaryKeyConstraint("provider_subscription_id", name="pk_billing_subscription"),
        CheckConstraint(
            sql_in_list("status", SUBSCRIPTION_STATUSES), name="ck_billing_subscription_status"
        ),
        CheckConstraint("quantity >= 1", name="ck_billing_subscription_quantity"),
        Index("ix_billing_subscription_tenant_started", "tenant_id", "started_at"),
        {
            "comment": (
                "A tenant's subscriptions at the billing provider and their current status; "
                "row-level security by tenant_id"
            )
        },
    )

    provider_subscription_id: Mapped[str] = mapped_column(String(length=PROVIDER_ID_CHARS))
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(), nullable=False)
    plan_key: Mapped[str] = mapped_column(String(length=64), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="1")
    status: Mapped[str] = mapped_column(String(length=16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    checkout_url: Mapped[str] = mapped_column(Text(), nullable=False, server_default="")
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    past_due_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BillingStartRow(Base):
    __tablename__ = "billing_start"
    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "idempotency_key", name="pk_billing_start"),
        CheckConstraint("quantity >= 1", name="ck_billing_start_quantity"),
        {
            "comment": (
                "Subscription starts by Idempotency-Key, recorded before the provider is called; "
                "row-level security by tenant_id"
            )
        },
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid())
    idempotency_key: Mapped[str] = mapped_column(String(length=START_KEY_CHARS))
    plan_key: Mapped[str] = mapped_column(String(length=64), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provider_subscription_id: Mapped[str | None] = mapped_column(
        String(length=PROVIDER_ID_CHARS), nullable=True
    )
    checkout_url: Mapped[str] = mapped_column(Text(), nullable=False, server_default="")
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BillingEventRow(Base):
    __tablename__ = "billing_event"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_billing_event"),
        UniqueConstraint("tenant_id", "body_sha256", name=BILLING_EVENT_DIGEST),
        CheckConstraint(
            "status IS NULL OR " + sql_in_list("status", SUBSCRIPTION_STATUSES),
            name="ck_billing_event_status",
        ),
        CheckConstraint(
            f"body_sha256 ~ '{SECRET_SHA256_PATTERN}'", name="ck_billing_event_body_sha256"
        ),
        Index(
            "ix_billing_event_subscription",
            "tenant_id",
            "provider_subscription_id",
            "received_at",
        ),
        {
            "comment": (
                "Append-only verified billing webhooks with the payload masked; row-level "
                "security by tenant_id"
            )
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid())
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(), nullable=False)
    provider_subscription_id: Mapped[str] = mapped_column(
        String(length=PROVIDER_ID_CHARS), nullable=False, server_default=""
    )
    kind: Mapped[str] = mapped_column(String(length=64), nullable=False)
    status: Mapped[str | None] = mapped_column(String(length=16), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    body_sha256: Mapped[str] = mapped_column(String(length=64), nullable=False)
    raw_event: Mapped[dict[str, object]] = mapped_column(JSONB(), nullable=False)
