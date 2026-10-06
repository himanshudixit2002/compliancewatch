"""What a parsed document is, how sure the pipeline is of it, and where it goes next (the
``document_classification`` table).

The classify step reads every parsed document once, after its parse and before anything is
registered or extracted, and records:

- its ``doc_type``;
- its ``relevance``: ``irrelevant`` for something that is no regulatory document (a portal user
  manual listed among notifications), else ``relevant``;
- its ``confidence`` in the type: ``certain`` when the text names the type its source publishes
  (or a person gave the type), ``default`` when nothing in the text names a type and the
  source's is taken, ``conflict`` when the text names another type than its source publishes;
- the ``reasons``, in words.

The route follows (``Route``): an irrelevant document is set aside, a conflict waits for a
person's triage (a ``triage`` task), a press release or a statute is kept for reference
(registered and embedded, nothing extracted), and a notification, circular or act amendment
goes on to the rule extraction. A person's triage replaces a conflict with their decision,
``certain``, by the ``triage`` classifier.

A document's status names its route, not what became of it. The classify step sets it before
anything is registered, in the transaction of the classification:

- ``irrelevant`` and ``triage``: the ingest ends there and nothing is registered;
- ``reference``: on its way to be registered and embedded, nothing extracted. It is registered
  only while knowledge is on and its registration succeeds, so a ``reference`` document may be
  in no rulebook (the ingest's result says ``registered``);
- ``classified``: on its way to the rule extraction, registered the same way, and extracted only
  once registered and while the extraction is on; a document stays ``classified`` while the
  extraction is off, when it failed, and when knowledge is off;
- ``extracted``, set by the stored extraction: an extraction is stored, whatever its outcome,
  so an ``unparseable`` one, with no candidate for an analyst to review, is ``extracted`` too
  (``domain.extraction``).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from domain_kernel._validation import require_aware, require_instance, require_text
from domain_kernel.documents import DocumentType
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import DocumentId
from pipeline.domain.raw_documents import DocumentStatus
from pipeline.domain.tasks import TaskId

DETECTOR: Final = "detector@1"
"""The rule-based classifier (``application.detector``); bump it when its reading changes."""
TRIAGE: Final = "triage"
"""The classifier of a person's triage decision."""
MAX_REASONS: Final = 8
MAX_REASON_CHARS: Final = 500

RULE_KINDS: Final[tuple[str, ...]] = ("notification", "circular", "act_amendment")
"""The document types a rule candidate is extracted from. A press release announces what the
Council recommended, which is not in force until a notification says so, and a statute is the
law the other documents act on: both are kept for reference, and no rule is extracted from
them."""


def extracts_rules(doc_type: DocumentType | str) -> bool:
    """Whether the rule extraction reads a document of this type."""
    return DocumentType(doc_type).value in RULE_KINDS


class Relevance(StrEnum):
    RELEVANT = "relevant"
    IRRELEVANT = "irrelevant"


class TypeConfidence(StrEnum):
    """How sure the classifier is of the type: the text names it (``certain``), nothing in the
    text names one and the source's is taken (``default``), or the text names another type than
    its source publishes (``conflict``)."""

    CERTAIN = "certain"
    DEFAULT = "default"
    CONFLICT = "conflict"


class Route(StrEnum):
    """Where a classified document goes: on to the rule extraction, kept for reference, set
    aside as irrelevant, or held for a person's triage."""

    EXTRACT = "extract"
    REFERENCE = "reference"
    IRRELEVANT = "irrelevant"
    TRIAGE = "triage"

    @property
    def status(self) -> DocumentStatus:
        """The document's status on this route, set when it is classified, before anything is
        registered: the route it takes, not an outcome."""
        return _STATUS[self]

    @property
    def stops(self) -> bool:
        """Whether the ingest ends here: nothing is registered while a document waits for its
        triage, or once it is set aside."""
        return self in (Route.IRRELEVANT, Route.TRIAGE)


_STATUS: Final = {
    Route.EXTRACT: DocumentStatus.CLASSIFIED,
    Route.REFERENCE: DocumentStatus.REFERENCE,
    Route.IRRELEVANT: DocumentStatus.IRRELEVANT,
    Route.TRIAGE: DocumentStatus.TRIAGE,
}


def route_of(doc_type: DocumentType, relevance: Relevance, confidence: TypeConfidence) -> Route:
    """An irrelevant document is set aside whatever its type; a conflict waits for triage; a
    rule kind goes on to the extraction; anything else is kept for reference."""
    if relevance is Relevance.IRRELEVANT:
        return Route.IRRELEVANT
    if confidence is TypeConfidence.CONFLICT:
        return Route.TRIAGE
    return Route.EXTRACT if extracts_rules(doc_type) else Route.REFERENCE


@dataclass(frozen=True, slots=True)
class Classification:
    """One document's classification: by the detector, or by a person's triage
    (``classifier`` ``triage``, ``decided_by`` the person, ``task_id`` the task they resolved).
    A conflict names the triage task it opened in ``task_id``."""

    document_id: DocumentId
    doc_type: DocumentType
    relevance: Relevance
    confidence: TypeConfidence
    reasons: tuple[str, ...]
    classified_at: datetime
    classifier: str = DETECTOR
    decided_by: UUID | None = None
    task_id: TaskId | None = None

    def __post_init__(self) -> None:
        require_instance(self.document_id, DocumentId, "document_id")
        require_instance(self.doc_type, DocumentType, "doc_type")
        require_instance(self.relevance, Relevance, "relevance")
        require_instance(self.confidence, TypeConfidence, "confidence")
        reasons = require_instance(self.reasons, tuple, "reasons")
        if not 1 <= len(reasons) <= MAX_REASONS:
            raise InvariantViolationError(f"a classification gives 1 to {MAX_REASONS} reasons")
        for reason in reasons:
            if len(require_text(reason, "reason")) > MAX_REASON_CHARS:
                raise InvariantViolationError(f"a reason is at most {MAX_REASON_CHARS} characters")
        require_aware(self.classified_at, "classified_at")
        require_text(self.classifier, "classifier")
        if self.decided_by is not None:
            require_instance(self.decided_by, UUID, "decided_by")
            if self.classifier != TRIAGE:
                raise InvariantViolationError("only a triage is decided by a person")
        if self.task_id is not None:
            require_instance(self.task_id, TaskId, "task_id")

    @property
    def route(self) -> Route:
        return route_of(self.doc_type, self.relevance, self.confidence)

    @classmethod
    def triaged(
        cls,
        document_id: DocumentId,
        *,
        relevance: Relevance,
        doc_type: DocumentType,
        by: UUID | None,
        task_id: TaskId,
        at: datetime,
        reason: str,
    ) -> "Classification":
        """A person's triage: the type they gave (a relevant document) or the type the
        classifier read (an irrelevant one), ``certain``, with their reason."""
        verdict = (
            f"an analyst triaged it as a {doc_type.value.replace('_', ' ')}"
            if relevance is Relevance.RELEVANT
            else "an analyst triaged it as no regulatory document"
        )
        return cls(
            document_id=document_id,
            doc_type=doc_type,
            relevance=relevance,
            confidence=TypeConfidence.CERTAIN,
            reasons=reasons_of((verdict, reason)),
            classified_at=at,
            classifier=TRIAGE,
            decided_by=by,
            task_id=task_id,
        )


def reasons_of(texts: Sequence[str]) -> tuple[str, ...]:
    """``texts`` as a classification's reasons, in order: blank ones dropped, each trimmed to
    fit, at most ``MAX_REASONS``."""
    kept = [text.strip()[:MAX_REASON_CHARS] for text in texts if text.strip()]
    return tuple(kept[:MAX_REASONS])


@dataclass(frozen=True, slots=True)
class TriageDecision:
    """A person's triage of a conflict: the document is ``relevant`` and of ``doc_type``, or
    ``irrelevant`` (no type: the classifier's reading stays on record)."""

    relevance: Relevance
    doc_type: DocumentType | None = None

    def __post_init__(self) -> None:
        require_instance(self.relevance, Relevance, "relevance")
        if self.doc_type is not None:
            require_instance(self.doc_type, DocumentType, "doc_type")
        if (self.relevance is Relevance.RELEVANT) != (self.doc_type is not None):
            raise InvariantViolationError(
                "a relevant document is triaged with its type, an irrelevant one without"
            )

    def resolution(self) -> dict[str, object]:
        """What the task's resolution records of it."""
        return {
            "relevance": self.relevance.value,
            "doc_type": None if self.doc_type is None else self.doc_type.value,
        }
