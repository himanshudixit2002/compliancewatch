"""SQLAlchemy rows of the applicability-engine service; mirrored by the migrations."""

import uuid
from datetime import datetime
from typing import Any, Final

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Double,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from applicability_engine.domain.model import TRIGGER_REF_MAX_CHARS, Trigger
from applicability_engine.domain.review import Resolution, ReviewReason, ReviewStatus
from domain_kernel.ontology import AttributeLevel
from domain_kernel.predicates import Applicability

RESULTS: Final[tuple[str, ...]] = tuple(result.value for result in Applicability)
TRIGGERS: Final[tuple[str, ...]] = tuple(trigger.value for trigger in Trigger)
LEVELS: Final[tuple[str, ...]] = tuple(level.value for level in AttributeLevel)
REASONS: Final[tuple[str, ...]] = tuple(reason.value for reason in ReviewReason)
STATUSES: Final[tuple[str, ...]] = tuple(status.value for status in ReviewStatus)
RESOLUTIONS: Final[tuple[str, ...]] = tuple(resolution.value for resolution in Resolution)
TENANT_SETTING: Final[str] = "app.tenant_id"
"""The session setting the row-level security policy reads; set per transaction."""


def sql_in_list(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"


class Base(DeclarativeBase):
    pass


class DecisionRow(Base):
    """One decision. Append-only: a trigger refuses UPDATE, and DELETE outside a tenant's
    erasure (migration 0001); recomputing adds a row."""

    __tablename__ = "applicability_decision"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_applicability_decision"),
        CheckConstraint(sql_in_list("result", RESULTS), name="ck_applicability_decision_result"),
        CheckConstraint(sql_in_list("trigger", TRIGGERS), name="ck_applicability_decision_trigger"),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_applicability_decision_confidence"
        ),
        CheckConstraint("profile_version >= 1", name="ck_applicability_decision_profile_version"),
        Index(
            "ix_applicability_decision_business",
            "tenant_id",
            "business_id",
            "decided_at",
            "id",
        ),
        Index(
            "ix_applicability_decision_rule_version",
            "tenant_id",
            "business_id",
            "rule_version_id",
            "decided_at",
        ),
        UniqueConstraint(
            "trigger_ref",
            "business_id",
            "rule_version_id",
            name="uq_applicability_decision_trigger_ref",
        ),
        {
            "comment": (
                "Applicability decisions, append-only: one row per evaluation of a rule version "
                "against a business profile version, written with its outbox row. Row-level "
                "security by tenant_id."
            )
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    rule_version_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float] = mapped_column(Double, nullable=False)
    profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    as_of_fy: Mapped[str | None] = mapped_column(String(7), nullable=True)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)
    trigger_ref: Mapped[str | None] = mapped_column(
        String(TRIGGER_REF_MAX_CHARS),
        nullable=True,
        comment=(
            "The event or review item that caused the decision (profile.updated:<event id>, "
            "review:<item id>); null for a manual evaluation"
        ),
    )
    evaluated: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, comment="Per-predicate outcomes, confidences and reasons"
    )
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BusinessDirectoryRow(Base):
    """One hierarchy node the engine heard of; a routing directory: any session reads the ids,
    a write passes the tenant policy (migration 0002)."""

    __tablename__ = "business_directory"
    __table_args__ = (
        PrimaryKeyConstraint("business_id", name="pk_business_directory"),
        CheckConstraint(sql_in_list("level", LEVELS), name="ck_business_directory_level"),
        CheckConstraint(
            "(level = 'entity') = (parent_id IS NULL)", name="ck_business_directory_parent"
        ),
        Index("ix_business_directory_level", "level", "tenant_id", "business_id"),
        {
            "comment": (
                "Every business node the engine heard of, by tenant and level, for fan-outs that "
                "read the ids across tenants and then work one tenant unit at a time. Row-level "
                "security: any session may read, a write needs the tenant setting of its row."
            )
        },
    )

    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, nullable=False, comment="The legal entity at the top of the node's lineage"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReviewItemRow(Base):
    """A decision waiting for a reviewer, or settled; at most one open per business and rule
    version (migration 0002)."""

    __tablename__ = "review_item"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_review_item"),
        ForeignKeyConstraint(
            ["decision_id"],
            ["applicability_decision.id"],
            name="fk_review_item_decision_id_applicability_decision",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["resolution_decision_id"],
            ["applicability_decision.id"],
            name="fk_review_item_resolution_decision_id_applicability_decision",
            ondelete="CASCADE",
        ),
        CheckConstraint(sql_in_list("reason", REASONS), name="ck_review_item_reason"),
        CheckConstraint(sql_in_list("status", STATUSES), name="ck_review_item_status"),
        CheckConstraint(
            f"resolution IS NULL OR {sql_in_list('resolution', RESOLUTIONS)}",
            name="ck_review_item_resolution",
        ),
        CheckConstraint(
            "(status = 'resolved') = (resolution IS NOT NULL AND resolved_at IS NOT NULL)",
            name="ck_review_item_resolved",
        ),
        CheckConstraint(
            "(resolution_decision_id IS NOT NULL) = "
            "(resolution IS NOT NULL AND resolution <> 'dismiss')",
            name="ck_review_item_resolution_decision",
        ),
        Index(
            "uq_review_item_open",
            "business_id",
            "rule_version_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
        Index("ix_review_item_queue", "tenant_id", "status", "opened_at", "id"),
        Index("ix_review_item_decision_id", "decision_id"),
        {
            "comment": (
                "Decisions a person has to settle (a free-text predicate, a low confidence), at "
                "most one open per business and rule version. Row-level security by tenant_id."
            )
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    rule_version_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    decision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, nullable=False, comment="The decision under review: the pair's latest while open"
    )
    reason: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolution: Mapped[str | None] = mapped_column(String(16), nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, nullable=True, comment="The reviewer; null when a later decision settled the item"
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    resolution_decision_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, nullable=True, comment="The decision a resolution to a result appended"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
