"""Records the pipeline hands to the rulebook, which owns regulator documents, their clauses
and the knowledge found in them."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime

from domain_kernel.documents import ParsedDocument
from domain_kernel.ids import ClauseId, DocumentId, SourceId
from domain_kernel.knowledge import RelationKind
from pipeline.domain.grammar import ExtractedMention
from pipeline.domain.issues import Issue


@dataclass(frozen=True, slots=True)
class DocumentRecord:
    """A parsed document plus where it came from. ``document`` carries the clauses, the title,
    the language, the publication date and the parser version."""

    document: ParsedDocument
    source_id: SourceId
    sha256: str
    regulator: str
    url: str
    media_type: str
    fetched_at: datetime
    external_ref: str = ""
    raw_uri: str | None = None


@dataclass(frozen=True, slots=True)
class RegisteredDocument:
    """The rulebook's answer: whether it stored the document now, and the id of each clause."""

    document_id: DocumentId
    created: bool
    clause_ids: Mapping[str, ClauseId] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MentionSubmission:
    """The mentions one extractor found in one document, for the rulebook to align."""

    document_id: DocumentId
    extractor: str
    mentions: tuple[ExtractedMention, ...]


@dataclass(frozen=True, slots=True)
class AlignmentReport:
    aligned: int
    queued: int
    unchanged: int


@dataclass(frozen=True, slots=True)
class StagedRelation:
    """A proposed relation after the validators: its target mention, its evidence, the checks'
    issues and the confidence they left."""

    relation: RelationKind
    target: ExtractedMention
    evidence_clause_ref: str
    evidence_quote: str
    quote_score: float
    confidence: float
    needs_review: bool
    rule_key: str | None = None
    period_label: str | None = None
    new_due_on: date | None = None
    issues: tuple[Issue, ...] = ()


@dataclass(frozen=True, slots=True)
class RelationSubmission:
    """What one run of the relation stage produced for a document, for the rulebook to stage.
    ``run_issues`` keep what could not become a candidate, verbatim."""

    document_id: DocumentId
    extractor: str
    model: str
    outcome: str
    candidates: tuple[StagedRelation, ...] = ()
    run_issues: tuple[Issue, ...] = ()


@dataclass(frozen=True, slots=True)
class StagingReport:
    created: int
    unchanged: int


@dataclass(frozen=True, slots=True)
class RuleKey:
    """A rule the model may name as the one a relation affects."""

    rule_key: str
    title: str
