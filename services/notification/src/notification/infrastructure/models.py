"""SQLAlchemy rows of the notification service; mirrored by the migrations.

Tenant tables (row-level security by ``tenant_id``): recipient, recipient_address,
recipient_business and notification. Tables without row-level security, each with the reason in
its comment: channel_preference, suppression, address_directory and work_index.
"""

import uuid
from datetime import datetime, time
from typing import Any, Final

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from domain_kernel.channels import Channel
from notification.domain.notification import DeliveryState
from notification.domain.occasions import OccasionKind
from notification.domain.preferences import ConsentSource, SuppressionReason
from notification.domain.recipients import DigestMode, RecipientRole
from notification.domain.repository import WorkKind

CHANNELS: Final[tuple[str, ...]] = tuple(channel.value for channel in Channel)
STATES: Final[tuple[str, ...]] = tuple(state.value for state in DeliveryState)
OCCASIONS: Final[tuple[str, ...]] = tuple(kind.value for kind in OccasionKind)
SOURCES: Final[tuple[str, ...]] = tuple(source.value for source in ConsentSource)
SUPPRESSION_REASONS: Final[tuple[str, ...]] = tuple(reason.value for reason in SuppressionReason)
WORK_KINDS: Final[tuple[str, ...]] = tuple(kind.value for kind in WorkKind)
WORK_STATUSES: Final[tuple[str, ...]] = ("pending", "done")
RECIPIENT_ROLES: Final[tuple[str, ...]] = tuple(role.value for role in RecipientRole)
DIGEST_MODES: Final[tuple[str, ...]] = tuple(mode.value for mode in DigestMode)
TENANT_SETTING: Final[str] = "app.tenant_id"
"""The session setting the row-level security policies read; set per transaction."""

NO_RLS = "No row-level security: "
PREFERENCE_COMMENT = (
    NO_RLS + "consent is per channel and normalised address, recorded before any tenant links the "
    "address (an opt-out typed on WhatsApp must be honoured for every tenant), with the time the "
    "address last wrote to us (the 24-hour WhatsApp window)."
)
SUPPRESSION_COMMENT = (
    NO_RLS + "a closed address (permanent bounce, complaint, or support) holds for every tenant "
    "that sends to it."
)
DIRECTORY_COMMENT = (
    NO_RLS + "routes an address to the tenants and recipients that registered it, for inbound "
    "messages and receipts that name only the address, and lists the tenants a retention sweep "
    "visits. It holds ids and addresses, no message content."
)
WORK_INDEX_COMMENT = (
    NO_RLS + "the dispatcher claims due work across tenants (FOR UPDATE SKIP LOCKED) and then "
    "handles each entry in a unit of work of its tenant; receipts find their tenant by the "
    "provider's message id. It holds ids and times, no message content."
)


def sql_in_list(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"


class Base(DeclarativeBase):
    pass


class RecipientRow(Base):
    """A person who receives a tenant's notifications. Keyed by tenant and id: one person may be
    a recipient of several tenants under one id, such as their user id."""

    __tablename__ = "recipient"
    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "id", name="pk_recipient"),
        CheckConstraint(sql_in_list("role", RECIPIENT_ROLES), name="ck_recipient_role"),
        CheckConstraint(sql_in_list("digest_mode", DIGEST_MODES), name="ck_recipient_digest_mode"),
        Index("ix_recipient_tenant_user", "tenant_id", "user_id"),
        {"comment": "Recipients of a tenant's notifications. Row-level security by tenant_id."},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False, server_default="en")
    digest_mode: Mapped[str] = mapped_column(String(8), nullable=False, server_default="off")
    org_label: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RecipientAddressRow(Base):
    """One address of a recipient; ``position`` orders them, the first open one is primary."""

    __tablename__ = "recipient_address"
    __table_args__ = (
        PrimaryKeyConstraint(
            "tenant_id", "recipient_id", "channel", "address", name="pk_recipient_address"
        ),
        UniqueConstraint(
            "tenant_id", "recipient_id", "position", name="uq_recipient_address_position"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "recipient_id"],
            ["recipient.tenant_id", "recipient.id"],
            name="fk_recipient_address_recipient",
            ondelete="CASCADE",
        ),
        CheckConstraint(sql_in_list("channel", CHANNELS), name="ck_recipient_address_channel"),
        CheckConstraint("position >= 0", name="ck_recipient_address_position"),
        {"comment": "Addresses of a recipient in order. Row-level security by tenant_id."},
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    recipient_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)


class RecipientBusinessRow(Base):
    """A business whose notifications the recipient receives."""

    __tablename__ = "recipient_business"
    __table_args__ = (
        PrimaryKeyConstraint(
            "tenant_id", "recipient_id", "business_id", name="pk_recipient_business"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "recipient_id"],
            ["recipient.tenant_id", "recipient.id"],
            name="fk_recipient_business_recipient",
            ondelete="CASCADE",
        ),
        Index("ix_recipient_business_business", "tenant_id", "business_id"),
        {
            "comment": (
                "The businesses each recipient hears about. Row-level security by tenant_id."
            )
        },
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    recipient_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False, server_default="")


class NotificationRow(Base):
    """One notification to one address, keyed once per occasion by ``dedupe_key``."""

    __tablename__ = "notification"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_notification"),
        UniqueConstraint("dedupe_key", name="uq_notification_dedupe_key"),
        ForeignKeyConstraint(
            ["fallback_of"],
            ["notification.id"],
            name="fk_notification_fallback_of_notification",
            ondelete="SET NULL",
        ),
        CheckConstraint(sql_in_list("channel", CHANNELS), name="ck_notification_channel"),
        CheckConstraint(sql_in_list("occasion", OCCASIONS), name="ck_notification_occasion"),
        CheckConstraint(sql_in_list("state", STATES), name="ck_notification_state"),
        CheckConstraint("attempts >= 0", name="ck_notification_attempts"),
        CheckConstraint(
            "state NOT IN ('sent', 'delivered', 'read') OR sent_at IS NOT NULL",
            name="ck_notification_sent_at",
        ),
        CheckConstraint(
            "state <> 'failed' OR failed_at IS NOT NULL", name="ck_notification_failed_at"
        ),
        Index("ix_notification_state_available", "state", "available_at"),
        Index("ix_notification_provider_message", "provider_message_id"),
        Index("ix_notification_business_created", "tenant_id", "business_id", "created_at"),
        Index("ix_notification_recipient_due", "recipient_id", "channel", "state", "available_at"),
        Index("ix_notification_dispatch", "dispatch_id"),
        Index("ix_notification_obligation", "obligation_id", "created_at"),
        {
            "comment": (
                "Notifications, one per occasion, recipient and channel (unique dedupe_key). "
                "Row-level security by tenant_id."
            )
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    obligation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    recipient_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    occasion: Mapped[str] = mapped_column(String(16), nullable=False)
    template_key: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    dedupe_key: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dispatch_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    provider_message_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    error: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    fallback_of: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ChannelPreferenceRow(Base):
    """Consent per channel and address; a row may hold only the last inbound time."""

    __tablename__ = "channel_preference"
    __table_args__ = (
        PrimaryKeyConstraint("channel", "address", name="pk_channel_preference"),
        CheckConstraint(sql_in_list("channel", CHANNELS), name="ck_channel_preference_channel"),
        CheckConstraint(
            f"source IS NULL OR {sql_in_list('source', SOURCES)}",
            name="ck_channel_preference_source",
        ),
        CheckConstraint(
            "(opted_in IS NULL) = (source IS NULL) AND (opted_in IS NULL) = (updated_at IS NULL)",
            name="ck_channel_preference_consent",
        ),
        CheckConstraint(
            "opted_in IS NOT NULL OR last_inbound_at IS NOT NULL",
            name="ck_channel_preference_not_empty",
        ),
        {"comment": PREFERENCE_COMMENT},
    )

    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    opted_in: Mapped[bool | None] = mapped_column(nullable=True)
    source: Mapped[str | None] = mapped_column(String(24), nullable=True)
    language: Mapped[str] = mapped_column(String(8), nullable=False, server_default="en")
    quiet_hours_start: Mapped[time] = mapped_column(
        Time, nullable=False, server_default=text("'21:00'")
    )
    quiet_hours_end: Mapped[time] = mapped_column(
        Time, nullable=False, server_default=text("'08:00'")
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SuppressionRow(Base):
    __tablename__ = "suppression"
    __table_args__ = (
        PrimaryKeyConstraint("channel", "address", name="pk_suppression"),
        CheckConstraint(sql_in_list("channel", CHANNELS), name="ck_suppression_channel"),
        CheckConstraint(sql_in_list("reason", SUPPRESSION_REASONS), name="ck_suppression_reason"),
        {"comment": SUPPRESSION_COMMENT},
    )

    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(String(16), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AddressDirectoryRow(Base):
    __tablename__ = "address_directory"
    __table_args__ = (
        PrimaryKeyConstraint(
            "channel", "address", "tenant_id", "recipient_id", name="pk_address_directory"
        ),
        CheckConstraint(sql_in_list("channel", CHANNELS), name="ck_address_directory_channel"),
        Index("ix_address_directory_recipient", "tenant_id", "recipient_id"),
        {"comment": DIRECTORY_COMMENT},
    )

    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    recipient_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)


class WorkIndexRow(Base):
    """A notification's place in the dispatch queue; its id is the notification's."""

    __tablename__ = "work_index"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_work_index"),
        ForeignKeyConstraint(
            ["id"], ["notification.id"], name="fk_work_index_id_notification", ondelete="CASCADE"
        ),
        CheckConstraint(sql_in_list("kind", WORK_KINDS), name="ck_work_index_kind"),
        CheckConstraint(sql_in_list("status", WORK_STATUSES), name="ck_work_index_status"),
        Index(
            "ix_work_index_due",
            "available_at",
            postgresql_where=text("status = 'pending'"),
        ),
        Index(
            "ix_work_index_provider_message",
            "provider_message_id",
            postgresql_where=text("provider_message_id <> ''"),
        ),
        Index("ix_work_index_tenant", "tenant_id"),
        {"comment": WORK_INDEX_COMMENT},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(8), nullable=False, server_default="pending")
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_message_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
