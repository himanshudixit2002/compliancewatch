"""SQLAlchemy rows of the identity service; mirrored by the migrations."""

import uuid
from datetime import datetime
from typing import Final

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    PrimaryKeyConstraint,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from identity.domain.channel_consent import (
    CHANNEL_PURPOSES,
    CHANNEL_SOURCES,
    MESSAGE_ID_MAX_LENGTH,
    ConsentChannel,
)
from identity.domain.consent import ConsentPurpose, ConsentSource

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


def sql_in_list(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"


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
