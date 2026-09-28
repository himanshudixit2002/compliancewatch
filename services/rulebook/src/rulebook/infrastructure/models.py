"""SQLAlchemy models for the rulebook tables: regulator documents and clauses, rules and rule
versions, citations, the knowledge tables (canonical entities, mentions, relations) and the clause
search index (a full-text column on ``clause`` and the ``clause_embedding`` vectors).

Table names are unqualified: the connection's search_path (CW_DB_SCHEMA, set by ``make migrate``
and ``make run``) puts them in the ``rulebook`` schema. The migrations under
``migrations/versions`` are written by hand and mirror these models constraint for constraint;
the integration test compares the two. Triggers are not modelled: migration 0004 makes
``document`` and ``clause`` append-only and fixes a citation's identity, migration 0006 makes
``clause_embedding`` refuse updates, and migration 0007 makes ``rule_version_decision``
append-only and guards ``rule_version`` (status moves, frozen content, publish preconditions).
The ``outbox_event`` table of the same migration belongs to py-common's metadata, not this one.

The vocabulary in the CHECK constraints is the kernel's (``domain_kernel.knowledge``), and so are
the rules on ``rule_relation``: the relations in ``RULE_VERSION_ONLY`` target a rule version,
``to_entity_id`` is set exactly when the target is an entity, ``to_rule_version_id`` exactly
when it is a rule version, and a rule version never relates to itself. The kernel checks the
same rules for every writer.
"""

from collections.abc import Callable, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final
from uuid import UUID

from sqlalchemy import (
    BindParameter,
    Boolean,
    CheckConstraint,
    ColumnElement,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    cast,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

from domain_kernel.documents import PARSER_VERSION_PATTERN, DocumentType
from domain_kernel.knowledge import RULE_VERSION_KIND, RULE_VERSION_ONLY, EntityType, RelationKind
from domain_kernel.status import RuleVersionStatus
from domain_kernel.vectors import EMBEDDING_DIMS
from rulebook.domain.alignment import ReviewReason
from rulebook.domain.documents import CLAUSE_REF_PATTERN
from rulebook.domain.publication import DecisionAction
from rulebook.domain.relations import CandidateRejectReason, CandidateStatus
from rulebook.domain.review import EntityRejectReason, Resolution, ReviewStatus

ENTITY_TYPES: Final[tuple[str, ...]] = tuple(kind.value for kind in EntityType)
"""The ten entity types a canonical entity can have: ``EntityType`` in the kernel."""

RELATION_KINDS: Final[tuple[str, ...]] = tuple(kind.value for kind in RelationKind)
"""The seven typed relations between a rule version and its target: ``RelationKind``."""

RULE_VERSION_TARGET: Final[str] = RULE_VERSION_KIND
"""``to_kind`` when the target is a rule version rather than an entity."""

TARGET_KINDS: Final[tuple[str, ...]] = (RULE_VERSION_TARGET, *ENTITY_TYPES)
"""What a relation can point at: a rule version or an entity of one of the ten types."""

DOCUMENT_TYPES: Final[tuple[str, ...]] = tuple(kind.value for kind in DocumentType)
"""What a regulator document can be: ``DocumentType`` in the kernel."""

MENTION_METHODS: Final[tuple[str, ...]] = ("grammar", "model", "analyst")
"""Who found a mention or proposed a relation: the grammar, a model, or an analyst."""

EXTRACTION_STAGES: Final[tuple[str, ...]] = ("mentions", "relations")
EXTRACTION_OUTCOMES: Final[tuple[str, ...]] = (
    "ok",
    "needs_review",
    "no_targets",
    "unparseable",
    "failed",
)
REVIEW_REASONS: Final[tuple[str, ...]] = tuple(reason.value for reason in ReviewReason)
REVIEW_STATUSES: Final[tuple[str, ...]] = tuple(status.value for status in ReviewStatus)
RESOLUTIONS: Final[tuple[str, ...]] = tuple(resolution.value for resolution in Resolution)
ENTITY_REJECT_REASONS: Final[tuple[str, ...]] = tuple(r.value for r in EntityRejectReason)
CANDIDATE_STATUSES: Final[tuple[str, ...]] = tuple(status.value for status in CandidateStatus)
CANDIDATE_REJECT_REASONS: Final[tuple[str, ...]] = tuple(r.value for r in CandidateRejectReason)

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


SEARCH_VECTOR = "to_tsvector('english'::regconfig, text)"
"""The generated full-text column of ``clause``, written as Postgres reflects it. English
stemming; a token outside the English dictionary, such as a Devanagari word, stays as written."""


class Vector(UserDefinedType[tuple[float, ...]]):
    """pgvector's ``vector(n)`` without the pgvector package: a value is bound as the text form
    ``[x,y,...]`` cast to the column type and read back from the same text. The ``vector``
    type lives in ``public``, which every service keeps on its search_path."""

    cache_ok = True

    def __init__(self, dims: int = EMBEDDING_DIMS) -> None:
        self.dims = dims

    def get_col_spec(self, **kw: Any) -> str:
        return f"vector({self.dims})"

    def bind_processor(self, dialect: Dialect) -> Callable[[Sequence[float] | None], str | None]:
        def process(value: Sequence[float] | None) -> str | None:
            if value is None:
                return None
            return "[" + ",".join(repr(float(component)) for component in value) + "]"

        return process

    def bind_expression(
        self, bindvalue: BindParameter[tuple[float, ...]]
    ) -> ColumnElement[tuple[float, ...]]:
        return cast(bindvalue, self)

    def result_processor(
        self, dialect: Dialect, coltype: object
    ) -> Callable[[object], tuple[float, ...] | None]:
        def process(value: object) -> tuple[float, ...] | None:
            if value is None:
                return None
            return tuple(float(component) for component in str(value).strip("[]").split(","))

        return process


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
        ARRAY(Text),
        nullable=False,
        server_default=text("'{}'::text[]"),
        comment=(
            "Alternative names of the same type, each already normalised with normalise_name, "
            "that resolve to this entity"
        ),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DocumentRow(Base):
    """A regulator document: one row per distinct file, keyed by its digest."""

    __tablename__ = "document"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_document"),
        UniqueConstraint("sha256", name="uq_document_sha256"),
        CheckConstraint(sql_in_list("doc_type", DOCUMENT_TYPES), name="ck_document_doc_type"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_document_sha256"),
        CheckConstraint(
            "replace(id::text, '-', '') = left(sha256, 32)", name="ck_document_id_from_sha256"
        ),
        CheckConstraint(
            f"parser_version ~ '{PARSER_VERSION_PATTERN}'", name="ck_document_parser_version"
        ),
        Index("ix_document_source_published", "source_id", "published_at"),
        {
            "comment": (
                "Regulator documents, one row per distinct file; id is the first 32 hex digits "
                "of sha256. Append-only: a corrected document is a new row, and a re-parse that "
                "gives different clauses is rejected, not applied."
            )
        },
    )

    id: Mapped[UUID] = mapped_column(Uuid)
    source_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    regulator: Mapped[str] = mapped_column(String(40), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(16), nullable=False)
    external_ref: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    language: Mapped[str] = mapped_column(String(8), nullable=False)
    media_type: Mapped[str] = mapped_column(String(80), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(40), nullable=False)
    published_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ClauseRow(Base):
    """One clause of a document, under the id every service derives for it."""

    __tablename__ = "clause"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_clause"),
        ForeignKeyConstraint(
            ["document_id"],
            ["document.id"],
            name="fk_clause_document_id_document",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("document_id", "clause_ref", name="uq_clause_document_id_clause_ref"),
        UniqueConstraint("document_id", "ordinal", name="uq_clause_document_id_ordinal"),
        CheckConstraint(f"clause_ref ~ '{CLAUSE_REF_PATTERN}'", name="ck_clause_clause_ref"),
        CheckConstraint("ordinal >= 1", name="ck_clause_ordinal"),
        CheckConstraint("page IS NULL OR page >= 1", name="ck_clause_page"),
        CheckConstraint("length(text) > 0", name="ck_clause_text"),
        Index("ix_clause_search_vector", "search_vector", postgresql_using="gin"),
        {
            "comment": (
                "Clauses of a document in order. id is clause_id_for(document id, clause_ref) "
                "from the kernel, which clause_entity, rule_relation, citation and the vector "
                "index share. Mention spans are code-point offsets into text. Append-only."
            )
        },
    )

    id: Mapped[UUID] = mapped_column(Uuid)
    document_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    clause_ref: Mapped[str] = mapped_column(String(40), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed(SEARCH_VECTOR, persisted=True), deferred=True
    )


class ClauseEmbeddingRow(Base):
    """One clause's embedding from one model: the vector half of the clause search index."""

    __tablename__ = "clause_embedding"
    __table_args__ = (
        PrimaryKeyConstraint("clause_id", "model", name="pk_clause_embedding"),
        ForeignKeyConstraint(
            ["clause_id"],
            ["clause.id"],
            name="fk_clause_embedding_clause_id_clause",
            ondelete="RESTRICT",
        ),
        CheckConstraint("length(model) > 0", name="ck_clause_embedding_model"),
        Index(
            "ix_clause_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        {
            "comment": (
                "Clause embeddings, one per clause and model; vectors from different models "
                "do not compare. Rows are never updated: a new model means a new row, and a "
                "retired model's rows may be deleted."
            )
        },
    )

    clause_id: Mapped[UUID] = mapped_column(Uuid)
    model: Mapped[str] = mapped_column(String(120))
    embedding: Mapped[tuple[float, ...]] = mapped_column(Vector(EMBEDDING_DIMS), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ClauseEntityRow(Base):
    """A mention of a canonical entity inside a clause: the text-to-fact half of the index."""

    __tablename__ = "clause_entity"
    __table_args__ = (
        PrimaryKeyConstraint("clause_id", "entity_id", "span_start", name="pk_clause_entity"),
        ForeignKeyConstraint(
            ["clause_id"],
            ["clause.id"],
            name="fk_clause_entity_clause_id_clause",
            ondelete="RESTRICT",
        ),
        CheckConstraint("span_start >= 0", name="ck_clause_entity_span_start"),
        CheckConstraint("span_end > span_start", name="ck_clause_entity_span_end"),
        CheckConstraint(sql_in_list("method", MENTION_METHODS), name="ck_clause_entity_method"),
        Index("ix_clause_entity_entity", "entity_id"),
        {
            "comment": (
                "Entity mentions per clause with half-open code-point spans into clause.text: "
                "the text-to-fact half of the index. method says who found the mention."
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
    method: Mapped[str] = mapped_column(String(16), nullable=False, server_default="grammar")
    extractor: Mapped[str] = mapped_column(String(60), nullable=False, server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


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
        CheckConstraint(
            f"((to_kind = '{RULE_VERSION_TARGET}') = (to_rule_version_id IS NOT NULL))"
            " AND (to_rule_version_id IS NULL OR to_ref = to_rule_version_id::text)",
            name="ck_rule_relation_target_version",
        ),
        ForeignKeyConstraint(
            ["from_rule_version_id"],
            ["rule_version.id"],
            name="fk_rule_relation_from_rule_version_id_rule_version",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["to_rule_version_id"],
            ["rule_version.id"],
            name="fk_rule_relation_to_rule_version_id_rule_version",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["clause_id"],
            ["clause.id"],
            name="fk_rule_relation_clause_id_clause",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["candidate_id"],
            ["relation_candidate.id"],
            name="fk_rule_relation_candidate_id_relation_candidate",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("candidate_id", name="uq_rule_relation_candidate_id"),
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
        Index("ix_rule_relation_to_rule_version", "to_rule_version_id"),
        Index("ix_rule_relation_clause", "clause_id"),
        {
            "comment": (
                "Typed relations from a rule version to a rule version (to_rule_version_id) or "
                "an entity (to_entity_id); clause_id is the evidence, the fact-to-text half of "
                "the index."
            )
        },
    )

    id: Mapped[UUID] = mapped_column(Uuid)
    from_rule_version_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    relation: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        comment="One of " + ", ".join(RELATION_KINDS),
    )
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
    to_rule_version_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    clause_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    candidate_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


RULE_VERSION_STATUSES: Final[tuple[str, ...]] = tuple(status.value for status in RuleVersionStatus)
"""``RuleVersionStatus``: draft, in_review, approved, published, superseded, withdrawn."""
SEED_STATUSES: Final[tuple[str, ...]] = ("needs_review", "reviewed")
DECISION_ACTIONS: Final[tuple[str, ...]] = tuple(action.value for action in DecisionAction)
"""What a decision records: submitted, returned, approved, published, withdrawn, superseded."""
LEVELS: Final[tuple[str, ...]] = ("entity", "registration", "location")


class RuleRow(Base):
    """A rule: the identity that survives amendments; versions hang off it."""

    __tablename__ = "rule"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_rule"),
        UniqueConstraint("rule_key", name="uq_rule_rule_key"),
        CheckConstraint(sql_in_list("level", LEVELS), name="ck_rule_level"),
        {"comment": "One row per rule; rule_key is the stable key the seed calendar uses."},
    )

    id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    rule_key: Mapped[str] = mapped_column(String(80), nullable=False)
    regulator: Mapped[str] = mapped_column(String(40), nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RuleVersionRow(Base):
    """One version of a rule: predicates, template, recurrence, effective period and status."""

    __tablename__ = "rule_version"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_rule_version"),
        ForeignKeyConstraint(["rule_id"], ["rule.id"], name="fk_rule_version_rule_id_rule"),
        UniqueConstraint("rule_id", "version", name="uq_rule_version_rule_id_version"),
        CheckConstraint(
            sql_in_list("status", RULE_VERSION_STATUSES), name="ck_rule_version_status"
        ),
        CheckConstraint(
            sql_in_list("seed_status", SEED_STATUSES), name="ck_rule_version_seed_status"
        ),
        CheckConstraint("version >= 1", name="ck_rule_version_version"),
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_rule_version_effective",
        ),
        Index("ix_rule_version_status_effective", "status", "effective_from"),
        {
            "comment": (
                "Rule versions. specification, obligation_template and recurrence hold the "
                "kernel's mapping forms; source and todo come from the seed calendar. status "
                "moves only as the kernel's transitions allow, and a published version's content "
                "is frozen (trigger)."
            )
        },
    )

    id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    rule_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    specification: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    obligation_template: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    recurrence: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    source: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    seed_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="needs_review"
    )
    todo: Mapped[list[object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    high_impact: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=false(),
        comment="Publishing needs two different approvers (ADR-006)",
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Start of the current review round; approvals before it do not count",
    )


class RuleVersionDecisionRow(Base):
    """One step of a rule version's review and publication, by an analyst or caused by the
    version that replaced it."""

    __tablename__ = "rule_version_decision"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_rule_version_decision"),
        ForeignKeyConstraint(
            ["rule_version_id"],
            ["rule_version.id"],
            name="fk_rule_version_decision_rule_version_id_rule_version",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["caused_by_rule_version_id"],
            ["rule_version.id"],
            name="fk_rule_version_decision_caused_by_rule_version_id",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            sql_in_list("action", DECISION_ACTIONS), name="ck_rule_version_decision_action"
        ),
        CheckConstraint(
            sql_in_list("from_status", RULE_VERSION_STATUSES),
            name="ck_rule_version_decision_from_status",
        ),
        CheckConstraint(
            sql_in_list("to_status", RULE_VERSION_STATUSES),
            name="ck_rule_version_decision_to_status",
        ),
        CheckConstraint(
            "actor_id IS NOT NULL OR caused_by_rule_version_id IS NOT NULL",
            name="ck_rule_version_decision_actor",
        ),
        Index("ix_rule_version_decision_version", "rule_version_id", "decided_at"),
        {
            "comment": (
                "The review and publication audit of rule versions (ADR-006): who submitted, "
                "returned, approved, published or withdrew a version, or which version "
                "superseded or withdrew it. Append-only (trigger)."
            )
        },
    )

    id: Mapped[UUID] = mapped_column(Uuid)
    rule_version_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    from_status: Mapped[str] = mapped_column(String(16), nullable=False)
    to_status: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    caused_by_rule_version_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CitationRow(Base):
    """A rule version's citation of a clause, with the quote and its one-way verification."""

    __tablename__ = "citation"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_citation"),
        ForeignKeyConstraint(
            ["rule_version_id"],
            ["rule_version.id"],
            name="fk_citation_rule_version_id_rule_version",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["clause_id"], ["clause.id"], name="fk_citation_clause_id_clause", ondelete="RESTRICT"
        ),
        CheckConstraint("length(quote) BETWEEN 1 AND 400", name="ck_citation_quote"),
        CheckConstraint(
            "match_score IS NULL OR match_score BETWEEN 0 AND 1", name="ck_citation_match_score"
        ),
        CheckConstraint(
            "verified = (verified_at IS NOT NULL)"
            " AND (NOT verified OR (match_score IS NOT NULL AND match_score >= 0.85))",
            name="ck_citation_verified",
        ),
        Index("ix_citation_rule_version", "rule_version_id"),
        Index("ix_citation_clause", "clause_id"),
        {
            "comment": (
                "Citations from rule versions to clauses (ADR-006). Every citation of a version "
                "must be verified before the version is published. Identity columns are fixed; "
                "only the one-way verification (verified, match_score, verified_at) may be set."
            )
        },
    )

    id: Mapped[UUID] = mapped_column(Uuid)
    rule_version_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    clause_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    match_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ExtractionRunRow(Base):
    """One run of an extraction stage over a document: counts and run-level issues."""

    __tablename__ = "extraction_run"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_extraction_run"),
        ForeignKeyConstraint(
            ["document_id"],
            ["document.id"],
            name="fk_extraction_run_document_id_document",
            ondelete="RESTRICT",
        ),
        CheckConstraint(sql_in_list("stage", EXTRACTION_STAGES), name="ck_extraction_run_stage"),
        CheckConstraint(
            sql_in_list("outcome", EXTRACTION_OUTCOMES), name="ck_extraction_run_outcome"
        ),
        Index("ix_extraction_run_document", "document_id"),
        {
            "comment": (
                "One row per document, stage and extractor: counts and run-level issues, "
                "including model output that could not become a candidate. The first write "
                "wins."
            )
        },
    )

    id: Mapped[UUID] = mapped_column(Uuid)
    document_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    extractor: Mapped[str] = mapped_column(String(60), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False, server_default="")
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    counts: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    issues: Mapped[list[object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EntityReviewRow(Base):
    """A mention alignment could not resolve, waiting for or carrying an analyst's decision."""

    __tablename__ = "entity_review"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_entity_review"),
        ForeignKeyConstraint(
            ["document_id"],
            ["document.id"],
            name="fk_entity_review_document_id_document",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["clause_id"],
            ["clause.id"],
            name="fk_entity_review_clause_id_clause",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["resolved_entity_id"],
            ["canonical_entity.id"],
            name="fk_entity_review_resolved_entity_id_canonical_entity",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "clause_id",
            "entity_type",
            "span_start",
            name="uq_entity_review_clause_id_entity_type_span_start",
        ),
        CheckConstraint(
            sql_in_list("entity_type", ENTITY_TYPES), name="ck_entity_review_entity_type"
        ),
        CheckConstraint("span_start >= 0", name="ck_entity_review_span_start"),
        CheckConstraint("span_end > span_start", name="ck_entity_review_span_end"),
        CheckConstraint(sql_in_list("reason", REVIEW_REASONS), name="ck_entity_review_reason"),
        CheckConstraint(sql_in_list("status", REVIEW_STATUSES), name="ck_entity_review_status"),
        CheckConstraint(
            f"resolution IS NULL OR {sql_in_list('resolution', RESOLUTIONS)}",
            name="ck_entity_review_resolution",
        ),
        CheckConstraint(
            f"reject_reason IS NULL OR {sql_in_list('reject_reason', ENTITY_REJECT_REASONS)}",
            name="ck_entity_review_reject_reason",
        ),
        CheckConstraint(
            "(status = 'open' AND resolution IS NULL AND resolved_entity_id IS NULL"
            " AND reject_reason IS NULL AND decided_at IS NULL)"
            " OR (status = 'resolved' AND resolution IS NOT NULL AND resolved_entity_id IS NOT NULL"
            " AND reject_reason IS NULL AND decided_at IS NOT NULL)"
            " OR (status = 'rejected' AND resolution IS NULL AND resolved_entity_id IS NULL"
            " AND reject_reason IS NOT NULL AND decided_at IS NOT NULL)",
            name="ck_entity_review_decision",
        ),
        Index(
            "ix_entity_review_open_group",
            "entity_type",
            "proposed_name",
            postgresql_where=text("status = 'open'"),
        ),
        Index("ix_entity_review_document", "document_id"),
        {
            "comment": (
                "Mentions alignment could not resolve to exactly one canonical entity, decided "
                "per (entity_type, proposed_name). Resolving writes clause_entity rows. Global: "
                "no tenant, no row-level security."
            )
        },
    )

    id: Mapped[UUID] = mapped_column(Uuid)
    document_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    clause_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(16), nullable=False)
    mention_text: Mapped[str] = mapped_column(Text, nullable=False)
    span_start: Mapped[int] = mapped_column(Integer, nullable=False)
    span_end: Mapped[int] = mapped_column(Integer, nullable=False)
    proposed_name: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    reason: Mapped[str] = mapped_column(String(24), nullable=False)
    extractor: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="open")
    resolution: Mapped[str | None] = mapped_column(String(16), nullable=True)
    resolved_entity_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(String(24), nullable=True)
    decided_by: Mapped[str] = mapped_column(String(120), nullable=False, server_default="")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RelationCandidateRow(Base):
    """A relation the model proposed for a document, open until an analyst decides it."""

    __tablename__ = "relation_candidate"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_relation_candidate"),
        ForeignKeyConstraint(
            ["document_id"],
            ["document.id"],
            name="fk_relation_candidate_document_id_document",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["target_clause_id"],
            ["clause.id"],
            name="fk_relation_candidate_target_clause_id_clause",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["evidence_clause_id"],
            ["clause.id"],
            name="fk_relation_candidate_evidence_clause_id_clause",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["target_entity_id"],
            ["canonical_entity.id"],
            name="fk_relation_candidate_target_entity_id_canonical_entity",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["target_rule_id"],
            ["rule.id"],
            name="fk_relation_candidate_target_rule_id_rule",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            sql_in_list("relation", RELATION_KINDS), name="ck_relation_candidate_relation"
        ),
        CheckConstraint(
            sql_in_list("target_type", ENTITY_TYPES), name="ck_relation_candidate_target_type"
        ),
        CheckConstraint(
            "target_span_start >= 0 AND target_span_end > target_span_start",
            name="ck_relation_candidate_target_span",
        ),
        CheckConstraint(
            "target_rule_id IS NULL OR target_rule_key IS NOT NULL",
            name="ck_relation_candidate_rule_hint",
        ),
        CheckConstraint(
            "relation = 'extends_deadline' OR (period_label IS NULL AND new_due_on IS NULL)",
            name="ck_relation_candidate_deadline_detail",
        ),
        CheckConstraint(
            "quote_score BETWEEN 0 AND 1 AND confidence BETWEEN 0 AND 1",
            name="ck_relation_candidate_scores",
        ),
        CheckConstraint(
            "length(evidence_quote) BETWEEN 8 AND 400", name="ck_relation_candidate_quote"
        ),
        CheckConstraint(
            sql_in_list("method", MENTION_METHODS), name="ck_relation_candidate_method"
        ),
        CheckConstraint(
            sql_in_list("status", CANDIDATE_STATUSES), name="ck_relation_candidate_status"
        ),
        CheckConstraint(
            f"reject_reason IS NULL OR {sql_in_list('reject_reason', CANDIDATE_REJECT_REASONS)}",
            name="ck_relation_candidate_reject_reason",
        ),
        CheckConstraint(
            "(status = 'open' AND decided_at IS NULL AND reject_reason IS NULL)"
            " OR (status = 'approved' AND decided_at IS NOT NULL AND reject_reason IS NULL)"
            " OR (status = 'rejected' AND decided_at IS NOT NULL AND reject_reason IS NOT NULL)",
            name="ck_relation_candidate_decision",
        ),
        Index("ix_relation_candidate_document", "document_id"),
        Index(
            "ix_relation_candidate_open",
            "needs_review",
            "created_at",
            postgresql_where=text("status = 'open'"),
        ),
        Index("ix_relation_candidate_target", "target_type", "target_name"),
        {
            "comment": (
                "Relations the model proposed for a document before any rule version exists "
                "for it. An analyst approval turns one into a rule_relation row (ADR-006, "
                "ADR-017); period_label and new_due_on feed the obligation service's deadline "
                "change."
            )
        },
    )

    id: Mapped[UUID] = mapped_column(Uuid)
    document_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    relation: Mapped[str] = mapped_column(String(24), nullable=False)
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_name: Mapped[str] = mapped_column(Text, nullable=False)
    target_clause_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    target_span_start: Mapped[int] = mapped_column(Integer, nullable=False)
    target_span_end: Mapped[int] = mapped_column(Integer, nullable=False)
    target_entity_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    target_rule_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    target_rule_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    evidence_clause_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    evidence_quote: Mapped[str] = mapped_column(Text, nullable=False)
    quote_score: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    period_label: Mapped[str | None] = mapped_column(String(16), nullable=True)
    new_due_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    method: Mapped[str] = mapped_column(String(16), nullable=False, server_default="model")
    prompt_version: Mapped[str] = mapped_column(String(60), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False, server_default="")
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    issues: Mapped[list[object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="open")
    reject_reason: Mapped[str | None] = mapped_column(String(24), nullable=True)
    decided_by: Mapped[str] = mapped_column(String(120), nullable=False, server_default="")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
