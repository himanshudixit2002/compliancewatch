"""Align the mentions the pipeline found in a document: record the ones that resolve to a
canonical entity, queue the rest for review, in one transaction.

Each mention is checked against the stored clause first: its text must be exactly what the
clause holds at its span, and its proposed name must already be canonical. A mention that fails
either check fails the whole submission (422), because a wrong span would point the index at
the wrong characters. Re-submitting the same mentions changes nothing.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from domain_kernel.events import utc_now
from domain_kernel.ids import DocumentId
from domain_kernel.knowledge import EntityType, normalise_name
from rulebook.domain.alignment import Resolved, resolve
from rulebook.domain.errors import (
    MentionSpanMismatchError,
    NonCanonicalNameError,
    UnknownClauseError,
    UnknownDocumentError,
)
from rulebook.domain.ids import review_id_for, run_id_for
from rulebook.domain.repository import KnowledgeUnitOfWorkFactory
from rulebook.domain.review import EntityReviewItem
from rulebook.domain.runs import ExtractionRun

Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class SubmittedMention:
    clause_ref: str
    entity_type: EntityType
    text: str
    span_start: int
    span_end: int
    proposed_name: str


@dataclass(frozen=True, slots=True)
class AlignmentReport:
    aligned: int
    queued: int
    unchanged: int


class AlignMentions:
    def __init__(self, unit_of_work: KnowledgeUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(
        self, document_id: DocumentId, extractor: str, mentions: Sequence[SubmittedMention]
    ) -> AlignmentReport:
        aligned = queued = unchanged = 0
        with self._unit_of_work() as uow:
            if uow.documents.get(document_id) is None:
                raise UnknownDocumentError(str(document_id))
            clauses = {clause.clause_ref: clause for clause in uow.documents.clauses(document_id)}
            for mention in mentions:
                clause = clauses.get(mention.clause_ref)
                if clause is None:
                    raise UnknownClauseError(
                        f"{mention.clause_ref} is not a clause of document {document_id}"
                    )
                if clause.text[mention.span_start : mention.span_end] != mention.text:
                    raise MentionSpanMismatchError(
                        f"{mention.clause_ref}[{mention.span_start}:{mention.span_end}] is not "
                        f"{mention.text!r}"
                    )
                if normalise_name(mention.entity_type, mention.proposed_name) != (
                    mention.proposed_name
                ):
                    raise NonCanonicalNameError(
                        f"{mention.entity_type.value} name {mention.proposed_name!r} is not "
                        "canonical"
                    )
                outcome = resolve(mention.entity_type, mention.proposed_name, uow.entities)
                if isinstance(outcome, Resolved):
                    added = uow.mentions.add(
                        clause.clause_id,
                        outcome.entity_id,
                        mention.text,
                        mention.span_start,
                        mention.span_end,
                        method="grammar",
                        extractor=extractor,
                    )
                    aligned, unchanged = aligned + added, unchanged + (not added)
                    continue
                item = EntityReviewItem(
                    review_id=review_id_for(
                        clause.clause_id, mention.entity_type, mention.span_start
                    ),
                    document_id=document_id,
                    clause_id=clause.clause_id,
                    entity_type=mention.entity_type,
                    mention_text=mention.text,
                    span_start=mention.span_start,
                    span_end=mention.span_end,
                    proposed_name=mention.proposed_name,
                    reason=outcome.reason,
                    extractor=extractor,
                )
                added = uow.reviews.enqueue(item)
                queued, unchanged = queued + added, unchanged + (not added)
            uow.runs.record(
                ExtractionRun(
                    run_id=run_id_for(document_id, "mentions", extractor),
                    document_id=document_id,
                    stage="mentions",
                    extractor=extractor,
                    outcome="needs_review" if queued else "ok",
                    counts={"aligned": aligned, "queued": queued, "unchanged": unchanged},
                )
            )
        return AlignmentReport(aligned=aligned, queued=queued, unchanged=unchanged)


def default_clock() -> datetime:
    return utc_now()
