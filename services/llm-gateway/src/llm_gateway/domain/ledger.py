"""The cost ledger: one row per call, the source of truth for budgets and the cost dashboard."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from domain_kernel._validation import require_aware, require_bool, require_instance, require_int
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import TenantId
from llm_gateway.domain.features import CallStatus, CostSource, Feature
from llm_gateway.domain.pricing import require_decimal

MAX_PROMPT_NAME = 120
MAX_PROMPT_VERSION = 40
MAX_MODEL_ID = 120
MAX_PROVIDER = 60
MAX_CORRELATION_ID = 64
MAX_TRACE_ID = 120
MAX_GENERATION_ID = 120
MAX_ERROR_TYPE = 80


def require_bounded(value: object, name: str, max_length: int, *, required: bool = False) -> str:
    """Return ``value`` when it is a string the ledger column ``name`` can hold."""
    text = require_instance(value, str, name)
    if required and not text.strip():
        raise InvariantViolationError(f"{name} must not be blank")
    if len(text) > max_length:
        raise InvariantViolationError(f"{name} must be at most {max_length} characters")
    return text


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """One call as the ledger stores it. Lengths match the ``cost_ledger`` columns.

    ``tenant_id`` is None for regulatory calls that serve every tenant. ``trace_id`` is the
    entry id, so a trace and its row share a key. Error rows carry zero tokens and cost.
    """

    id: UUID
    occurred_at: datetime
    tenant_id: TenantId | None
    feature: Feature
    prompt_name: str
    prompt_version: str
    model_requested: str
    model_served: str
    provider: str
    input_tokens: int
    output_tokens: int
    cached: bool
    cost_usd: Decimal | None
    cost_inr: Decimal
    cost_source: CostSource
    latency_ms: int
    correlation_id: str
    trace_id: str
    generation_id: str
    status: CallStatus
    error_type: str = ""

    def __post_init__(self) -> None:
        require_instance(self.id, UUID, "id")
        require_aware(self.occurred_at, "occurred_at")
        if self.tenant_id is not None:
            require_instance(self.tenant_id, TenantId, "tenant_id")
        require_instance(self.feature, Feature, "feature")
        require_bounded(self.prompt_name, "prompt_name", MAX_PROMPT_NAME, required=True)
        require_bounded(self.prompt_version, "prompt_version", MAX_PROMPT_VERSION, required=True)
        require_bounded(self.model_requested, "model_requested", MAX_MODEL_ID, required=True)
        require_bounded(self.model_served, "model_served", MAX_MODEL_ID, required=True)
        require_bounded(self.provider, "provider", MAX_PROVIDER)
        require_int(self.input_tokens, "input_tokens", minimum=0)
        require_int(self.output_tokens, "output_tokens", minimum=0)
        require_bool(self.cached, "cached")
        if self.cost_usd is not None:
            require_decimal(self.cost_usd, "cost_usd", minimum=Decimal(0))
        require_decimal(self.cost_inr, "cost_inr", minimum=Decimal(0))
        require_instance(self.cost_source, CostSource, "cost_source")
        require_int(self.latency_ms, "latency_ms", minimum=0)
        require_bounded(self.correlation_id, "correlation_id", MAX_CORRELATION_ID)
        require_bounded(self.trace_id, "trace_id", MAX_TRACE_ID)
        require_bounded(self.generation_id, "generation_id", MAX_GENERATION_ID)
        require_instance(self.status, CallStatus, "status")
        require_bounded(self.error_type, "error_type", MAX_ERROR_TYPE)
        if (self.status is CallStatus.ERROR) != bool(self.error_type):
            raise InvariantViolationError("error_type is set exactly on error rows")


class CostLedger(Protocol):
    """Where entries go and how budgets read them back."""

    def add(self, entry: LedgerEntry) -> None: ...

    def spent_inr(
        self, *, tenant_id: TenantId | None, feature: Feature | None, month: date
    ) -> Decimal:
        """Rupees booked in ``month`` (first day, UTC); ``None`` on a filter means no filter."""
        ...

    def recent(self, limit: int) -> Sequence[LedgerEntry]:
        """The newest entries first."""
        ...
