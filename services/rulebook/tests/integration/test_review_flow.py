"""The knowledge use cases on the Postgres unit of work, from a registered document to an
approved rule relation, plus the checks migration 0005 adds and the review queue numbers.
Needs Docker."""

import hashlib
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from testcontainers.community.postgres import PostgresContainer

from domain_kernel.documents import Clause, DocumentType, clause_id_for, document_id_for
from domain_kernel.ids import RuleVersionId, SourceId
from domain_kernel.knowledge import EntityType, RelationKind
from rulebook.application.alignment import AlignMentions, SubmittedMention
from rulebook.application.documents import RegisterDocument
from rulebook.application.relations import (
    ApproveRelationCandidate,
    ListRelationCandidates,
    ListRules,
    RejectRelationCandidate,
    RelationSubmission,
    StageRelationCandidates,
    SubmittedCandidate,
)
from rulebook.application.review import (
    DecideMentionGroup,
    ListMentionGroups,
    ReadReviewQueueStats,
)
from rulebook.domain.alignment import ReviewReason
from rulebook.domain.documents import StoredDocument
from rulebook.domain.errors import SupersessionCycleError
from rulebook.domain.relations import CandidateRejectReason, CandidateStatus
from rulebook.domain.review import (
    EntityRejectReason,
    EntityReviewItem,
    MentionDecision,
    Resolution,
)
from rulebook.infrastructure.knowledge_repository import PostgresKnowledgeUnitOfWorkFactory

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "rulebook"
NOW = datetime(2026, 9, 28, 12, tzinfo=UTC)
TEXT = (
    "sub -section (6) of section 39 of the Central Goods and Services Tax Act, 2017 hereby "
    "extends the due date for furnishing the return in FORM GSTR-3B for March, 2026"
)
DIGEST = hashlib.sha256(b"review flow document").hexdigest()
DOC = document_id_for(DIGEST)


def clock() -> datetime:
    return NOW


@pytest.fixture(scope="module")
def factory() -> Iterator[PostgresKnowledgeUnitOfWorkFactory]:
    with PostgresContainer(IMAGE, driver="psycopg") as postgres:
        base_url = postgres.get_connection_url()
        admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
        admin.dispose()
        url = f"{base_url}?options=-csearch_path%3D{SCHEMA}%2Cpublic"
        with pytest.MonkeyPatch.context() as env:
            env.setenv("CW_DATABASE_URL", url)
            env.setenv("CW_DB_SCHEMA", SCHEMA)
            command.upgrade(Config(str(SERVICE_DIR / "alembic.ini")), "head")
        factory = PostgresKnowledgeUnitOfWorkFactory.from_url(url)
        RegisterDocument(factory).run(
            StoredDocument(
                document_id=DOC,
                source_id=SourceId(UUID(int=7)),
                sha256=DIGEST,
                regulator="CBIC",
                doc_type=DocumentType.NOTIFICATION,
                url="https://example.invalid/n.pdf",
                language="en",
                media_type="application/pdf",
                parser_version="pdf@1",
                fetched_at=NOW,
            ),
            (Clause("en.p1", "NOTIFICATION No. 01/2026 - Central Tax"), Clause("en.p3", TEXT)),
        )
        yield factory
        factory.engine.dispose()


def rule(factory: PostgresKnowledgeUnitOfWorkFactory, key: str, status: str) -> RuleVersionId:
    rule_id, version_id = uuid4(), uuid4()
    with factory.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO rule (id, rule_key, regulator, level)"
                " VALUES (:id, :key, 'CBIC', 'registration')"
            ),
            {"id": rule_id, "key": key},
        )
        connection.execute(
            text(
                "INSERT INTO rule_version (id, rule_id, version, status, title, specification,"
                " obligation_template, effective_from)"
                " VALUES (:id, :rule, 1, :status, :title, '{}', '{}', '2026-04-01')"
            ),
            {"id": version_id, "rule": rule_id, "status": status, "title": f"{key} title"},
        )
    return RuleVersionId(version_id)


def mention(text_: str, kind: EntityType, name: str) -> SubmittedMention:
    start = TEXT.index(text_)
    return SubmittedMention("en.p3", kind, text_, start, start + len(text_), name)


FORM = mention("FORM GSTR-3B", EntityType.FORM, "GSTR-3B")
SECTION = mention("sub -section (6) of section 39", EntityType.SECTION, "39(6)@cgst-act")
BARE = mention("section 39", EntityType.SECTION, "39")
EXTENDS = SubmittedCandidate(
    relation=RelationKind.EXTENDS_DEADLINE,
    target_type=EntityType.FORM,
    target_name="GSTR-3B",
    target_clause_ref="en.p3",
    target_span_start=TEXT.index("FORM GSTR-3B"),
    target_span_end=TEXT.index("FORM GSTR-3B") + 12,
    evidence_clause_ref="en.p3",
    evidence_quote="hereby extends the due date for furnishing the return",
    quote_score=1.0,
    confidence=0.9,
    needs_review=False,
    rule_key="gstr3b_monthly",
    period_label="2026-03",
    new_due_on=date(2026, 4, 21),
)


def test_mentions_review_and_candidates_end_to_end(
    factory: PostgresKnowledgeUnitOfWorkFactory,
) -> None:
    rule(factory, "gstr3b_monthly", "published")
    with factory() as uow:
        form_id, created = uow.entities.create_or_get(EntityType.FORM, "GSTR-3B")
        assert created is True
        assert uow.entities.create_or_get(EntityType.FORM, "GSTR-3B") == (form_id, False)
        assert uow.entities.add_alias(form_id, "GSTR-3") is True
        assert uow.entities.add_alias(form_id, "GSTR-3") is False
        assert uow.entities.by_alias(EntityType.FORM, "GSTR-3") == [form_id]
        assert uow.entities.get(form_id) == (EntityType.FORM, "GSTR-3B")

    report = AlignMentions(factory).run(DOC, "grammar@1", [FORM, SECTION, BARE])
    assert (report.aligned, report.queued, report.unchanged) == (1, 2, 0)
    again = AlignMentions(factory).run(DOC, "grammar@1", [FORM, SECTION, BARE])
    assert (again.aligned, again.queued, again.unchanged) == (0, 0, 3)

    groups = ListMentionGroups(factory).run()
    assert [(g.proposed_name, g.open_count) for g in groups] == [("39", 1), ("39(6)@cgst-act", 1)]
    assert [g.proposed_name for g in ListMentionGroups(factory).run(after=("section", "39"))] == [
        "39(6)@cgst-act"
    ]

    refers = replace(
        EXTENDS,
        relation=RelationKind.REFERS_TO,
        target_type=EntityType.SECTION,
        target_name="39(6)@cgst-act",
        rule_key=None,
        period_label=None,
        new_due_on=None,
    )
    staged = StageRelationCandidates(factory).run(
        DOC,
        RelationSubmission(
            "extraction.rule_relations@1",
            "scripted/golden",
            "ok",
            (EXTENDS, refers),
            ({"code": "detector_relation_missing", "detail": "x"},),
        ),
    )
    assert (staged.created, staged.unchanged) == (2, 0)
    extends_id, refers_id = staged.candidate_ids
    by_id = {c.candidate_id: c for c in ListRelationCandidates(factory).run()}
    assert by_id[extends_id].target_entity_id == form_id
    assert by_id[extends_id].target_rule_id is not None
    assert by_id[extends_id].new_due_on == date(2026, 4, 21)
    assert by_id[refers_id].target_entity_id is None

    decided = DecideMentionGroup(factory, clock).run(
        EntityType.SECTION, "39(6)@cgst-act", MentionDecision.CREATE_ENTITY, decided_by="analyst"
    )
    assert (decided.resolution, decided.items_closed, decided.relation_targets_updated) == (
        Resolution.CREATED,
        1,
        1,
    )
    with factory() as uow:
        bare_ids = [item.review_id for item in uow.reviews.group_items(EntityType.SECTION, "39")]
    rejected = DecideMentionGroup(factory, clock).run(
        EntityType.SECTION,
        "39",
        MentionDecision.REJECT,
        decided_by="analyst",
        reject_reason=EntityRejectReason.TEXT_ARTIFACT,
        review_ids=bare_ids,
    )
    assert rejected.items_closed == 1
    assert ListMentionGroups(factory).run() == []

    new_version = rule(factory, "gstr3b_extension", "draft")
    affected = rule(factory, "gstr3b_monthly_old", "published")
    approval = ApproveRelationCandidate(factory, clock).run(
        extends_id, new_version, affected, decided_by="analyst"
    )
    ApproveRelationCandidate(factory, clock).run(refers_id, new_version, None, decided_by="a")
    with factory.engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT relation, to_kind, to_rule_version_id, to_entity_id, candidate_id,"
                " clause_id FROM rule_relation ORDER BY relation"
            )
        ).all()
        mentions: int = connection.execute(text("SELECT count(*) FROM clause_entity")).scalar_one()
        runs = connection.execute(
            text("SELECT stage, outcome, issues FROM extraction_run ORDER BY stage")
        ).all()
    assert [(r.relation, r.to_kind) for r in rows] == [
        ("extends_deadline", "rule_version"),
        ("refers_to", "section"),
    ]
    assert rows[0].to_rule_version_id == affected.value
    assert rows[0].candidate_id == extends_id
    assert rows[0].clause_id == clause_id_for(DOC, "en.p3").value
    assert decided.entity_id is not None
    assert rows[1].to_entity_id == decided.entity_id.value
    assert approval.rule_relation_id
    assert mentions == 2
    assert [(r.stage, r.outcome) for r in runs] == [
        ("mentions", "needs_review"),
        ("relations", "ok"),
    ]
    assert runs[1].issues == [{"code": "detector_relation_missing", "detail": "x"}]
    approved = ListRelationCandidates(factory).run(status=CandidateStatus.APPROVED)
    assert {c.candidate_id for c in approved} == {extends_id, refers_id}

    rules = {r.rule_key: r.title for r in ListRules(factory).run()}
    assert rules["gstr3b_monthly"] == "gstr3b_monthly title"


def test_supersession_cycles_and_rejections(factory: PostgresKnowledgeUnitOfWorkFactory) -> None:
    first, second = rule(factory, "a_rule", "draft"), rule(factory, "b_rule", "draft")
    supersedes = replace(
        EXTENDS,
        relation=RelationKind.SUPERSEDES,
        target_type=EntityType.NOTIFICATION,
        target_name="01/2026-central tax",
        target_clause_ref="en.p1",
        target_span_start=0,
        target_span_end=38,
        evidence_clause_ref="en.p1",
        evidence_quote="NOTIFICATION No. 01/2026",
        rule_key=None,
        period_label=None,
        new_due_on=None,
    )
    other = replace(supersedes, evidence_clause_ref="en.p3", evidence_quote="hereby extends it")
    third = replace(supersedes, target_name="02/2026-central tax")
    one, two, three = (
        StageRelationCandidates(factory)
        .run(DOC, RelationSubmission("p@1", "m", "ok", (supersedes, other, third)))
        .candidate_ids
    )
    ApproveRelationCandidate(factory, clock).run(one, first, second, decided_by="a")
    with pytest.raises(SupersessionCycleError):
        ApproveRelationCandidate(factory, clock).run(two, second, first, decided_by="a")
    rejected = RejectRelationCandidate(factory, clock).run(
        three, CandidateRejectReason.OUT_OF_SCOPE, decided_by="a"
    )
    assert rejected.status is CandidateStatus.REJECTED


def test_decisions_must_be_complete_in_the_table(
    factory: PostgresKnowledgeUnitOfWorkFactory,
) -> None:
    with factory.engine.begin() as connection:
        review_id: UUID = connection.execute(
            text("SELECT id FROM entity_review LIMIT 1")
        ).scalar_one()
    with (
        pytest.raises(IntegrityError, match="ck_entity_review_decision"),
        factory.engine.begin() as c,
    ):
        c.execute(
            text("UPDATE entity_review SET status = 'open', decided_at = now() WHERE id = :id"),
            {"id": review_id},
        )


def test_unqualified_mentions_and_late_alignment_on_postgres(
    factory: PostgresKnowledgeUnitOfWorkFactory,
) -> None:
    AlignMentions(factory).run(DOC, "grammar@1", [BARE])
    bare_target = replace(
        EXTENDS,
        relation=RelationKind.REFERS_TO,
        target_type=EntityType.SECTION,
        target_name="39",
        target_span_start=BARE.span_start,
        target_span_end=BARE.span_end,
        rule_key=None,
        period_label=None,
        new_due_on=None,
        evidence_quote="section 39 of the Central Goods",
    )
    (candidate_id,) = (
        StageRelationCandidates(factory)
        .run(DOC, RelationSubmission("p@1", "m", "ok", (bare_target,)))
        .candidate_ids
    )
    with factory() as uow:
        target, _ = uow.entities.create_or_get(EntityType.SECTION, "39@cgst-act")
        clause = clause_id_for(DOC, "en.p3")
        assert uow.mentions.add(
            clause,
            target,
            BARE.text,
            BARE.span_start,
            BARE.span_end,
            method="analyst",
            extractor="",
        )
        assert uow.mentions.entity_at(clause, BARE.span_start, EntityType.SECTION) == target
        assert uow.mentions.entity_at(clause, BARE.span_start, EntityType.FORM) is None
        assert (
            uow.candidates.set_target_entity_at(clause, BARE.span_start, EntityType.SECTION, target)
            == 1
        )
        uow.relations.lock_supersession()
    version = rule(factory, "late_rule", "draft")
    ApproveRelationCandidate(factory, clock).run(candidate_id, version, None, decided_by="a")
    with factory.engine.connect() as connection:
        to_ref: str = connection.execute(
            text("SELECT to_ref FROM rule_relation WHERE candidate_id = :id"), {"id": candidate_id}
        ).scalar_one()
    assert to_ref == "39@cgst-act"


def test_queue_stats_count_open_items_by_type_and_find_the_oldest(
    factory: PostgresKnowledgeUnitOfWorkFactory,
) -> None:
    before = ReadReviewQueueStats(factory).run()
    clause = clause_id_for(DOC, "en.p1")
    circulars = [
        EntityReviewItem(
            review_id=uuid4(),
            document_id=DOC,
            clause_id=clause,
            entity_type=EntityType.CIRCULAR,
            mention_text="NOTIFICATION",
            span_start=start,
            span_end=start + 1,
            proposed_name=f"c{start}",
            reason=ReviewReason.NO_MATCH,
            extractor="grammar@1",
        )
        for start in (0, 1)
    ]
    with factory() as uow:
        assert all(uow.reviews.enqueue(item) for item in circulars)
    long_ago = datetime(2020, 1, 1, tzinfo=UTC)
    with factory.engine.begin() as connection:
        connection.execute(
            text("UPDATE entity_review SET created_at = :at WHERE id = :id"),
            {"at": long_ago, "id": circulars[0].review_id},
        )

    stats = ReadReviewQueueStats(factory).run()
    others: dict[EntityType, int] = {
        t: n for t, n in before.by_type.items() if t is not EntityType.CIRCULAR
    }
    assert stats.by_type == {**others, EntityType.CIRCULAR: 2}
    assert stats.oldest_open_at == long_ago

    with factory() as uow:
        uow.reviews.save(
            circulars[0].reject(EntityRejectReason.OUT_OF_SCOPE, decided_by="analyst", at=NOW)
        )
    stats = ReadReviewQueueStats(factory).run()
    assert stats.by_type == {**others, EntityType.CIRCULAR: 1}
    assert stats.oldest_open_at is not None
    assert stats.oldest_open_at > long_ago, "a decided item no longer counts"
