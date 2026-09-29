"""SQLAlchemy rows of the obligation service; mirrored by the migrations."""

import uuid
from datetime import date, datetime
from typing import Final

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from domain_kernel.status import ClosureReason, ObligationStatus
from obligation.domain.events import RescheduleReason
from obligation.domain.history import ChangeKind

STATUSES: Final[tuple[str, ...]] = tuple(status.value for status in ObligationStatus)
CLOSURE_REASONS: Final[tuple[str, ...]] = tuple(reason.value for reason in ClosureReason)
CHANGE_KINDS: Final[tuple[str, ...]] = tuple(kind.value for kind in ChangeKind)
CHANGE_REASONS: Final[tuple[str, ...]] = (
    "",
    *(reason.value for reason in RescheduleReason),
    *CLOSURE_REASONS,
)
TENANT_SETTING: Final[str] = "app.tenant_id"
"""The session setting the row-level security policy reads; set per transaction."""


def sql_in_list(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"


class Base(DeclarativeBase):
    pass


class ObligationRow(Base):
    """One obligation; for a recurring rule one row per (business, rule version, period)."""

    __tablename__ = "obligation"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_obligation"),
        UniqueConstraint(
            "business_id", "rule_version_id", "period_label", name="uq_obligation_period"
        ),
        CheckConstraint(sql_in_list("status", STATUSES), name="ck_obligation_status"),
        CheckConstraint(
            f"closed_reason IS NULL OR {sql_in_list('closed_reason', CLOSURE_REASONS)}",
            name="ck_obligation_closed_reason",
        ),
        CheckConstraint(
            "(status IN ('done', 'waived', 'closed_not_applicable')) = (closed_at IS NOT NULL)",
            name="ck_obligation_closed",
        ),
        CheckConstraint(
            "(period_label IS NULL) = (period_start IS NULL) AND "
            "(period_label IS NULL) = (period_end IS NULL)",
            name="ck_obligation_period",
        ),
        Index("ix_obligation_tenant_status_due", "tenant_id", "status", "due_at"),
        Index("ix_obligation_rule_version", "rule_version_id", "period_label"),
        {
            "comment": (
                "Obligations per business and period. Row-level security by tenant_id: the "
                "policy reads the app.tenant_id setting the unit of work sets per transaction."
            )
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    rule_version_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    decision_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    steps: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    evidence_type: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    period_label: Mapped[str | None] = mapped_column(String(20), nullable=True)
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_reason: Mapped[str | None] = mapped_column(String(24), nullable=True)
    closed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)


class ObligationChangeRow(Base):
    """One change of one obligation, keyed by the id of the event that made it. Append-only: a
    trigger refuses UPDATE, and DELETE outside a tenant's erasure (migration 0002)."""

    __tablename__ = "obligation_change"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_obligation_change"),
        ForeignKeyConstraint(
            ["obligation_id"],
            ["obligation.id"],
            name="fk_obligation_change_obligation_id_obligation",
            ondelete="RESTRICT",
        ),
        CheckConstraint(sql_in_list("kind", CHANGE_KINDS), name="ck_obligation_change_kind"),
        CheckConstraint(
            sql_in_list("status_after", STATUSES), name="ck_obligation_change_status_after"
        ),
        CheckConstraint(sql_in_list("reason", CHANGE_REASONS), name="ck_obligation_change_reason"),
        CheckConstraint(
            "kind <> 'rescheduled' OR (previous_due_at IS NOT NULL AND new_due_at IS NOT NULL)",
            name="ck_obligation_change_rescheduled_dates",
        ),
        Index("ix_obligation_change_obligation", "tenant_id", "obligation_id", "occurred_at"),
        {
            "comment": (
                "Append-only change log of obligations (ADR-015): one row per created, "
                "rescheduled or closed event, written with its outbox row. Row-level "
                "security by tenant_id."
            )
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, nullable=False, comment="The id of the event that made it"
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    obligation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    rule_version_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    previous_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    new_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status_after: Mapped[str] = mapped_column(String(24), nullable=False)
    reason: Mapped[str] = mapped_column(String(24), nullable=False, server_default="")
    caused_by_rule_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    actor: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    correlation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
