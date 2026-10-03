"""The Postgres unit of work: one transaction with the tenant setting for row-level security,
the decision repository on it and the outbox writer as the event sink, so a decision commits or
rolls back with its ``applicability.decided`` row."""

from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC
from typing import Any, Self

from sqlalchemy import Connection, Engine, create_engine, select, text, tuple_
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from applicability_engine.domain.model import Decision, DecisionKey, Trigger
from applicability_engine.domain.repository import UnitOfWork
from applicability_engine.infrastructure.models import TENANT_SETTING, DecisionRow
from domain_kernel.confidence import Confidence
from domain_kernel.events import DomainEvent
from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import BusinessId, DecisionId, RuleVersionId, TenantId
from domain_kernel.predicates import (
    Applicability,
    Predicate,
    PredicateResult,
    specification_from_mapping,
    specification_to_mapping,
)
from py_common.outbox import OutboxWriter


class SqlAlchemyDecisionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, decision: Decision) -> None:
        self._session.add(_to_row(decision))
        self._session.flush()

    def get(self, decision_id: DecisionId) -> Decision | None:
        row = self._session.get(DecisionRow, decision_id.value)
        return None if row is None else _to_decision(row)

    def list_for_business(
        self,
        business_id: BusinessId,
        *,
        rule_version_id: RuleVersionId | None,
        after: DecisionKey | None,
        limit: int,
    ) -> Sequence[Decision]:
        statement = (
            select(DecisionRow)
            .where(DecisionRow.business_id == business_id.value)
            .order_by(DecisionRow.decided_at.desc(), DecisionRow.id.desc())
            .limit(limit)
        )
        if rule_version_id is not None:
            statement = statement.where(DecisionRow.rule_version_id == rule_version_id.value)
        if after is not None:
            statement = statement.where(
                tuple_(DecisionRow.decided_at, DecisionRow.id)
                < tuple_(after.decided_at, after.decision_id.value)
            )
        return [_to_decision(row) for row in self._session.scalars(statement).all()]


class OutboxSink:
    def __init__(self, connection: Connection, writer: OutboxWriter) -> None:
        self._connection = connection
        self._writer = writer

    def publish(self, event: DomainEvent) -> None:
        self._writer.write(self._connection, event)


class SqlAlchemyUnitOfWork:
    def __init__(self, session: Session, tenant_id: TenantId, writer: OutboxWriter) -> None:
        connection = session.connection()
        connection.execute(
            text("SELECT set_config(:name, :value, true)"),
            {"name": TENANT_SETTING, "value": str(tenant_id)},
        )
        self.decisions = SqlAlchemyDecisionRepository(session)
        self.events = OutboxSink(connection, writer)


class PostgresUnitOfWorkFactory:
    """``factory(tenant_id)`` opens a transaction with ``app.tenant_id`` set for its duration."""

    def __init__(self, engine: Engine, *, writer: OutboxWriter | None = None) -> None:
        self._engine = engine
        self._writer = writer or OutboxWriter()

    @classmethod
    def from_url(cls, database_url: str) -> Self:
        return cls(create_engine(database_url, poolclass=NullPool))

    @property
    def engine(self) -> Engine:
        """The engine the units of work run on; the idempotency store shares it."""
        return self._engine

    def __call__(self, tenant_id: TenantId) -> AbstractContextManager[UnitOfWork]:
        return self._open(tenant_id)

    @contextmanager
    def _open(self, tenant_id: TenantId) -> Iterator[UnitOfWork]:
        with Session(self._engine, expire_on_commit=False) as session, session.begin():
            yield SqlAlchemyUnitOfWork(session, tenant_id, self._writer)

    def ping(self) -> bool:
        with self._engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True


def evaluated_to_json(evaluated: Sequence[PredicateResult]) -> list[dict[str, Any]]:
    """The predicate results as the ``evaluated`` column stores them: each predicate in the
    kernel's specification mapping, with its outcome, confidence and reason."""
    return [
        {
            "predicate": specification_to_mapping(item.predicate),
            "outcome": item.outcome.value,
            "confidence": item.confidence.value,
            "reason": item.reason,
        }
        for item in evaluated
    ]


def evaluated_from_json(items: Sequence[Mapping[str, Any]]) -> tuple[PredicateResult, ...]:
    results: list[PredicateResult] = []
    for item in items:
        predicate = specification_from_mapping(item["predicate"])
        if not isinstance(predicate, Predicate):
            raise ValueError(f"an evaluated entry holds a {type(predicate).__name__}")
        results.append(
            PredicateResult(
                predicate,
                Applicability(item["outcome"]),
                Confidence(float(item["confidence"])),
                str(item["reason"]),
            )
        )
    return tuple(results)


def _to_row(decision: Decision) -> DecisionRow:
    return DecisionRow(
        id=decision.decision_id.value,
        tenant_id=decision.tenant_id.value,
        business_id=decision.business_id.value,
        rule_version_id=decision.rule_version_id.value,
        result=decision.result.value,
        confidence=decision.confidence.value,
        profile_version=decision.profile_version,
        as_of_fy=None if decision.as_of_fy is None else decision.as_of_fy.label,
        trigger=decision.trigger.value,
        evaluated=evaluated_to_json(decision.evaluated),
        decided_at=decision.decided_at,
    )


def _to_decision(row: DecisionRow) -> Decision:
    return Decision(
        decision_id=DecisionId(row.id),
        tenant_id=TenantId(row.tenant_id),
        business_id=BusinessId(row.business_id),
        rule_version_id=RuleVersionId(row.rule_version_id),
        result=Applicability(row.result),
        confidence=Confidence(row.confidence),
        evaluated=evaluated_from_json(row.evaluated),
        profile_version=row.profile_version,
        decided_at=row.decided_at.astimezone(UTC),
        trigger=Trigger(row.trigger),
        as_of_fy=None if row.as_of_fy is None else FinancialYear.parse(row.as_of_fy),
    )
