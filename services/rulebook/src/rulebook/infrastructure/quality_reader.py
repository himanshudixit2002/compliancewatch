"""Read the facts the data-quality checks need, in one read-only transaction.

Two queries: every rule version with its rule key, its citation counts and the number of open
analyst questions in its ``todo`` list, and every relation from a rule version to another rule
version. The connection is read-only (``postgresql_readonly``), so the reader writes nothing
even with a role that could; the nightly job can point it at a deployed database through a
read-only role. ``schema`` sets the transaction's ``search_path`` for a URL that does not carry
one.
"""

from uuid import UUID

from sqlalchemy import Engine, create_engine, func, select, text
from sqlalchemy.pool import NullPool

from domain_kernel.ids import RuleVersionId
from domain_kernel.knowledge import RelationKind
from domain_kernel.status import RuleVersionStatus
from rulebook.domain.quality import QualityFacts, RelationFacts, VersionFacts
from rulebook.infrastructure.models import CitationRow, RuleRelationRow, RuleRow, RuleVersionRow


class SqlQualityReader:
    def __init__(self, engine: Engine, *, schema: str | None = None) -> None:
        self._engine = engine
        self._schema = schema

    @classmethod
    def from_url(cls, database_url: str, *, schema: str | None = None) -> "SqlQualityReader":
        return cls(create_engine(database_url, poolclass=NullPool), schema=schema)

    def read(self) -> QualityFacts:
        citations = func.count(CitationRow.id)
        verified = func.count(CitationRow.id).filter(CitationRow.verified)
        versions = (
            select(
                RuleVersionRow.id,
                RuleRow.rule_key,
                RuleVersionRow.version,
                RuleVersionRow.status,
                RuleVersionRow.effective_from,
                RuleVersionRow.effective_to,
                RuleVersionRow.specification,
                citations,
                verified,
                func.jsonb_array_length(RuleVersionRow.todo),
            )
            .join(RuleRow, RuleRow.id == RuleVersionRow.rule_id)
            .outerjoin(CitationRow, CitationRow.rule_version_id == RuleVersionRow.id)
            .group_by(RuleVersionRow.id, RuleRow.rule_key)
            .order_by(RuleRow.rule_key, RuleVersionRow.version)
        )
        relations = (
            select(
                RuleRelationRow.from_rule_version_id,
                RuleRelationRow.relation,
                RuleRelationRow.to_rule_version_id,
            )
            .where(RuleRelationRow.to_rule_version_id.is_not(None))
            .order_by(RuleRelationRow.from_rule_version_id, RuleRelationRow.id)
        )
        with (
            self._engine.connect().execution_options(postgresql_readonly=True) as connection,
            connection.begin(),
        ):
            if self._schema:
                connection.execute(
                    text("SELECT set_config('search_path', :path, true)"),
                    {"path": f"{self._schema}, public"},
                )
            version_rows = connection.execute(versions).all()
            relation_rows = connection.execute(relations).all()
        return QualityFacts(
            versions=tuple(
                VersionFacts(
                    rule_version_id=RuleVersionId(row[0]),
                    rule_key=row[1],
                    version=row[2],
                    status=RuleVersionStatus(row[3]),
                    effective_from=row[4],
                    effective_to=row[5],
                    specification=row[6],
                    citations=row[7],
                    verified_citations=row[8],
                    open_questions=row[9],
                )
                for row in version_rows
            ),
            relations=tuple(
                RelationFacts(
                    from_rule_version_id=RuleVersionId(row[0]),
                    relation=RelationKind(row[1]),
                    to_rule_version_id=RuleVersionId(_required(row[2])),
                )
                for row in relation_rows
            ),
        )


def _required(value: UUID | None) -> UUID:
    if value is None:  # pragma: no cover - the query selects rows where it is set
        raise ValueError("to_rule_version_id is missing")
    return value
