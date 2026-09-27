"""SQLAlchemy mapping of the cost ledger. The migration under ``migrations/versions`` is the DDL.

The table name is unqualified: the connection's ``search_path`` (``llm_gateway,public`` in the
service URL) selects the schema, and ``migrations/env.py`` keeps ``alembic_version`` there too.
"""

import uuid
from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from llm_gateway.domain.ledger import (
    MAX_CORRELATION_ID,
    MAX_ERROR_TYPE,
    MAX_GENERATION_ID,
    MAX_MODEL_ID,
    MAX_PROMPT_NAME,
    MAX_PROMPT_VERSION,
    MAX_PROVIDER,
    MAX_TRACE_ID,
)

TABLE_COMMENT = (
    "Usage metering for every LLM call. Row-level security is deliberately not applied: the cost "
    "dashboard reads this table across tenants and tenant_id is NULL for regulatory calls. The "
    "tenant RLS convention lands with the first customer-data table."
)


class Base(DeclarativeBase):
    """Declarative base of the llm-gateway models; ``migrations/env.py`` reads its metadata."""


class CostLedgerRow(Base):
    """One row per call; column lengths are the domain's ``MAX_*`` limits."""

    __tablename__ = "cost_ledger"
    __table_args__ = (
        sa.Index("ix_cost_ledger_tenant_month", "tenant_id", "occurred_at"),
        sa.Index("ix_cost_ledger_feature_month", "feature", "occurred_at"),
        {"comment": TABLE_COMMENT},
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid(), nullable=True)
    feature: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    prompt_name: Mapped[str] = mapped_column(sa.String(MAX_PROMPT_NAME), nullable=False)
    prompt_version: Mapped[str] = mapped_column(sa.String(MAX_PROMPT_VERSION), nullable=False)
    model_requested: Mapped[str] = mapped_column(sa.String(MAX_MODEL_ID), nullable=False)
    model_served: Mapped[str] = mapped_column(sa.String(MAX_MODEL_ID), nullable=False)
    provider: Mapped[str] = mapped_column(sa.String(MAX_PROVIDER), nullable=False)
    input_tokens: Mapped[int] = mapped_column(sa.Integer(), nullable=False)
    output_tokens: Mapped[int] = mapped_column(sa.Integer(), nullable=False)
    cached: Mapped[bool] = mapped_column(sa.Boolean(), nullable=False)
    cost_usd: Mapped[Decimal | None] = mapped_column(sa.Numeric(12, 6), nullable=True)
    cost_inr: Mapped[Decimal] = mapped_column(sa.Numeric(14, 4), nullable=False)
    cost_source: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    latency_ms: Mapped[int] = mapped_column(sa.Integer(), nullable=False)
    correlation_id: Mapped[str] = mapped_column(
        sa.String(MAX_CORRELATION_ID), nullable=False, server_default=""
    )
    trace_id: Mapped[str] = mapped_column(
        sa.String(MAX_TRACE_ID), nullable=False, server_default=""
    )
    generation_id: Mapped[str] = mapped_column(
        sa.String(MAX_GENERATION_ID), nullable=False, server_default=""
    )
    status: Mapped[str] = mapped_column(sa.String(8), nullable=False)
    error_type: Mapped[str] = mapped_column(
        sa.String(MAX_ERROR_TYPE), nullable=False, server_default=""
    )
