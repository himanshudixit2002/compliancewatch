"""The cost ledger in Postgres through SQLAlchemy: the durable ledger that budgets read from."""

from collections.abc import Sequence
from datetime import UTC, date
from decimal import Decimal
from typing import Self

from sqlalchemy import Engine, create_engine, func, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from domain_kernel._validation import require_int
from domain_kernel.ids import TenantId
from llm_gateway.domain.budgets import month_bounds
from llm_gateway.domain.features import CallStatus, CostSource, Feature
from llm_gateway.domain.ledger import LedgerEntry
from llm_gateway.domain.pricing import quantize_inr, quantize_usd
from llm_gateway.infrastructure.ledger.models import CostLedgerRow


class SqlAlchemyLedger:
    """Each method is one short transaction; the API's threadpool calls them concurrently."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @classmethod
    def from_url(cls, database_url: str) -> Self:
        """A ledger over a new engine without a pool: a connection per call, none held idle."""
        return cls(create_engine(database_url, poolclass=NullPool))

    @property
    def engine(self) -> Engine:
        return self._engine

    def add(self, entry: LedgerEntry) -> None:
        with Session(self._engine) as session, session.begin():
            session.add(_to_row(entry))

    def spent_inr(
        self, *, tenant_id: TenantId | None, feature: Feature | None, month: date
    ) -> Decimal:
        start, end = month_bounds(month)
        statement = select(func.coalesce(func.sum(CostLedgerRow.cost_inr), 0)).where(
            CostLedgerRow.occurred_at >= start, CostLedgerRow.occurred_at < end
        )
        if tenant_id is not None:
            statement = statement.where(CostLedgerRow.tenant_id == tenant_id.value)
        if feature is not None:
            statement = statement.where(CostLedgerRow.feature == feature.value)
        with self._engine.connect() as connection:
            total = connection.scalar(statement)
        return quantize_inr(Decimal(str(0 if total is None else total)))

    def recent(self, limit: int) -> Sequence[LedgerEntry]:
        require_int(limit, "limit", minimum=0)
        statement = select(CostLedgerRow).order_by(CostLedgerRow.occurred_at.desc()).limit(limit)
        with Session(self._engine) as session:
            rows = session.scalars(statement).all()
        return tuple(_to_entry(row) for row in rows)

    def ping(self) -> bool:
        """``SELECT 1``; raises when the database is unreachable, which the readiness probe logs."""
        with self._engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True


def _to_row(entry: LedgerEntry) -> CostLedgerRow:
    return CostLedgerRow(
        id=entry.id,
        occurred_at=entry.occurred_at,
        tenant_id=None if entry.tenant_id is None else entry.tenant_id.value,
        feature=entry.feature.value,
        prompt_name=entry.prompt_name,
        prompt_version=entry.prompt_version,
        model_requested=entry.model_requested,
        model_served=entry.model_served,
        provider=entry.provider,
        input_tokens=entry.input_tokens,
        output_tokens=entry.output_tokens,
        cached=entry.cached,
        cost_usd=entry.cost_usd,
        cost_inr=entry.cost_inr,
        cost_source=entry.cost_source.value,
        latency_ms=entry.latency_ms,
        correlation_id=entry.correlation_id,
        trace_id=entry.trace_id,
        generation_id=entry.generation_id,
        status=entry.status.value,
        error_type=entry.error_type,
    )


def _to_entry(row: CostLedgerRow) -> LedgerEntry:
    return LedgerEntry(
        id=row.id,
        occurred_at=row.occurred_at.astimezone(UTC),
        tenant_id=None if row.tenant_id is None else TenantId(row.tenant_id),
        feature=Feature(row.feature),
        prompt_name=row.prompt_name,
        prompt_version=row.prompt_version,
        model_requested=row.model_requested,
        model_served=row.model_served,
        provider=row.provider,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        cached=row.cached,
        cost_usd=None if row.cost_usd is None else quantize_usd(Decimal(str(row.cost_usd))),
        cost_inr=quantize_inr(Decimal(str(row.cost_inr))),
        cost_source=CostSource(row.cost_source),
        latency_ms=row.latency_ms,
        correlation_id=row.correlation_id,
        trace_id=row.trace_id,
        generation_id=row.generation_id,
        status=CallStatus(row.status),
        error_type=row.error_type,
    )
