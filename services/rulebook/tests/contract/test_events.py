"""The rule events the publish flow writes serialise to messages the published event schemas
accept: every topic it emits, taken from a publication run on the memory store."""

import hashlib
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from cw_contracts.events import TOPICS, EventEnvelopeV1
from domain_kernel.documents import Clause, DocumentType, clause_id_for, document_id_for
from domain_kernel.ids import ClauseId, RuleVersionId, SourceId, UserId
from domain_kernel.knowledge import EntityType, RelationKind, RuleRelation
from domain_kernel.status import RuleVersionStatus
from py_common.events import decode, encode, to_message
from rulebook.application.documents import RegisterDocument
from rulebook.application.publication import (
    AddCitations,
    ApplyDueTransitions,
    ApproveVersion,
    CitationInput,
    PublishVersion,
    SubmitForReview,
    WithdrawVersion,
)
from rulebook.domain.documents import StoredDocument
from rulebook.domain.events import RuleEvent
from rulebook.domain.relations import RelationCandidate
from rulebook.infrastructure.memory import MemoryKnowledgeStore

NOW = datetime(2026, 10, 1, 4, 30, tzinfo=UTC)
TEXT = "The due date for the return in FORM GSTR-3B for September, 2026 is extended."
QUOTE = "the return in FORM GSTR-3B for September, 2026"
ANALYST = UserId(UUID(int=11))
REVIEWER = UserId(UUID(int=12))
SPECIFICATION = {"attribute": "registration_type", "operator": "eq", "value": "regular"}


def check(event: RuleEvent) -> None:
    message = decode(encode(to_message(event)))
    EventEnvelopeV1.model_validate(message.model_dump(mode="json"))
    spec = TOPICS[message.topic]
    assert message.schema_version == spec.version
    assert not spec.tenant_scoped
    assert message.tenant_id is None
    spec.model.model_validate(message.payload)


def publish(
    store: MemoryKnowledgeStore, version: RuleVersionId, clause: ClauseId, *, high_impact: bool
) -> None:
    def clock() -> datetime:
        return NOW

    AddCitations(store, clock).run(version, [CitationInput(clause, QUOTE)])
    SubmitForReview(store, clock).run(version, actor_id=ANALYST, high_impact=high_impact)
    ApproveVersion(store, clock).run(version, actor_id=REVIEWER)
    if high_impact:
        ApproveVersion(store, clock).run(version, actor_id=ANALYST)
    PublishVersion(store, enabled=True, clock=clock).run(version, actor_id=ANALYST)


def test_every_rule_event_matches_its_schema() -> None:
    store = MemoryKnowledgeStore()
    digest = hashlib.sha256(b"contract").hexdigest()
    document_id = document_id_for(digest)
    RegisterDocument(store).run(
        StoredDocument(
            document_id=document_id,
            source_id=SourceId(UUID(int=7)),
            sha256=digest,
            regulator="CBIC",
            doc_type=DocumentType.NOTIFICATION,
            url="https://example.invalid/contract.pdf",
            language="en",
            media_type="application/pdf",
            parser_version="pdf@1",
            fetched_at=NOW,
        ),
        [Clause("en.p1", TEXT)],
    )
    clause = clause_id_for(document_id, "en.p1")
    _, old = store.add_rule(
        "gstr3b_monthly",
        title="Monthly",
        status=RuleVersionStatus.PUBLISHED,
        effective_from=date(2026, 4, 1),
        recurrence={"frequency": "monthly", "due_day": 20, "due_month_offset": 0},
    )
    _, withdrawn = store.add_rule("gstr1_monthly", title="Old", status=RuleVersionStatus.PUBLISHED)
    _, future_target = store.add_rule(
        "cmp08_quarterly", title="Quarterly", status=RuleVersionStatus.PUBLISHED
    )
    new = store.add_version(
        "gstr3b_monthly", title="Monthly, amended", effective_from=date(2026, 7, 1)
    )
    later = store.add_version(
        "cmp08_quarterly", title="Quarterly, amended", effective_from=date(2026, 11, 1)
    )
    candidate_id = uuid4()
    with store() as uow:
        uow.candidates.add(
            RelationCandidate(
                candidate_id=candidate_id,
                document_id=document_id,
                relation=RelationKind.EXTENDS_DEADLINE,
                target_type=EntityType.FORM,
                target_name="GSTR-3B",
                target_clause_id=clause,
                target_span_start=TEXT.index("FORM"),
                target_span_end=TEXT.index("FORM") + 12,
                evidence_clause_id=clause,
                evidence_quote=QUOTE,
                quote_score=1.0,
                prompt_version="extraction.rule_relations@1",
                confidence=0.9,
                needs_review=False,
                period_label="2026-09",
                new_due_on=date(2026, 10, 27),
            )
        )
        for kind, target, candidate in (
            (RelationKind.SUPERSEDES, old, None),
            (RelationKind.EXTENDS_DEADLINE, old, candidate_id),
        ):
            uow.relations.add(
                RuleRelation(new, kind, target, clause), relation_id=uuid4(), candidate_id=candidate
            )
        uow.relations.add(
            RuleRelation(later, RelationKind.WITHDRAWS, future_target, clause),
            relation_id=uuid4(),
            candidate_id=None,
        )
    publish(store, new, clause, high_impact=True)
    publish(store, later, clause, high_impact=False)
    WithdrawVersion(store, enabled=True, clock=lambda: NOW).run(withdrawn, actor_id=ANALYST)
    ApplyDueTransitions(store, enabled=True, clock=lambda: datetime(2026, 11, 1, tzinfo=UTC)).run()

    events = store.events()
    assert sorted({type(event).topic for event in events}) == [
        "rule.deadline_changed",
        "rule.published",
        "rule.superseded",
        "rule.withdrawn",
    ]
    assert len(events) == 6
    for event in events:
        check(event)
