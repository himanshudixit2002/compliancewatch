"""The embedding use case: feature check, route model, scrubbing, budgets, breaker, ledger.

One model per call and no fallback, because vectors from two models do not compare: the caller
stores ``model_served`` with every vector. There is no cache. As with completions, every call
that reaches a provider leaves a ledger row, a refusal before that does not, and tracing and
event publishing never fail a call.

The breaker is keyed by provider and model and shared with completions, so only an unavailable
provider counts against it. A refusal of the request or an answer the gateway cannot use
(``ProviderResponseError``, such as a model named in an override that serves no embeddings) does
not: otherwise a bad embeddings override would open the circuit for that model's completions.
"""

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from domain_kernel.events import utc_now
from domain_kernel.vectors import EMBEDDING_DIMS, Vector
from llm_gateway.application.metering import BudgetGuard, error_entry, require_ledger_bounds
from llm_gateway.domain.breaker import CircuitBreaker
from llm_gateway.domain.config import GatewayConfig
from llm_gateway.domain.embeddings import (
    EMBEDDING_LEDGER_REF,
    EmbeddingProvider,
    EmbeddingRequest,
    EmbeddingResult,
    require_vectors_for,
)
from llm_gateway.domain.errors import ProviderUnavailableError
from llm_gateway.domain.events import EventPublisher, LLMCallCompleted, correlation_id_from
from llm_gateway.domain.features import (
    CallKind,
    CallStatus,
    CostSource,
    Feature,
    parse_feature,
    require_kind,
)
from llm_gateway.domain.ledger import CostLedger, LedgerEntry
from llm_gateway.domain.pricing import cost_for
from llm_gateway.domain.routing import provider_for, require_model_id
from llm_gateway.domain.scrub import PII_KINDS, scrub
from llm_gateway.domain.tracing import CallRecord, Tracer

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EmbeddingOutcome:
    """The vectors, their ledger row and what was masked; the API reads the properties."""

    vectors: tuple[Vector, ...]
    entry: LedgerEntry
    pii_counts: Mapping[str, int]

    @property
    def dims(self) -> int:
        return EMBEDDING_DIMS

    @property
    def model_requested(self) -> str:
        return self.entry.model_requested

    @property
    def model_served(self) -> str:
        return self.entry.model_served

    @property
    def provider(self) -> str:
        return self.entry.provider

    @property
    def input_tokens(self) -> int:
        return self.entry.input_tokens

    @property
    def cost_usd(self) -> Decimal | None:
        return self.entry.cost_usd

    @property
    def cost_inr(self) -> Decimal:
        return self.entry.cost_inr

    @property
    def cost_source(self) -> CostSource:
        return self.entry.cost_source

    @property
    def latency_ms(self) -> int:
        return self.entry.latency_ms

    @property
    def trace_id(self) -> str:
        return self.entry.trace_id

    @property
    def generation_id(self) -> str:
        return self.entry.generation_id


@dataclass(frozen=True, slots=True)
class _Call:
    """What one ``run`` knows before the provider is called; shared with the error path."""

    req: EmbeddingRequest
    clean: EmbeddingRequest
    feature: Feature
    model: str
    pii_counts: Mapping[str, int]
    correlation_id: str
    started_at: datetime
    started: float


class Embed:
    """Embed a batch of texts. Sync; the API runs it in a threadpool."""

    def __init__(
        self,
        *,
        providers: Mapping[str, EmbeddingProvider],
        breaker: CircuitBreaker,
        budgets: BudgetGuard,
        ledger: CostLedger,
        tracer: Tracer,
        publisher: EventPublisher,
        config: GatewayConfig,
        clock: Callable[[], datetime] = utc_now,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._providers = providers
        self._breaker = breaker
        self._budgets = budgets
        self._ledger = ledger
        self._tracer = tracer
        self._publisher = publisher
        self._config = config
        self._clock = clock
        self._monotonic = monotonic

    def run(self, req: EmbeddingRequest, *, correlation_id: str) -> EmbeddingOutcome:
        """Serve ``req`` with the route's model, or the one the request names.

        A refusal before the provider is tried (unknown or completion feature, malformed or
        overlong model or correlation id, budget used up) leaves no ledger row; every error
        after that has written its row. A wrong vector count or length is a
        ``ProviderResponseError`` and no vector is returned.
        """
        feature = require_kind(parse_feature(req.feature), CallKind.EMBEDDING)
        route = self._config.routes[feature]
        model = route.primary if req.model is None else require_model_id(req.model, "model")
        require_ledger_bounds((model,), correlation_id)

        scrubbed = tuple(scrub(text) for text in req.inputs)
        pii_counts = {kind: sum(item.counts[kind] for item in scrubbed) for kind in PII_KINDS}
        clean = replace(req, inputs=tuple(item.text for item in scrubbed), model=model)

        call = _Call(
            req=req,
            clean=clean,
            feature=feature,
            model=model,
            pii_counts=pii_counts,
            correlation_id=correlation_id,
            started_at=self._clock(),
            started=self._monotonic(),
        )
        self._budgets.check(
            tenant_id=req.tenant_id,
            feature=feature,
            at=call.started_at,
            correlation_id=correlation_id,
        )

        result, provider_name = self._call_provider(call)
        latency_ms = self._elapsed_ms(call)
        cost = cost_for(
            model=result.model,
            input_tokens=result.input_tokens,
            output_tokens=0,
            gateway_cost_usd=result.cost_usd,
            cached=False,
            usd_inr=self._config.usd_inr,
            table=self._config.price_table,
        )
        entry_id = uuid4()
        entry = LedgerEntry(
            id=entry_id,
            occurred_at=call.started_at,
            tenant_id=req.tenant_id,
            feature=feature,
            prompt_name=EMBEDDING_LEDGER_REF.name,
            prompt_version=EMBEDDING_LEDGER_REF.version,
            model_requested=model,
            model_served=result.model,
            provider=result.provider or provider_name,
            input_tokens=result.input_tokens,
            output_tokens=0,
            cached=False,
            cost_usd=cost.usd,
            cost_inr=cost.inr,
            cost_source=cost.source,
            latency_ms=latency_ms,
            correlation_id=correlation_id,
            trace_id=str(entry_id),
            generation_id=result.generation_id,
            status=CallStatus.OK,
        )
        self._ledger.add(entry)
        self._record(call, entry, output=_summary(result), error_detail="")
        event = LLMCallCompleted(
            entry=entry,
            tenant_id=req.tenant_id,
            correlation_id=correlation_id_from(correlation_id),
        )
        try:
            self._publisher.publish(event)
        except Exception:
            log.exception("publishing %s failed", LLMCallCompleted.topic)
        return EmbeddingOutcome(vectors=result.vectors, entry=entry, pii_counts=pii_counts)

    def _call_provider(self, call: _Call) -> tuple[EmbeddingResult, str]:
        """The one attempt: breaker, provider, then the count and length of the vectors. Only
        ``ProviderUnavailableError`` counts as a breaker failure."""
        name = provider_for(call.model)
        breaker_key = (name, call.model)
        if not self._breaker.allows(breaker_key):
            error = ProviderUnavailableError(
                f"circuit open for {call.model}",
                retry_after_seconds=self._breaker.retry_after(breaker_key),
            )
            self._fail(call, error, provider=name)
            raise error
        provider = self._providers.get(name)
        if provider is None:
            error = ProviderUnavailableError(f"no provider registered for {name!r}")
            self._fail(call, error, provider=name)
            raise error
        try:
            result = require_vectors_for(provider.embed(call.clean), len(call.clean.inputs))
        except ProviderUnavailableError as exc:
            self._breaker.record_failure(breaker_key)
            self._fail(call, exc, provider=name)
            raise
        except Exception as exc:
            self._fail(call, exc, provider=name)
            raise
        self._breaker.record_success(breaker_key)
        return result, name

    def _elapsed_ms(self, call: _Call) -> int:
        return max(0, round((self._monotonic() - call.started) * 1000))

    def _fail(self, call: _Call, exc: Exception, *, provider: str) -> None:
        """Write the error row and trace it. The event is only for completed calls."""
        entry = error_entry(
            exc,
            occurred_at=call.started_at,
            tenant_id=call.req.tenant_id,
            feature=call.feature,
            ref=EMBEDDING_LEDGER_REF,
            model_requested=call.model,
            model_served=call.model,
            provider=provider,
            latency_ms=self._elapsed_ms(call),
            correlation_id=call.correlation_id,
        )
        self._ledger.add(entry)
        self._record(call, entry, output="", error_detail=str(exc))

    def _record(self, call: _Call, entry: LedgerEntry, *, output: str, error_detail: str) -> None:
        record = CallRecord(
            entry=entry,
            system="",
            user="\n\n".join(call.clean.inputs),
            output=output,
            pii_counts=call.pii_counts,
            temperature=0.0,
            max_tokens=None,
            has_schema=False,
            metadata=call.req.metadata,
            error_detail=error_detail,
            kind=CallKind.EMBEDDING,
        )
        try:
            self._tracer.record(record)
        except Exception:
            log.exception("tracing call %s failed", entry.trace_id)


def _summary(result: EmbeddingResult) -> str:
    """What the trace shows as the output: the shape, never the numbers."""
    return f"{len(result.vectors)} vectors of {EMBEDDING_DIMS} dimensions"
