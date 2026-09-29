"""The completion use case: registry, routing, scrubbing, budgets, cache, provider, ledger.

Every call that reaches a provider leaves a ledger row, successful or not; a call refused
before that (unknown prompt, a model id or correlation id the ledger cannot store, budget used
up) does not. Tracing and event publishing never fail a call; a ledger write that fails does,
because the ledger is what budgets are read from.
"""

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from domain_kernel.events import utc_now
from domain_kernel.llm import CompletionRequest, CompletionResponse
from domain_kernel.protocols import LLMProvider
from llm_gateway.application.metering import BudgetGuard, error_entry, require_ledger_bounds
from llm_gateway.domain.breaker import CircuitBreaker
from llm_gateway.domain.cache import ResponseCache, cache_key, is_cacheable
from llm_gateway.domain.config import GatewayConfig
from llm_gateway.domain.errors import (
    ProviderResponseError,
    ProviderUnavailableError,
    UnknownPromptError,
)
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
from llm_gateway.domain.pricing import Cost, cost_for
from llm_gateway.domain.prompts import PromptRef, PromptRegistry
from llm_gateway.domain.providers import ProviderResponse
from llm_gateway.domain.routing import provider_for, require_model_id
from llm_gateway.domain.scrub import scrub
from llm_gateway.domain.tracing import CallRecord, Tracer

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CompletionOutcome:
    """The response, its ledger row and what was masked; the API reads the properties."""

    response: CompletionResponse
    entry: LedgerEntry
    pii_counts: Mapping[str, int]

    @property
    def text(self) -> str:
        return self.response.text

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
    def output_tokens(self) -> int:
        return self.entry.output_tokens

    @property
    def cached(self) -> bool:
        return self.entry.cached

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
    """What one ``run`` knows before a provider is called; shared with the error path."""

    req: CompletionRequest
    clean: CompletionRequest
    feature: Feature
    ref: PromptRef
    model_requested: str
    pii_counts: Mapping[str, int]
    correlation_id: str
    started_at: datetime
    started: float


class Complete:
    """Run one completion. Sync; the API runs it in a threadpool."""

    def __init__(
        self,
        *,
        registry: PromptRegistry,
        providers: Mapping[str, LLMProvider],
        breaker: CircuitBreaker,
        budgets: BudgetGuard,
        cache: ResponseCache | None,
        ledger: CostLedger,
        tracer: Tracer,
        publisher: EventPublisher,
        config: GatewayConfig,
        clock: Callable[[], datetime] = utc_now,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._registry = registry
        self._providers = providers
        self._breaker = breaker
        self._budgets = budgets
        self._cache = cache
        self._ledger = ledger
        self._tracer = tracer
        self._publisher = publisher
        self._config = config
        self._clock = clock
        self._monotonic = monotonic

    def run(self, req: CompletionRequest, *, correlation_id: str) -> CompletionOutcome:
        """Serve ``req``.

        A refusal before any provider is tried (unknown feature or prompt, an embedding feature,
        malformed or overlong model or correlation id, budget used up) leaves no ledger row; every
        error after that has written its row.
        """
        feature = require_kind(parse_feature(req.feature), CallKind.COMPLETION)
        ref = PromptRef.parse(req.prompt_version)
        if self._registry.get(ref.name, ref.version) is None and (
            not self._config.allow_unregistered_prompts
        ):
            raise UnknownPromptError(str(ref))

        route = self._config.routes[feature]
        candidates = route.models if req.model is None else (require_model_id(req.model, "model"),)
        require_ledger_bounds(candidates, correlation_id)

        system = scrub(req.system)
        user = scrub(req.user)
        pii_counts = {kind: system.counts[kind] + user.counts[kind] for kind in system.counts}
        clean = replace(req, system=system.text, user=user.text)

        call = _Call(
            req=req,
            clean=clean,
            feature=feature,
            ref=ref,
            model_requested=candidates[0],
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

        key = cache_key(
            model=call.model_requested,
            prompt=str(ref),
            system=clean.system,
            user=clean.user,
            json_schema=clean.json_schema,
            temperature=clean.temperature,
            max_tokens=clean.max_tokens,
        )
        cacheable = self._cache is not None and is_cacheable(clean)
        hit = self._cache.get(key) if cacheable and self._cache is not None else None
        if hit is not None:
            entry_id = uuid4()
            entry = self._entry(
                call,
                entry_id=entry_id,
                served=hit,
                cost=cost_for(
                    model=hit.model,
                    input_tokens=hit.input_tokens,
                    output_tokens=hit.output_tokens,
                    gateway_cost_usd=hit.cost_usd,
                    cached=True,
                    usd_inr=self._config.usd_inr,
                    table=self._config.price_table,
                ),
                cached=True,
                latency_ms=0,
            )
            response = replace(hit, cached=True, trace_id=str(entry_id))
            return self._finish(call, entry, response)

        served, provider_name, latency_ms = self._call_provider(call, candidates)
        cost = cost_for(
            model=served.model,
            input_tokens=served.input_tokens,
            output_tokens=served.output_tokens,
            gateway_cost_usd=served.cost_usd,
            cached=False,
            usd_inr=self._config.usd_inr,
            table=self._config.price_table,
        )
        if not served.provider:
            served = replace(served, provider=provider_name)
        entry_id = uuid4()
        entry = self._entry(
            call, entry_id=entry_id, served=served, cost=cost, cached=False, latency_ms=latency_ms
        )
        if cacheable and self._cache is not None:
            if served.model == call.model_requested:
                self._cache.put(key, served)
            else:
                # A fallback's answer is not what a later call for the primary asked for. Logged
                # so a gateway that renames models cannot leave the cache silently empty.
                log.info(
                    "llm.cache.skipped",
                    extra={"requested": call.model_requested, "served": served.model},
                )
        return self._finish(call, entry, replace(served, trace_id=str(entry_id)))

    def _call_provider(
        self, call: _Call, candidates: tuple[str, ...]
    ) -> tuple[ProviderResponse, str, int]:
        """Try each candidate in order; returns the response, provider name and latency.

        Latency runs from the start of ``run``, so a fallback's row includes the failed attempt.
        """
        last_error: Exception = ProviderUnavailableError("no model candidates")
        attempted, attempted_provider = candidates[0], provider_for(candidates[0])
        for model in candidates:
            name = provider_for(model)
            attempted, attempted_provider = model, name
            breaker_key = (name, model)
            if not self._breaker.allows(breaker_key):
                last_error = ProviderUnavailableError(
                    f"circuit open for {model}",
                    retry_after_seconds=self._breaker.retry_after(breaker_key),
                )
                continue
            provider = self._providers.get(name)
            if provider is None:
                error = ProviderUnavailableError(f"no provider registered for {name!r}")
                self._fail(call, error, model=model, provider=name)
                raise error
            try:
                response = provider.complete(replace(call.clean, model=model))
            except ProviderUnavailableError as exc:
                self._breaker.record_failure(breaker_key)
                last_error = exc
                continue
            except ProviderResponseError as exc:
                self._breaker.record_failure(breaker_key)
                self._fail(call, exc, model=model, provider=name)
                raise
            except Exception as exc:
                self._fail(call, exc, model=model, provider=name)
                raise
            self._breaker.record_success(breaker_key)
            return _as_provider_response(response, name), name, self._elapsed_ms(call)
        self._fail(call, last_error, model=attempted, provider=attempted_provider)
        raise last_error

    def _elapsed_ms(self, call: _Call) -> int:
        return max(0, round((self._monotonic() - call.started) * 1000))

    def _entry(
        self,
        call: _Call,
        *,
        entry_id: UUID,
        served: ProviderResponse,
        cost: Cost,
        cached: bool,
        latency_ms: int,
    ) -> LedgerEntry:
        return LedgerEntry(
            id=entry_id,
            occurred_at=call.started_at,
            tenant_id=call.req.tenant_id,
            feature=call.feature,
            prompt_name=call.ref.name,
            prompt_version=call.ref.version,
            model_requested=call.model_requested,
            model_served=served.model,
            provider=served.provider,
            input_tokens=served.input_tokens,
            output_tokens=served.output_tokens,
            cached=cached,
            cost_usd=cost.usd,
            cost_inr=cost.inr,
            cost_source=cost.source,
            latency_ms=latency_ms,
            correlation_id=call.correlation_id,
            trace_id=str(entry_id),
            generation_id=served.generation_id,
            status=CallStatus.OK,
        )

    def _finish(
        self, call: _Call, entry: LedgerEntry, response: CompletionResponse
    ) -> CompletionOutcome:
        self._ledger.add(entry)
        self._record(call, entry, output=response.text, error_detail="")
        event = LLMCallCompleted(
            entry=entry,
            tenant_id=call.req.tenant_id,
            correlation_id=correlation_id_from(call.correlation_id),
        )
        try:
            self._publisher.publish(event)
        except Exception:
            log.exception("publishing %s failed", LLMCallCompleted.topic)
        return CompletionOutcome(response=response, entry=entry, pii_counts=call.pii_counts)

    def _fail(self, call: _Call, exc: Exception, *, model: str, provider: str) -> None:
        """Write the error row and trace it. The event is only for completed calls."""
        entry = error_entry(
            exc,
            occurred_at=call.started_at,
            tenant_id=call.req.tenant_id,
            feature=call.feature,
            ref=call.ref,
            model_requested=call.model_requested,
            model_served=model,
            provider=provider,
            latency_ms=self._elapsed_ms(call),
            correlation_id=call.correlation_id,
        )
        self._ledger.add(entry)
        self._record(call, entry, output="", error_detail=str(exc))

    def _record(self, call: _Call, entry: LedgerEntry, *, output: str, error_detail: str) -> None:
        record = CallRecord(
            entry=entry,
            system=call.clean.system,
            user=call.clean.user,
            output=output,
            pii_counts=call.pii_counts,
            temperature=call.req.temperature,
            max_tokens=call.req.max_tokens,
            has_schema=call.req.json_schema is not None,
            metadata=call.req.metadata,
            error_detail=error_detail,
        )
        try:
            self._tracer.record(record)
        except Exception:
            log.exception("tracing call %s failed", entry.trace_id)


def _as_provider_response(response: CompletionResponse, provider: str) -> ProviderResponse:
    """Adapters return a ``ProviderResponse``; a plain kernel response is widened."""
    if isinstance(response, ProviderResponse):
        return response
    return ProviderResponse(
        text=response.text,
        model=response.model,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        cached=False,
        trace_id=response.trace_id,
        provider=provider,
    )
