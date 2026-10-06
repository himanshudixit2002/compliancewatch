"""Helpers for tests and demos that run the rulebook in process on the memory store.

``ExampleDecisions`` is a memory store with a synthetic notification registered and three rule
candidates of it decided through the review use cases: one approved after an edit to its title,
one rejected, one approved with conditions the golden shape cannot hold. The golden export's
tests and its contract with the eval harness (``packages/contracts/golden``) start from it.
"""

import hashlib
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final
from uuid import UUID

from domain_kernel.documents import Clause, DocumentType, clause_id_for, document_id_for
from domain_kernel.ids import SourceId, UserId
from domain_kernel.ontology import AttributeLevel, Ontology
from rulebook.application.documents import RegisterDocument
from rulebook.application.intake import IngestRuleCandidate
from rulebook.application.review_tasks import (
    ClaimReviewTask,
    DecideReviewTask,
    DraftFromCandidate,
    NewRule,
)
from rulebook.domain.documents import StoredDocument
from rulebook.domain.drafting import DraftEdit
from rulebook.domain.intake import RuleRejectReason
from rulebook.domain.review_tasks import ReviewDecision
from rulebook.infrastructure.memory import MemoryKnowledgeStore
from rulebook.settings import RulebookSettings

WRITE_TOKEN = "test-write-token"
"""The write token ``rulebook_settings`` configures; send it as ``x-cw-write-token``."""
REVIEW_TOKEN = "test-review-token"
"""The review token ``rulebook_settings`` configures; send it as ``x-cw-review-token``."""


def rulebook_settings(**overrides: Any) -> RulebookSettings:
    """Settings that ignore the repo ``.env``: the memory store, ``WRITE_TOKEN`` and
    ``REVIEW_TOKEN``."""
    values: dict[str, Any] = {
        "_env_file": None,
        "service_name": "rulebook",
        "rulebook_store": "memory",
        "rulebook_write_token": WRITE_TOKEN,
        "rulebook_review_token": REVIEW_TOKEN,
    }
    values.update(overrides)
    return RulebookSettings(**values)


# ---------------------------------------------------------------- decided candidates

START: Final = datetime(2000, 1, 3, 4, 30, tzinfo=UTC)
ANALYST: Final = UserId(UUID(int=71))
REVIEWER: Final = UserId(UUID(int=72))
CLAUSES: Final = (
    Clause("en.p1", "Example notification No. 05/2000 of the example board.", 1),
    Clause(
        "en.p2",
        "Every registered person furnishing the example return shall file the example "
        "statement for each month by the eleventh day of the following month.",
        1,
    ),
    Clause("en.p3", "This example notification shall come into effect from 1st March, 2000.", 1),
)
QUOTE_FILE: Final = "shall file the example statement for each month by the eleventh day"
QUOTE_EFFECT: Final = "shall come into effect from 1st March, 2000"
DIGEST: Final = hashlib.sha256(b"example notification for the golden export").hexdigest()
DOC: Final = document_id_for(DIGEST)
FIELDS: Final[dict[str, Any]] = {
    "title": "Example: monthly example statement by the eleventh",
    "summary": "An example notification has registered persons file an example statement.",
    "doc_kind": "notification",
    "change_kind": "none",
    "effective_from": "2000-03-01",
    "effective_to": None,
    "references": ["Example notification No. 01/2000"],
    "applies_to": [
        {
            "attribute": "registration_type",
            "operator": "eq",
            "value": "regular",
            "clause_ref": "en.p2",
        }
    ],
    "obligation": {
        "title": "File the example statement",
        "steps": ["Furnish the example statement"],
        "evidence_type": "filing_acknowledgement",
        "due_in_days": None,
        "clause_ref": "en.p2",
    },
    "recurrence": {
        "frequency": "monthly",
        "due_day": 11,
        "due_month_offset": 1,
        "clause_ref": "en.p2",
    },
    "amounts": [],
    "citations": [
        {"clause_ref": "en.p2", "quote": QUOTE_FILE},
        {"clause_ref": "en.p3", "quote": QUOTE_EFFECT},
    ],
    "confidence": 0.8,
}
APPROVED: Final = UUID("00000000-0000-4000-8000-00000000a001")
REJECTED: Final = UUID("00000000-0000-4000-8000-00000000a002")
UNFIT: Final = UUID("00000000-0000-4000-8000-00000000a003")


class Clock:
    def __init__(self, start: datetime = START) -> None:
        self.now = start

    def __call__(self) -> datetime:
        self.now += timedelta(minutes=1)
        return self.now


def payload(candidate_id: UUID, **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "candidate_id": str(candidate_id),
        "document_id": str(DOC),
        "regulator": "CBIC",
        "model": "scripted/golden",
        "prompt_version": "extraction.rule_candidate@1",
        "confidence": 0.8,
        "citation_count": 2,
        "needs_review": False,
        "outcome": "extracted",
        "candidate": FIELDS,
        "issues": [],
        "suggested_rule_key": None,
        "clause_ids": [str(clause_id_for(DOC, ref)) for ref in ("en.p2", "en.p3")],
        "doc_type": "notification",
        "source_id": str(UUID(int=11)),
        "source_key": "cbic_notifications",
        "ontology_version": "0.2.0",
    }
    values.update(overrides)
    return values


class ExampleDecisions:
    """The memory store with the example notification registered, and three candidates of it
    decided: one approved (drafted with an edit to its title), one rejected, one approved whose
    conditions an analyst rewrote as an any_of."""

    def __init__(self, ontology: Ontology) -> None:
        self.clock = Clock()
        self.store = MemoryKnowledgeStore(self.clock)
        RegisterDocument(self.store).run(
            StoredDocument(
                document_id=DOC,
                source_id=SourceId(UUID(int=11)),
                sha256=DIGEST,
                regulator="CBIC",
                doc_type=DocumentType.NOTIFICATION,
                url="https://example.invalid/notification-05-2000.pdf",
                language="en",
                media_type="application/pdf",
                parser_version="pdf@1",
                fetched_at=START,
                external_ref="05/2000-Example",
                title="Example notification 05/2000",
                published_at=date(2000, 2, 25),
            ),
            list(CLAUSES),
        )
        ingest = IngestRuleCandidate(self.store, self.clock)
        claim = ClaimReviewTask(self.store, self.clock)
        draft = DraftFromCandidate(self.store, lambda: ontology, self.clock)
        decide = DecideReviewTask(self.store, self.clock)

        def task(candidate_id: UUID) -> UUID:
            intake = ingest.run(payload(candidate_id), UUID(int=candidate_id.int + 1))
            assert intake.task is not None
            claim.run(intake.task.task_id, by=ANALYST)
            return intake.task.task_id

        approved = task(APPROVED)
        draft.run(
            approved,
            by=ANALYST,
            rule_key="example_statement_monthly",
            new_rule=NewRule("cbic", AttributeLevel.REGISTRATION),
            edit=DraftEdit({"title": "Example: the monthly example statement"}),
        )
        decide.run(approved, ReviewDecision.APPROVE, by=REVIEWER)
        rejected = task(REJECTED)
        decide.run(
            rejected,
            ReviewDecision.REJECT,
            by=REVIEWER,
            note="Example: the model read it wrongly",
            reason=RuleRejectReason.WRONG_EXTRACTION,
        )
        unfit = task(UNFIT)
        draft.run(
            unfit,
            by=ANALYST,
            rule_key="example_statement_any",
            new_rule=NewRule("cbic", AttributeLevel.REGISTRATION),
            edit=DraftEdit(
                {
                    "specification": {
                        "any_of": [
                            {"attribute": "registration_type", "operator": "eq", "value": "regular"}
                        ]
                    }
                }
            ),
        )
        decide.run(unfit, ReviewDecision.APPROVE, by=REVIEWER)
