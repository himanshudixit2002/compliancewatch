"""The read use cases on the Postgres unit of work: rule versions in force, citations, entities
and the clauses that mention them, relations, clauses. Needs Docker."""

import hashlib
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from testcontainers.community.postgres import PostgresContainer

from domain_kernel.documents import Clause, DocumentType, clause_id_for, document_id_for
from domain_kernel.ids import CanonicalEntityId, ClauseId, DocumentId, RuleVersionId, SourceId
from domain_kernel.knowledge import EntityRef, EntityType, RelationKind, RuleRelation
from domain_kernel.ontology import AttributeLevel
from domain_kernel.status import RuleVersionStatus
from rulebook.application.documents import RegisterDocument
from rulebook.application.graph import (
    ListEntityClauses,
    ListRelations,
    ReadClause,
    ReadEntity,
    ResolveEntity,
)
from rulebook.application.rule_versions import ListCitations, ListRulesInForce, ReadRuleVersion
from rulebook.domain.documents import StoredDocument
from rulebook.domain.errors import ClauseNotStoredError
from rulebook.domain.graph import RelationQuery, ResolutionStatus
from rulebook.domain.relations import RelationCandidate
from rulebook.domain.seed import SeedStatus
from rulebook.infrastructure.knowledge_repository import PostgresKnowledgeUnitOfWorkFactory

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "rulebook"
INSERT_GUARD = "tr_rule_version_insert_guard"
"""Admits only unpublished drafts. The fixture below inserts versions in any status, so it turns
the guard off for its own transaction; ``ALTER TABLE`` is transactional, so the guard is back on
for everyone else when that transaction commits."""
NOW = datetime(2026, 9, 28, 12, tzinfo=UTC)
TEXT = "hereby extends the due date for furnishing the return in FORM GSTR-3B for March, 2026"
OTHER = "Every registered person shall furnish a return in FORM GSTR-3B."


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
        yield factory
        factory.engine.dispose()


def register(
    factory: PostgresKnowledgeUnitOfWorkFactory, name: str, published_at: date | None, *texts: str
) -> DocumentId:
    digest = hashlib.sha256(name.encode()).hexdigest()
    document_id = document_id_for(digest)
    RegisterDocument(factory).run(
        StoredDocument(
            document_id=document_id,
            source_id=SourceId(UUID(int=7)),
            sha256=digest,
            regulator="CBIC",
            doc_type=DocumentType.NOTIFICATION,
            url=f"https://example.invalid/{name}.pdf",
            language="en",
            media_type="application/pdf",
            parser_version="pdf@1",
            fetched_at=NOW,
            external_ref=name,
            published_at=published_at,
        ),
        [Clause(f"en.p{index}", clause) for index, clause in enumerate(texts, 1)],
    )
    return document_id


def rule(factory: PostgresKnowledgeUnitOfWorkFactory, key: str, *, regulator: str = "CBIC") -> UUID:
    rule_id = uuid4()
    with factory.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO rule (id, rule_key, regulator, level)"
                " VALUES (:id, :key, :regulator, 'registration')"
            ),
            {"id": rule_id, "key": key, "regulator": regulator},
        )
    return rule_id


def version(
    factory: PostgresKnowledgeUnitOfWorkFactory,
    rule_id: UUID,
    number: int,
    status: str,
    effective_from: date,
    effective_to: date | None = None,
) -> RuleVersionId:
    version_id = uuid4()
    with factory.engine.begin() as connection:
        connection.execute(text(f"ALTER TABLE rule_version DISABLE TRIGGER {INSERT_GUARD}"))
        connection.execute(
            text(
                "INSERT INTO rule_version (id, rule_id, version, status, title, summary,"
                " specification, obligation_template, recurrence, effective_from, effective_to,"
                " source, todo)"
                " VALUES (:id, :rule, :number, :status, :title, 'summary',"
                ' \'{"all": []}\', \'{"title": "t"}\', NULL, :start, :end,'
                ' \'{"instrument": "i"}\', \'["question"]\')'
            ),
            {
                "id": version_id,
                "rule": rule_id,
                "number": number,
                "status": status,
                "title": f"version {number}",
                "start": effective_from,
                "end": effective_to,
            },
        )
        connection.execute(text(f"ALTER TABLE rule_version ENABLE TRIGGER {INSERT_GUARD}"))
    return RuleVersionId(version_id)


def test_versions_in_force_filter_order_and_page(
    factory: PostgresKnowledgeUnitOfWorkFactory,
) -> None:
    april, july = date(2026, 4, 1), date(2026, 7, 1)
    monthly = rule(factory, "rv_monthly")
    old = version(factory, monthly, 1, "superseded", april, july)
    new = version(factory, monthly, 2, "published", july)
    draft = version(factory, rule(factory, "rv_draft"), 1, "draft", april)
    version(factory, rule(factory, "rv_withdrawn"), 1, "withdrawn", april)
    state = version(factory, rule(factory, "rv_state", regulator="KA-CTD"), 1, "published", april)
    use_case = ListRulesInForce(factory)

    def keys(
        as_of: date,
        rule_key: str | None = None,
        regulator: str | None = None,
        after: str | None = None,
    ) -> list[tuple[str, int]]:
        found = use_case.run(as_of, rule_key=rule_key, regulator=regulator, after=after)
        return [(r.rule_key, r.version) for r in found]

    assert keys(date(2026, 3, 31)) == []
    assert keys(date(2026, 6, 30)) == [("rv_monthly", 1), ("rv_state", 1)]
    assert keys(july) == [("rv_monthly", 2), ("rv_state", 1)]
    assert keys(july, regulator="KA-CTD") == [("rv_state", 1)]
    assert keys(july, rule_key="rv_monthly") == [("rv_monthly", 2)]
    assert keys(july, after="rv_monthly") == [("rv_state", 1)]
    assert [r.rule_version_id for r in use_case.run(july, limit=1)] == [new]
    assert [r.rule_version_id for r in use_case.run(date(2026, 6, 30), limit=1)] == [old]

    record, citations = ReadRuleVersion(factory).run(draft)
    assert (record.status, record.seed_status, record.level) == (
        RuleVersionStatus.DRAFT,
        SeedStatus.NEEDS_REVIEW,
        AttributeLevel.REGISTRATION,
    )
    assert record.specification == {"all": []}
    assert record.source == {"instrument": "i"}
    assert record.todo == ("question",)
    assert (record.recurrence, record.published_at, citations) == (None, None, ())
    assert ReadRuleVersion(factory).run(state)[0].regulator == "KA-CTD"


def test_citations_come_in_clause_order(factory: PostgresKnowledgeUnitOfWorkFactory) -> None:
    document = register(factory, "citations", date(2026, 3, 28), "Preamble text", TEXT)
    cited = version(factory, rule(factory, "rv_cited"), 1, "draft", date(2026, 4, 1))
    second, first = uuid4(), uuid4()
    with factory.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO citation (id, rule_version_id, clause_id, quote, verified,"
                " match_score, verified_at) VALUES"
                " (:second, :version, :p2, 'extends the due date', true, 0.9, :now),"
                " (:first, :version, :p1, 'Preamble', false, NULL, NULL)"
            ),
            {
                "second": second,
                "first": first,
                "version": cited.value,
                "p1": clause_id_for(document, "en.p1").value,
                "p2": clause_id_for(document, "en.p2").value,
                "now": NOW,
            },
        )
    citations = ListCitations(factory).run(cited)
    assert [c.citation_id for c in citations] == [first, second]
    assert [c.clause_ref for c in citations] == ["en.p1", "en.p2"]
    assert (citations[1].verified, citations[1].match_score) == (True, 0.9)
    assert citations[1].verified_at == NOW
    assert citations[0].match_score is None
    assert {c.document_id for c in citations} == {document}


def mention(
    factory: PostgresKnowledgeUnitOfWorkFactory,
    clause_id: ClauseId,
    entity: CanonicalEntityId,
    found: str,
    start: int,
) -> None:
    with factory() as uow:
        uow.mentions.add(
            clause_id,
            entity,
            found,
            start,
            start + len(found),
            method="grammar",
            extractor="grammar@1",
        )


def test_entities_resolve_and_list_their_clauses(
    factory: PostgresKnowledgeUnitOfWorkFactory,
) -> None:
    older = register(factory, "older", date(2026, 1, 16), OTHER)
    newer = register(factory, "newer", date(2026, 3, 28), "Preamble", TEXT)
    undated = register(factory, "undated", None, OTHER)
    with factory() as uow:
        form, _ = uow.entities.create_or_get(EntityType.FORM, "GSTR-3B")
        uow.entities.add_alias(form, "GSTR-3B-M")
    resolved = ResolveEntity(factory).run(EntityType.FORM, "gstr 3b m")
    assert resolved.status is ResolutionStatus.RESOLVED
    assert resolved.entity is not None
    assert (resolved.entity.entity_id, resolved.entity.aliases) == (form, ("GSTR-3B-M",))
    assert ReadEntity(factory).run(form).canonical_name == "GSTR-3B"

    start = OTHER.index("FORM GSTR-3B")
    mention(factory, clause_id_for(older, "en.p1"), form, "GSTR-3B", start + 5)
    mention(factory, clause_id_for(older, "en.p1"), form, "FORM GSTR-3B", start)
    mention(factory, clause_id_for(newer, "en.p2"), form, "FORM GSTR-3B", TEXT.index("FORM"))
    mention(factory, clause_id_for(undated, "en.p1"), form, "FORM GSTR-3B", start)

    found = ListEntityClauses(factory).run(form)
    assert [(c.detail.document.document_id, c.detail.clause.clause_ref) for c in found] == [
        (newer, "en.p2"),
        (older, "en.p1"),
        (undated, "en.p1"),
    ]
    assert [span.text for span in found[1].mentions] == ["FORM GSTR-3B", "GSTR-3B"]
    assert found[0].detail.document.external_ref == "newer"
    dated = ListEntityClauses(factory).run(form, as_of=date(2026, 2, 1))
    assert [c.detail.document.document_id for c in dated] == [older]
    assert len(ListEntityClauses(factory).run(form, limit=1)) == 1


def test_relations_by_either_end(factory: PostgresKnowledgeUnitOfWorkFactory) -> None:
    document = register(factory, "relations", date(2026, 3, 28), TEXT)
    evidence = clause_id_for(document, "en.p1")
    april = date(2026, 4, 1)
    monthly = version(factory, rule(factory, "rel_monthly"), 1, "published", april)
    extension = version(factory, rule(factory, "rel_extension"), 1, "published", april)
    draft = version(factory, rule(factory, "rel_draft"), 1, "draft", april)
    candidate_id = uuid4()
    start = TEXT.index("FORM GSTR-3B")
    with factory() as uow:
        form, _ = uow.entities.create_or_get(EntityType.FORM, "GSTR-3B")
        uow.candidates.add(
            RelationCandidate(
                candidate_id=candidate_id,
                document_id=document,
                relation=RelationKind.EXTENDS_DEADLINE,
                target_type=EntityType.FORM,
                target_name="GSTR-3B",
                target_clause_id=evidence,
                target_span_start=start,
                target_span_end=start + 12,
                evidence_clause_id=evidence,
                evidence_quote="hereby extends the due date",
                quote_score=1.0,
                prompt_version="extraction.rule_relations@1",
                confidence=0.9,
                needs_review=False,
                period_label="2026-03",
                new_due_on=date(2026, 4, 21),
            )
        )
    ids = {name: uuid4() for name in ("extends", "refers", "drafted")}
    with factory() as uow:
        uow.relations.add(
            RuleRelation(extension, RelationKind.EXTENDS_DEADLINE, monthly, evidence),
            relation_id=ids["extends"],
            candidate_id=candidate_id,
        )
        uow.relations.add(
            RuleRelation(
                extension,
                RelationKind.REFERS_TO,
                EntityRef(EntityType.FORM, "GSTR-3B", form),
                evidence,
            ),
            relation_id=ids["refers"],
            candidate_id=None,
        )
        uow.relations.add(
            RuleRelation(draft, RelationKind.SUPERSEDES, monthly, evidence),
            relation_id=ids["drafted"],
            candidate_id=None,
        )
    find = ListRelations(factory)
    (extends,) = find.run(RelationQuery(to_rule_version_id=monthly))
    assert extends.relation_id == ids["extends"]
    assert (extends.period_label, extends.new_due_on) == ("2026-03", date(2026, 4, 21))
    assert (extends.evidence_clause_ref, extends.evidence_document_id) == ("en.p1", document)
    assert (extends.to_rule_version_id, extends.to_entity_id) == (monthly, None)
    everything = find.run(RelationQuery(to_rule_version_id=monthly, published_only=False))
    assert {r.relation_id for r in everything} == {ids["extends"], ids["drafted"]}
    outgoing = find.run(RelationQuery(from_rule_version_id=extension))
    assert [r.relation_id for r in outgoing] == sorted([ids["extends"], ids["refers"]])
    typed = find.run(RelationQuery(from_rule_version_id=extension, relation=RelationKind.REFERS_TO))
    assert [r.relation_id for r in typed] == [ids["refers"]]
    (to_form,) = find.run(RelationQuery(to_entity_id=form))
    assert (to_form.to_kind, to_form.to_ref, to_form.to_entity_id) == ("form", "GSTR-3B", form)
    assert to_form.candidate_id is None
    assert len(find.run(RelationQuery(from_rule_version_id=extension, limit=1))) == 1


def test_a_clause_reads_with_its_document(factory: PostgresKnowledgeUnitOfWorkFactory) -> None:
    document = register(factory, "clause", date(2026, 3, 28), "Preamble", TEXT)
    detail = ReadClause(factory).run(clause_id_for(document, "en.p2"))
    assert (detail.clause.ordinal, detail.clause.text) == (2, TEXT)
    assert (detail.document.document_id, detail.document.external_ref) == (document, "clause")
    with pytest.raises(ClauseNotStoredError):
        ReadClause(factory).run(clause_id_for(document, "en.p7"))
