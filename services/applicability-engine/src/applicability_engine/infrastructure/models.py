"""SQLAlchemy rows of the applicability-engine service; mirrored by the migrations."""

import uuid
from datetime import datetime
from typing import Any, Final

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Double,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from applicability_engine.domain.model import Trigger
from domain_kernel.predicates import Applicability

RESULTS: Final[tuple[str, ...]] = tuple(result.value for result in Applicability)
TRIGGERS: Final[tuple[str, ...]] = tuple(trigger.value for trigger in Trigger)
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
    evaluated: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, comment="Per-predicate outcomes, confidences and reasons"
    )
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
