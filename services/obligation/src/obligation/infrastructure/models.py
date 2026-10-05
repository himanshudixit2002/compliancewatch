"""SQLAlchemy rows of the obligation service; mirrored by the migrations."""

import uuid
from datetime import date, datetime
from typing import Final

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from domain_kernel.status import ClosureReason, ObligationStatus, RuleVersionStatus
from obligation.domain.comments import MAX_AUTHOR_LABEL_CHARS, MAX_COMMENT_CHARS
from obligation.domain.events import RescheduleReason
from obligation.domain.history import MAX_NOTE_CHARS, ChangeKind

STATUSES: Final[tuple[str, ...]] = tuple(status.value for status in ObligationStatus)
CLOSURE_REASONS: Final[tuple[str, ...]] = tuple(reason.value for reason in ClosureReason)
CHANGE_KINDS: Final[tuple[str, ...]] = tuple(kind.value for kind in ChangeKind)
CHANGE_REASONS: Final[tuple[str, ...]] = (
    "",
    *(reason.value for reason in RescheduleReason),
    *CLOSURE_REASONS,
)
RULE_VERSION_STATUSES: Final[tuple[str, ...]] = tuple(status.value for status in RuleVersionStatus)
TENANT_SETTING: Final[str] = "app.tenant_id"
"""The session setting the row-level security policy reads; set per transaction."""
CHANGE_ASSIGNEES: Final[str] = (
    "CASE kind WHEN 'assigned' THEN new_assignee_id IS NOT NULL "
    "WHEN 'unassigned' THEN previous_assignee_id IS NOT NULL AND new_assignee_id IS NULL "
    "ELSE previous_assignee_id IS NULL AND new_assignee_id IS NULL END"
)
"""An assignment names its assignees, and no other change names any (migration 0005)."""
CHANGE_COMMENT: Final[str] = (
    "Append-only change log of obligations (ADR-015): one row per change, written with the "
    "outbox row of the event that records it, if any. Row-level security by tenant_id."
)
CHANGE_ID_COMMENT: Final[str] = (
    "The id of the event that made it, or its own for a change no event records"
)


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
        CheckConstraint(
            "profile_version IS NULL OR profile_version >= 1",
            name="ck_obligation_profile_version",
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
    profile_version: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="The profile version of the decision that made it"
    )
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)


class ObligationChangeRow(Base):
    """One change of one obligation, keyed by the id of the event that made it, or by an id of
    its own for a change no event records (started, assigned, unassigned). Append-only: a trigger
    refuses UPDATE, and DELETE outside a tenant's erasure (migration 0002)."""

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
        CheckConstraint(CHANGE_ASSIGNEES, name="ck_obligation_change_assignees"),
        CheckConstraint(f"char_length(note) <= {MAX_NOTE_CHARS}", name="ck_obligation_change_note"),
        Index("ix_obligation_change_obligation", "tenant_id", "obligation_id", "occurred_at"),
        {"comment": CHANGE_COMMENT},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, comment=CHANGE_ID_COMMENT)
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
    previous_assignee_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    new_assignee_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    note: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="", comment="What the person said: a waiver's reason"
    )


class ObligationCommentRow(Base):
    """One comment on one obligation (migration 0005). Append-only: a trigger refuses UPDATE,
    and DELETE outside a tenant's erasure."""

    __tablename__ = "obligation_comment"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_obligation_comment"),
        ForeignKeyConstraint(
            ["obligation_id"],
            ["obligation.id"],
            name="fk_obligation_comment_obligation_id_obligation",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            f"char_length(body) BETWEEN 1 AND {MAX_COMMENT_CHARS}",
            name="ck_obligation_comment_body",
        ),
        Index("ix_obligation_comment_obligation", "tenant_id", "obligation_id", "created_at"),
        {
            "comment": (
                "Comments on obligations, each with its author; append-only. Row-level security "
                "by tenant_id."
            )
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    obligation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, nullable=True, comment="The user who wrote it; null when no token named the caller"
    )
    author_label: Mapped[str] = mapped_column(
        String(MAX_AUTHOR_LABEL_CHARS),
        nullable=False,
        comment="The author as the audit log labels them: roles, service:<client> or system:<name>",
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ObligationReminderRow(Base):
    """One reminder sent for one obligation, due date and threshold, keyed by the id of its
    obligation.due_soon event (migration 0003)."""

    __tablename__ = "obligation_reminder"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_obligation_reminder"),
        ForeignKeyConstraint(
            ["obligation_id"],
            ["obligation.id"],
            name="fk_obligation_reminder_obligation_id_obligation",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "obligation_id", "due_at", "threshold_days", name="uq_obligation_reminder_threshold"
        ),
        UniqueConstraint("obligation_id", "reminder_index", name="uq_obligation_reminder_index"),
        CheckConstraint("threshold_days >= 0", name="ck_obligation_reminder_threshold_days"),
        CheckConstraint("reminder_index >= 1", name="ck_obligation_reminder_reminder_index"),
        {
            "comment": (
                "Reminders sent for open obligations, one per obligation, due date and "
                "threshold, written with the obligation.due_soon outbox row. Row-level "
                "security by tenant_id."
            )
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, nullable=False, comment="The id of the obligation.due_soon event"
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    obligation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    threshold_days: Mapped[int] = mapped_column(Integer, nullable=False)
    reminder_index: Mapped[int] = mapped_column(Integer, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ObligationTenantRow(Base):
    """A tenant that has obligations: the directory the reminder sweep reads across tenants
    (migration 0003)."""

    __tablename__ = "obligation_tenant"
    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", name="pk_obligation_tenant"),
        {
            "comment": (
                "Tenants that have obligations, for sweeps that run one tenant unit at a time. "
                "Row-level security: any session may read the ids, a write needs the tenant "
                "setting of its own row."
            )
        },
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RuleVersionRefRow(Base):
    """What the service caches of one rule version: rule-level, not tenant data, so it has no
    tenant_id and no row-level security (migration 0004, exempt in
    infra/scripts/migration_lint.toml). ``citations`` holds the verified citations as JSON."""

    __tablename__ = "rule_version_ref"
    __table_args__ = (
        PrimaryKeyConstraint("rule_version_id", name="pk_rule_version_ref"),
        CheckConstraint(
            sql_in_list("status", RULE_VERSION_STATUSES), name="ck_rule_version_ref_status"
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_rule_version_ref_effective",
        ),
        {
            "comment": (
                "The rule versions obligations come from, as the rulebook last described them: "
                "status, dates, approvers and verified citations. Rule-level, the same for every "
                "tenant."
            )
        },
    )

    rule_version_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    rule_key: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    seed_status: Mapped[str] = mapped_column(String(24), nullable=False)
    approved_by: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    citations: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ObligationDecisionRow(Base):
    """The latest applicability decision the service acted on for one business and rule
    version (migration 0004); the rolling window reads the ones that apply."""

    __tablename__ = "obligation_decision"
    __table_args__ = (
        PrimaryKeyConstraint("business_id", "rule_version_id", name="pk_obligation_decision"),
        Index("ix_obligation_decision_tenant_applies", "tenant_id", "applies"),
        {
            "comment": (
                "The latest applies or not_applicable decision per business and rule version, "
                "which the daily rolling window reads. Row-level security by tenant_id."
            )
        },
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    rule_version_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    decision_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    applies: Mapped[bool] = mapped_column(Boolean, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    profile_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
