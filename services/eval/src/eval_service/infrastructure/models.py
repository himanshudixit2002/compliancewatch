"""SQLAlchemy rows of the eval service; mirrored by the migrations.

Eval runs are platform data shared by every tenant (the ``eval`` schema is in the global group of
infra/scripts/migration_lint.toml), so the tables carry no tenant_id and no row-level security.
"""

import uuid
from datetime import datetime
from typing import Final

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from eval_service.domain.model import Profile, Suite

SUITES: Final[tuple[str, ...]] = tuple(suite.value for suite in Suite)
PROFILES: Final[tuple[str, ...]] = tuple(profile.value for profile in Profile)


def sql_in_list(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"


class Base(DeclarativeBase):
    pass


class EvalRunRow(Base):
    __tablename__ = "eval_run"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_eval_run"),
        ForeignKeyConstraint(
            ["previous_run_id"], ["eval_run.id"], name="fk_eval_run_previous_run_id_eval_run"
        ),
        CheckConstraint(sql_in_list("suite", SUITES), name="ck_eval_run_suite"),
        CheckConstraint(sql_in_list("profile", PROFILES), name="ck_eval_run_profile"),
        CheckConstraint("completed_at >= started_at", name="ck_eval_run_completed"),
        Index("ix_eval_run_suite_profile_started", "suite", "profile", "started_at"),
        Index("ix_eval_run_started", "started_at"),
        {"comment": "One run of an eval harness suite under a profile; platform data, no tenant."},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    suite: Mapped[str] = mapped_column(String(20))
    profile: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    previous_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    gates: Mapped[list["EvalGateRow"]] = relationship(
        order_by="EvalGateRow.position", lazy="selectin"
    )


class EvalGateRow(Base):
    __tablename__ = "eval_gate_result"
    __table_args__ = (
        PrimaryKeyConstraint("run_id", "position", name="pk_eval_gate_result"),
        ForeignKeyConstraint(
            ["run_id"], ["eval_run.id"], name="fk_eval_gate_result_run_id_eval_run"
        ),
        UniqueConstraint("run_id", "name", name="uq_eval_gate_result_name"),
        CheckConstraint("position >= 0", name="ck_eval_gate_result_position"),
        {"comment": "The gates of one eval run, in the harness's order, with the previous value."},
    )

    run_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    position: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(200))
    metric: Mapped[str] = mapped_column(String(100))
    threshold: Mapped[float] = mapped_column(Float)
    value: Mapped[float | None] = mapped_column(Float)
    passed: Mapped[bool] = mapped_column(Boolean)
    previous_value: Mapped[float | None] = mapped_column(Float)
