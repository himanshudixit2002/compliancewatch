"""SQLAlchemy rows of the obligation service; mirrored by the migrations."""

import uuid
from datetime import date, datetime
from typing import Final

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Index,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from domain_kernel.status import ClosureReason, ObligationStatus

STATUSES: Final[tuple[str, ...]] = tuple(status.value for status in ObligationStatus)
CLOSURE_REASONS: Final[tuple[str, ...]] = tuple(reason.value for reason in ClosureReason)
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
