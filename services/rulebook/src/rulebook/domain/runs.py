"""Records of what the rulebook holds besides documents and knowledge: extraction runs and the
catalogue of rules the pipeline may point a relation at."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from uuid import UUID

from domain_kernel.ids import DocumentId


@dataclass(frozen=True, slots=True)
class ExtractionRun:
    """One run of an extraction stage over a document. ``issues`` are the run-level problems,
    including the verbatim model output that could not become a candidate."""

    run_id: UUID
    document_id: DocumentId
    stage: str
    extractor: str
    outcome: str
    model: str = ""
    counts: Mapping[str, int] = field(default_factory=dict)
    issues: tuple[Mapping[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class RuleSummary:
    """A rule as the pipeline sees it: its key, id, regulator and latest title."""

    rule_key: str
    rule_id: UUID
    regulator: str
    title: str
