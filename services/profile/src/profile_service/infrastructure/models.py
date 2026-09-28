"""SQLAlchemy rows of the profile service; mirrored by the migrations. Every table carries
tenant_id and a row-level security policy."""

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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

LEVELS: Final[tuple[str, ...]] = ("entity", "registration", "location")
STATES: Final[tuple[str, ...]] = ("known", "unsure", "not_applicable")
SOURCES: Final[tuple[str, ...]] = ("gstin_lookup", "user_input", "derived")
REASONS: Final[tuple[str, ...]] = ("not_applicable", "confirm_financial_year")
TENANT_SETTING: Final[str] = "app.tenant_id"
TENANT_TABLES: Final[tuple[str, ...]] = (
    "profile_node",
    "profile_attribute",
    "profile_version",
    "review_task",
)


def sql_in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(f"'{value}'" for value in values)})"


class Base(DeclarativeBase):
    pass


class ProfileNodeRow(Base):
    __tablename__ = "profile_node"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_profile_node"),
        UniqueConstraint("tenant_id", "level", "key", name="uq_profile_node_key"),
        ForeignKeyConstraint(
            ["parent_id"], ["profile_node.id"], name="fk_profile_node_parent_id_profile_node"
        ),
        CheckConstraint(sql_in_list("level", LEVELS), name="ck_profile_node_level"),
        CheckConstraint("(level = 'entity') = (parent_id IS NULL)", name="ck_profile_node_parent"),
        Index("ix_profile_node_parent", "parent_id"),
        {
            "comment": (
                "Hierarchy nodes: entity (PAN), registration (GSTIN), location. RLS by tenant_id."
            )
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProfileAttributeRow(Base):
    __tablename__ = "profile_attribute"
    __table_args__ = (
        PrimaryKeyConstraint("node_id", "key", "fy_label", name="pk_profile_attribute"),
        ForeignKeyConstraint(
            ["node_id"], ["profile_node.id"], name="fk_profile_attribute_node_id_profile_node"
        ),
        CheckConstraint(sql_in_list("state", STATES), name="ck_profile_attribute_state"),
        CheckConstraint(sql_in_list("source", SOURCES), name="ck_profile_attribute_source"),
        CheckConstraint(
            "(state = 'known') = (value IS NOT NULL)", name="ck_profile_attribute_value"
        ),
        {
            "comment": (
                "One value per node, attribute and financial year ('' when the attribute is "
                "not per year). value is the ontology's canonical form as JSON."
            )
        },
    )

    node_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    fy_label: Mapped[str] = mapped_column(String(7), nullable=False, server_default="")
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    # none_as_null: a Python None is SQL NULL, not the JSON null the check would reject
    value: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProfileVersionRow(Base):
    __tablename__ = "profile_version"
    __table_args__ = (
        PrimaryKeyConstraint("node_id", "version", name="pk_profile_version"),
        ForeignKeyConstraint(
            ["node_id"], ["profile_node.id"], name="fk_profile_version_node_id_profile_node"
        ),
        {"comment": "History: the attributes of a node after each change, for replay."},
    )

    node_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    changed_attributes: Mapped[list[object]] = mapped_column(JSONB, nullable=False)
    attributes: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReviewTaskRow(Base):
    __tablename__ = "review_task"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_review_task"),
        ForeignKeyConstraint(
            ["node_id"], ["profile_node.id"], name="fk_review_task_node_id_profile_node"
        ),
        CheckConstraint(sql_in_list("reason", REASONS), name="ck_review_task_reason"),
        Index("ix_review_task_open", "tenant_id", "open"),
        {
            "comment": (
                "Questions for a person: not-applicable answers and financial-year confirmations."
            )
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    node_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    attribute_key: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    fy_label: Mapped[str] = mapped_column(String(7), nullable=False, server_default="")
    open: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
