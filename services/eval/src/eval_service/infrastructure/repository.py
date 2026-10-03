"""The Postgres unit of work: one transaction with the run repository on it and the outbox writer
as the event sink, so a run commits or rolls back with its ``eval.run.completed`` row."""

from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC
from typing import Self

from sqlalchemy import Connection, Engine, create_engine, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from domain_kernel.events import DomainEvent
from eval_service.domain.model import (
    EvalRun,
    EvalRunId,
    GateMeasurement,
    GateResult,
    Profile,
    Suite,
)
from eval_service.domain.repository import UnitOfWork
from eval_service.infrastructure.models import EvalGateRow, EvalRunRow
from py_common.outbox import OutboxWriter


class SqlAlchemyEvalRunRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, run: EvalRun) -> None:
        self._session.add(_to_row(run))
        self._session.flush()

    def get(self, run_id: EvalRunId) -> EvalRun | None:
        row = self._session.get(EvalRunRow, run_id.value)
        return None if row is None else _to_run(row)

    def latest(self, suite: Suite, profile: Profile) -> EvalRun | None:
        found = self.recent(suite=suite, profile=profile, limit=1)
        return found[0] if found else None

    def recent(
        self, *, suite: Suite | None, profile: Profile | None, limit: int
    ) -> Sequence[EvalRun]:
        statement = (
            select(EvalRunRow)
            .order_by(EvalRunRow.started_at.desc(), EvalRunRow.id.desc())
            .limit(limit)
        )
        if suite is not None:
            statement = statement.where(EvalRunRow.suite == suite.value)
        if profile is not None:
            statement = statement.where(EvalRunRow.profile == profile.value)
        return [_to_run(row) for row in self._session.scalars(statement).all()]


class OutboxSink:
    def __init__(self, connection: Connection, writer: OutboxWriter) -> None:
        self._connection = connection
        self._writer = writer

    def publish(self, event: DomainEvent) -> None:
        self._writer.write(self._connection, event)


class SqlAlchemyUnitOfWork:
    def __init__(self, session: Session, writer: OutboxWriter) -> None:
        self.runs = SqlAlchemyEvalRunRepository(session)
        self.events = OutboxSink(session.connection(), writer)


class PostgresUnitOfWorkFactory:
    """``factory()`` opens one transaction; there is no tenant setting, eval runs are global."""

    def __init__(self, engine: Engine, *, writer: OutboxWriter | None = None) -> None:
        self._engine = engine
        self._writer = writer or OutboxWriter()

    @classmethod
    def from_url(cls, database_url: str) -> Self:
        return cls(create_engine(database_url, poolclass=NullPool))

    def __call__(self) -> AbstractContextManager[UnitOfWork]:
        return self._open()

    @contextmanager
    def _open(self) -> Iterator[UnitOfWork]:
        with Session(self._engine, expire_on_commit=False) as session, session.begin():
            yield SqlAlchemyUnitOfWork(session, self._writer)

    def ping(self) -> bool:
        with self._engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True


def _to_row(run: EvalRun) -> EvalRunRow:
    return EvalRunRow(
        id=run.id.value,
        suite=run.suite.value,
        profile=run.profile.value,
        started_at=run.started_at,
        completed_at=run.completed_at,
        previous_run_id=None if run.previous_run_id is None else run.previous_run_id.value,
        gates=[
            EvalGateRow(
                run_id=run.id.value,
                position=position,
                name=gate.name,
                metric=gate.measurement.metric,
                threshold=gate.measurement.threshold,
                value=gate.measurement.value,
                passed=gate.passed,
                previous_value=gate.previous_value,
            )
            for position, gate in enumerate(run.gates)
        ],
    )


def _to_run(row: EvalRunRow) -> EvalRun:
    return EvalRun(
        id=EvalRunId(row.id),
        suite=Suite(row.suite),
        profile=Profile(row.profile),
        started_at=row.started_at.astimezone(UTC),
        completed_at=row.completed_at.astimezone(UTC),
        gates=tuple(
            GateResult(
                GateMeasurement(
                    name=gate.name,
                    metric=gate.metric,
                    threshold=gate.threshold,
                    value=gate.value,
                    passed=gate.passed,
                ),
                gate.previous_value,
            )
            for gate in row.gates
        ),
        previous_run_id=None if row.previous_run_id is None else EvalRunId(row.previous_run_id),
    )
