"""SQLAlchemy models for the rulebook knowledge tables.

Table names are unqualified: the connection's search_path (CW_DB_SCHEMA, set by ``make migrate``
and ``make run``) puts them in the ``rulebook`` schema. The migration under
``migrations/versions`` is written by hand and mirrors these models constraint for constraint;
the integration test compares the two.

``clause_id`` and ``from_rule_version_id`` are plain uuid columns for now. The ``clause`` and
``rule_version`` tables do not exist yet; the migration that creates them adds the foreign keys.
The vocabulary in the CHECK constraints is the kernel's (``domain_kernel.knowledge``), and so are
the three rules on ``rule_relation``: ``supersedes`` and ``extends_deadline`` target a rule
version, ``to_entity_id`` is set exactly when the target is an entity, and a rule version never
relates to itself. The kernel checks the same rules for every writer.
"""

from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
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
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from domain_kernel.knowledge import RULE_VERSION_KIND, RULE_VERSION_ONLY, EntityType, RelationKind

ENTITY_TYPES: Final[tuple[str, ...]] = tuple(kind.value for kind in EntityType)
"""The ten entity types a canonical entity can have: ``EntityType`` in the kernel."""

RELATION_KINDS: Final[tuple[str, ...]] = tuple(kind.value for kind in RelationKind)
"""The five typed relations between a rule version and its target: ``RelationKind``."""

RULE_VERSION_TARGET: Final[str] = RULE_VERSION_KIND
"""``to_kind`` when the target is a rule version rather than an entity."""

TARGET_KINDS: Final[tuple[str, ...]] = (RULE_VERSION_TARGET, *ENTITY_TYPES)
"""What a relation can point at: a rule version or an entity of one of the ten types."""

RULE_VERSION_ONLY_RELATIONS: Final[tuple[str, ...]] = tuple(
    kind.value for kind in RelationKind if kind in RULE_VERSION_ONLY
)
"""Relations whose target must be a rule version, in ``RelationKind`` order."""


def sql_quoted(values: tuple[str, ...]) -> str:
    """``'a', 'b'`` for a CHECK constraint over a fixed vocabulary."""
    return ", ".join(f"'{value}'" for value in values)


def sql_in_list(column: str, values: tuple[str, ...]) -> str:
    """``column IN ('a', 'b')`` for a CHECK constraint over a fixed vocabulary."""
    return f"{column} IN ({sql_quoted(values)})"


class Base(DeclarativeBase):
    """Declarative base for every rulebook table. ``migrations/env.py`` targets its metadata."""


class CanonicalEntityRow(Base):
    """One aligned knowledge entity: the canonical name mentions are resolved to, plus aliases."""

    __tablename__ = "canonical_entity"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_canonical_entity"),
        CheckConstraint(sql_in_list("type", ENTITY_TYPES), name="ck_canonical_entity_type"),
        UniqueConstraint("type", "canonical_name", name="uq_canonical_entity_type_canonical_name"),
        Index("ix_canonical_entity_aliases", "aliases", postgresql_using="gin"),
        {
            "comment": (
                "Aligned knowledge entities (one row per type and canonical name); "
                "aliases hold the surface forms seen in clauses."
            )
        },
    )

    id: Mapped[UUID] = mapped_column(Uuid)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    aliases: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ClauseEntityRow(Base):
    """A mention of a canonical entity inside a clause: the text-to-fact half of the index."""

    __tablename__ = "clause_entity"
    __table_args__ = (
        PrimaryKeyConstraint("clause_id", "entity_id", "span_start", name="pk_clause_entity"),
        CheckConstraint("span_start >= 0", name="ck_clause_entity_span_start"),
        CheckConstraint("span_end > span_start", name="ck_clause_entity_span_end"),
        Index("ix_clause_entity_entity", "entity_id"),
        {
            "comment": (
                "Entity mentions per clause with character spans. clause_id has no foreign key "
                "yet: the clause table arrives with a later migration, which adds it."
            )
        },
    )

    clause_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    entity_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "canonical_entity.id",
            name="fk_clause_entity_entity_id_canonical_entity",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    mention_text: Mapped[str] = mapped_column(Text, nullable=False)
    span_start: Mapped[int] = mapped_column(Integer, nullable=False)
    span_end: Mapped[int] = mapped_column(Integer, nullable=False)


class RuleRelationRow(Base):
    """A typed relation from a rule version to a rule version or an entity, plus its evidence."""

    __tablename__ = "rule_relation"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_rule_relation"),
        CheckConstraint(sql_in_list("relation", RELATION_KINDS), name="ck_rule_relation_relation"),
        CheckConstraint(sql_in_list("to_kind", TARGET_KINDS), name="ck_rule_relation_to_kind"),
        CheckConstraint(
            f"relation NOT IN ({sql_quoted(RULE_VERSION_ONLY_RELATIONS)})"
            f" OR to_kind = '{RULE_VERSION_TARGET}'",
            name="ck_rule_relation_pairing",
        ),
        CheckConstraint(
            f"(to_kind = '{RULE_VERSION_TARGET}') = (to_entity_id IS NULL)",
            name="ck_rule_relation_target_entity",
        ),
        CheckConstraint(
            f"NOT (to_kind = '{RULE_VERSION_TARGET}' AND to_ref = from_rule_version_id::text)",
            name="ck_rule_relation_not_self",
        ),
        UniqueConstraint(
            "from_rule_version_id",
            "relation",
            "to_kind",
            "to_ref",
            "clause_id",
            name="uq_rule_relation_edge",
        ),
        Index("ix_rule_relation_target", "relation", "to_ref"),
        Index("ix_rule_relation_source", "from_rule_version_id"),
        {
            "comment": (
                "Typed relations between rule versions and entities; clause_id is the evidence. "
                "from_rule_version_id and clause_id have no foreign keys yet: the rule_version "
                "and clause tables arrive with a later migration, which adds them."
            )
        },
    )

    id: Mapped[UUID] = mapped_column(Uuid)
    from_rule_version_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    relation: Mapped[str] = mapped_column(String(24), nullable=False)
    to_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    to_ref: Mapped[str] = mapped_column(Text, nullable=False)
    to_entity_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "canonical_entity.id",
            name="fk_rule_relation_to_entity_id_canonical_entity",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    clause_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
