"""The embedding use case against local stubs of every port; no infrastructure imported."""

import logging
import math
from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest

from domain_kernel.errors import InvariantViolationError
from domain_kernel.events import DomainEvent
from domain_kernel.ids import CorrelationId, TenantId
from domain_kernel.llm import CompletionRequest, CompletionResponse
from domain_kernel.vectors import EMBEDDING_DIMS
from llm_gateway.application.complete import Complete
from llm_gateway.application.embed import Embed, EmbeddingOutcome
from llm_gateway.application.metering import BudgetGuard
from llm_gateway.domain.breaker import BreakerState, CircuitBreaker
from llm_gateway.domain.budgets import BudgetLimits, BudgetScope, month_bounds
from llm_gateway.domain.config import GatewayConfig
from llm_gateway.domain.embeddings import EmbeddingRequest, EmbeddingResult
from llm_gateway.domain.errors import (
    BudgetExceededError,
    FeatureMismatchError,
    ProviderResponseError,
    ProviderUnavailableError,
    UnknownFeatureError,
)
from llm_gateway.domain.events import BudgetAlarmed, LLMCallCompleted
from llm_gateway.domain.features import CallKind, CallStatus, CostSource, Feature
from llm_gateway.domain.ledger import MAX_CORRELATION_ID, LedgerEntry
from llm_gateway.domain.prompts import PromptSpec
from llm_gateway.domain.routing import DEFAULT_ROUTES
from llm_gateway.domain.tracing import CallRecord

NOW = datetime(2026, 9, 27, 10, 0, tzinfo=UTC)
ROUTE_MODEL = DEFAULT_ROUTES[Feature.RETRIEVAL].primary
SERVED = "fake/hash-ngram-512"
CLAUSE = "x" * 4000
"""1,000 tokens: 0.0001 USD on the fake embedder at the table price, 0.0088 INR at 88."""
UNIT = (1.0,) + (0.0,) * (EMBEDDING_DIMS - 1)
NO_PII = {"gstin": 0, "pan": 0, "aadhaar": 0, "phone": 0, "email": 0}


# ---- stubs -----------------------------------------------------------------------------------


class Embedder:
    """A unit vector per input; failures and odd answers are injectable."""

    def __init__(self) -> None:
        self.calls = 0
        self.requests: list[EmbeddingRequest] = []
        self._failures = 0
        self._raise: Exception | None = None
        self.result: EmbeddingResult | None = None

    def fail_next(self, count: int = 1) -> None:
        self._failures = count

    def raise_next(self, exc: Exception) -> None:
        self._raise = exc

    def embed(self, req: EmbeddingRequest) -> EmbeddingResult:
        self.calls += 1
        self.requests.append(req)
        if self._raise is not None:
            exc, self._raise = self._raise, None
            raise exc
        if self._failures:
            self._failures -= 1
            raise ProviderUnavailableError("fake provider: injected failure")
        if self.result is not None:
            return self.result
        return EmbeddingResult(
            vectors=tuple(UNIT for _ in req.inputs),
            model=SERVED,
            input_tokens=sum(math.ceil(len(text) / 4) for text in req.inputs),
            provider="fake",
            generation_id="fake-1",
        )


class Echo:
    def complete(self, req: CompletionRequest) -> CompletionResponse:
        return CompletionResponse("fake:" + req.user, req.model or "fake/echo", 1, 2)


class Registry:
    def get(self, name: str, version: str) -> PromptSpec | None:
        return PromptSpec(name, version, "ai-platform", 1)

    def list(self) -> Sequence[PromptSpec]:
        return ()


class Ledger:
    def __init__(self) -> None:
        self.entries: list[LedgerEntry] = []

    def add(self, entry: LedgerEntry) -> None:
        self.entries.append(entry)

    def spent_inr(
        self, *, tenant_id: TenantId | None, feature: Feature | None, month: date
    ) -> Decimal:
        start, end = month_bounds(month)
        return sum(
            (
                e.cost_inr
                for e in self.entries
                if start <= e.occurred_at < end
                and (tenant_id is None or e.tenant_id == tenant_id)
                and (feature is None or e.feature is feature)
            ),
            Decimal("0.0000"),
        )

    def recent(self, limit: int) -> Sequence[LedgerEntry]:
        return tuple(reversed(self.entries))[:limit]


class Tracer:
    def __init__(self) -> None:
        self.records: list[CallRecord] = []
        self.fail = False

    def record(self, call: CallRecord) -> None:
        if self.fail:
            raise RuntimeError("tracer down")
        self.records.append(call)

    def flush(self) -> None:
        return None


class Publisher:
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []
        self.fail = False

    def publish(self, event: DomainEvent) -> None:
        if self.fail:
            raise RuntimeError("bus down")
        self.events.append(event)


class Harness:
    """Both use cases over one ledger, breaker and budget guard, as the composition root has it."""

    def __init__(self, **config: Any) -> None:
        self.embedder = Embedder()
        self.providers: dict[str, Any] = {"fake": self.embedder, "vercel": self.embedder}
        self.ledger = Ledger()
        self.tracer = Tracer()
        self.publisher = Publisher()
        self.breaker = CircuitBreaker(threshold=3, open_seconds=60.0)
        self.ticks = [0.0]
        values: dict[str, Any] = {
            "routes": DEFAULT_ROUTES,
            "budgets": BudgetLimits(Decimal("1500"), Decimal("20000"), Decimal("0.8")),
            "usd_inr": Decimal("88.00"),
        }
        values.update(config)
        self.config = GatewayConfig(**values)
        self.budgets = BudgetGuard(ledger=self.ledger, publisher=self.publisher, config=self.config)
        self._embed: Embed | None = None

    def _monotonic(self) -> float:
        self.ticks[0] += 0.005
        return self.ticks[0]

    def embed(self) -> Embed:
        if self._embed is None:
            self._embed = Embed(
                providers=self.providers,
                breaker=self.breaker,
                budgets=self.budgets,
                ledger=self.ledger,
                tracer=self.tracer,
                publisher=self.publisher,
                config=self.config,
                clock=lambda: NOW,
                monotonic=self._monotonic,
            )
        return self._embed

    def complete(self) -> Complete:
        return Complete(
            registry=Registry(),
            providers={"fake": Echo()},
            breaker=self.breaker,
            budgets=self.budgets,
            cache=None,
            ledger=self.ledger,
            tracer=self.tracer,
            publisher=self.publisher,
            config=self.config,
            clock=lambda: NOW,
        )

    def run(self, req: EmbeddingRequest, correlation_id: str = "req-1") -> EmbeddingOutcome:
        return self.embed().run(req, correlation_id=correlation_id)


def retrieval(*inputs: str, **changes: Any) -> EmbeddingRequest:
    fields: dict[str, Any] = {"feature": "retrieval", "inputs": inputs or (CLAUSE,)}
    fields.update(changes)
    return EmbeddingRequest(**fields)


@pytest.fixture
def harness() -> Harness:
    return Harness()


# ---- happy path and masking ------------------------------------------------------------------


def test_happy_path_books_cost_traces_and_publishes(harness: Harness) -> None:
    tenant = TenantId.new()
    outcome = harness.run(retrieval(CLAUSE, "short", tenant_id=tenant, metadata={"doc": "d-1"}))

    assert outcome.vectors == (UNIT, UNIT)
    assert outcome.dims == EMBEDDING_DIMS
    assert (outcome.model_requested, outcome.model_served, outcome.provider) == (
        ROUTE_MODEL,
        SERVED,
        "fake",
    )
    assert outcome.input_tokens == 1002
    assert (outcome.cost_usd, outcome.cost_inr, outcome.cost_source) == (
        Decimal("0.000100"),
        Decimal("0.0088"),
        CostSource.ESTIMATE,
    )
    assert outcome.latency_ms == 5
    assert outcome.generation_id == "fake-1"
    assert dict(outcome.pii_counts) == NO_PII

    [entry] = harness.ledger.entries
    assert outcome.entry is entry
    assert outcome.trace_id == entry.trace_id == str(entry.id)
    assert (entry.feature, entry.prompt_name, entry.prompt_version) == (
        Feature.RETRIEVAL,
        "retrieval.embedding",
        "1",
    )
    assert (entry.tenant_id, entry.status, entry.output_tokens, entry.cached) == (
        tenant,
        CallStatus.OK,
        0,
        False,
    )
    assert entry.occurred_at == NOW

    [req] = harness.embedder.requests
    assert req.model == ROUTE_MODEL
    assert req.inputs == (CLAUSE, "short")

    [record] = harness.tracer.records
    assert record.kind is CallKind.EMBEDDING
    assert record.entry is entry
    assert (record.system, record.user) == ("", CLAUSE + "\n\nshort")
    assert record.output == "2 vectors of 512 dimensions"
    assert (record.max_tokens, record.has_schema) == (None, False)
    assert record.metadata == {"doc": "d-1"}

    [event] = harness.publisher.events
    assert isinstance(event, LLMCallCompleted)
    assert event.entry is entry
    assert event.tenant_id == tenant
    assert isinstance(event.correlation_id, CorrelationId)


def test_pii_is_masked_in_every_input_and_counted_across_them(harness: Harness) -> None:
    outcome = harness.run(retrieval("PAN ABCDE1234F filed", "call 9876543210 or ABCDE1234F"))
    [req] = harness.embedder.requests
    assert req.inputs == ("PAN [PAN] filed", "call [PHONE] or [PAN]")
    assert dict(outcome.pii_counts) == {**NO_PII, "pan": 2, "phone": 1}
    assert "ABCDE1234F" not in harness.tracer.records[0].user


def test_a_model_override_is_the_only_model_tried(harness: Harness) -> None:
    harness.embedder.fail_next(1)
    with pytest.raises(ProviderUnavailableError):
        harness.run(retrieval(model="voyage/voyage-3.5"))
    assert [r.model for r in harness.embedder.requests] == ["voyage/voyage-3.5"]
    [entry] = harness.ledger.entries
    assert entry.model_requested == entry.model_served == "voyage/voyage-3.5"


def test_the_fake_model_names_the_fake_provider(harness: Harness) -> None:
    harness.providers["vercel"] = None
    outcome = harness.run(retrieval(model=SERVED))
    assert outcome.model_requested == SERVED
    assert harness.embedder.requests[0].model == SERVED


def test_gateway_cost_and_host_are_taken_from_the_result(harness: Harness) -> None:
    harness.embedder.result = EmbeddingResult(
        vectors=(UNIT,),
        model=ROUTE_MODEL,
        input_tokens=7,
        provider="voyage",
        cost_usd=Decimal("0.000002"),
        generation_id="gen-9",
    )
    outcome = harness.run(retrieval())
    assert (outcome.cost_source, outcome.cost_usd, outcome.cost_inr) == (
        CostSource.GATEWAY,
        Decimal("0.000002"),
        Decimal("0.0002"),
    )
    assert (outcome.provider, outcome.generation_id, outcome.model_served) == (
        "voyage",
        "gen-9",
        ROUTE_MODEL,
    )


def test_an_empty_provider_name_is_filled_from_routing(harness: Harness) -> None:
    harness.embedder.result = EmbeddingResult(vectors=(UNIT,), model=SERVED, input_tokens=1)
    assert harness.run(retrieval()).provider == "vercel"


# ---- refusals before the provider ------------------------------------------------------------


@pytest.mark.parametrize("feature", ["qa", "smoke"])
def test_a_completion_feature_is_refused(harness: Harness, feature: str) -> None:
    with pytest.raises(FeatureMismatchError, match=f"'{feature}' is not served by embedding"):
        harness.run(retrieval(feature=feature))
    assert harness.embedder.calls == 0
    assert harness.ledger.entries == []


def test_an_unknown_feature_is_refused(harness: Harness) -> None:
    with pytest.raises(UnknownFeatureError):
        harness.run(retrieval(feature="search"))
    assert harness.ledger.entries == []


def test_a_completion_with_the_retrieval_feature_is_refused(harness: Harness) -> None:
    req = CompletionRequest(feature="retrieval", prompt_version="smoke.echo@1", system="", user="x")
    with pytest.raises(FeatureMismatchError, match="not served by completion calls"):
        harness.complete().run(req, correlation_id="req-1")
    assert harness.ledger.entries == []


@pytest.mark.parametrize(
    ("changes", "correlation_id", "message"),
    [
        ({"model": "gpt-4"}, "req-1", "model must look like creator/model"),
        ({"model": "fake/" + "m" * 130}, "req-1", "model must be at most 120 characters"),
        ({}, "c" * (MAX_CORRELATION_ID + 1), "correlation_id must be at most 64"),
    ],
)
def test_what_the_ledger_cannot_store_is_refused_before_any_call(
    harness: Harness, changes: dict[str, Any], correlation_id: str, message: str
) -> None:
    with pytest.raises(InvariantViolationError, match=message):
        harness.run(retrieval(**changes), correlation_id=correlation_id)
    assert harness.embedder.calls == 0
    assert harness.ledger.entries == []


# ---- budgets ---------------------------------------------------------------------------------


def test_no_row_and_no_call_once_the_tenant_budget_is_spent() -> None:
    harness = Harness(budgets=BudgetLimits(Decimal("0.0050"), Decimal("20000"), Decimal("0.8")))
    tenant = TenantId.new()
    harness.run(retrieval(tenant_id=tenant))
    with pytest.raises(BudgetExceededError) as info:
        harness.run(retrieval(tenant_id=tenant))
    assert info.value.scope == "tenant"
    assert info.value.spent_inr == Decimal("0.0088")
    assert harness.embedder.calls == 1
    assert len(harness.ledger.entries) == 1


def test_the_feature_budget_is_retrievals_own() -> None:
    harness = Harness(budgets=BudgetLimits(Decimal("1500"), Decimal("0.0050"), Decimal("0.8")))
    harness.run(retrieval())
    with pytest.raises(BudgetExceededError) as info:
        harness.run(retrieval())
    assert info.value.scope == "feature"
    assert "feature budget for retrieval" in str(info.value)
    other = CompletionRequest(feature="smoke", prompt_version="smoke.echo@1", system="", user="x")
    assert harness.complete().run(other, correlation_id="req-2").entry.status is CallStatus.OK


def test_one_alarm_per_tenant_and_month_across_both_use_cases(caplog: Any) -> None:
    harness = Harness(budgets=BudgetLimits(Decimal("0.0100"), Decimal("20000"), Decimal("0.8")))
    tenant = TenantId.new()
    completion = CompletionRequest(
        feature="smoke", prompt_version="smoke.echo@1", system="", user="hi", tenant_id=tenant
    )
    with caplog.at_level(logging.WARNING, logger="llm_gateway.application.metering"):
        harness.run(retrieval(tenant_id=tenant))
        assert not [e for e in harness.publisher.events if isinstance(e, BudgetAlarmed)]
        harness.complete().run(completion, correlation_id="req-2")
        harness.run(retrieval("again", tenant_id=tenant))
        harness.complete().run(completion, correlation_id="req-3")
    [alarm] = [e for e in harness.publisher.events if isinstance(e, BudgetAlarmed)]
    assert (alarm.scope, alarm.key, alarm.spent_inr) == (
        BudgetScope.TENANT,
        str(tenant),
        Decimal("0.0088"),
    )
    assert len([r for r in caplog.records if "budget alarm" in r.getMessage()]) == 1
    assert len(harness.ledger.entries) == 4


# ---- provider errors and the breaker ---------------------------------------------------------


def test_an_unavailable_provider_writes_an_error_row_and_no_event(harness: Harness) -> None:
    harness.embedder.fail_next(1)
    with pytest.raises(ProviderUnavailableError, match="injected failure"):
        harness.run(retrieval(tenant_id=TenantId.new()))
    [entry] = harness.ledger.entries
    assert (entry.status, entry.error_type) == (CallStatus.ERROR, "llm-provider-unavailable")
    assert (entry.model_requested, entry.model_served, entry.provider) == (
        ROUTE_MODEL,
        ROUTE_MODEL,
        "vercel",
    )
    assert (entry.prompt_name, entry.prompt_version) == ("retrieval.embedding", "1")
    assert (entry.input_tokens, entry.output_tokens, entry.cost_inr) == (0, 0, Decimal("0.0000"))
    assert entry.latency_ms > 0
    assert harness.publisher.events == []
    [record] = harness.tracer.records
    assert (record.kind, record.output, record.error_detail) == (
        CallKind.EMBEDDING,
        "",
        "fake provider: injected failure",
    )
    assert harness.breaker.state(("vercel", ROUTE_MODEL)) is BreakerState.CLOSED


def test_repeated_failures_open_the_circuit_and_it_answers_without_a_call(
    harness: Harness,
) -> None:
    harness.embedder.fail_next(3)
    for _ in range(3):
        with pytest.raises(ProviderUnavailableError):
            harness.run(retrieval())
    assert harness.breaker.state(("vercel", ROUTE_MODEL)) is BreakerState.OPEN
    with pytest.raises(ProviderUnavailableError, match=f"circuit open for {ROUTE_MODEL}") as info:
        harness.run(retrieval())
    assert info.value.retry_after_seconds is not None
    assert harness.embedder.calls == 3
    assert [e.error_type for e in harness.ledger.entries] == ["llm-provider-unavailable"] * 4


def test_a_success_closes_the_count(harness: Harness) -> None:
    harness.embedder.fail_next(2)
    for _ in range(2):
        with pytest.raises(ProviderUnavailableError):
            harness.run(retrieval())
    harness.run(retrieval())
    harness.embedder.fail_next(2)
    for _ in range(2):
        with pytest.raises(ProviderUnavailableError):
            harness.run(retrieval())
    assert harness.breaker.state(("vercel", ROUTE_MODEL)) is BreakerState.CLOSED


@pytest.mark.parametrize(
    ("vectors", "message"),
    [
        ((UNIT[:3],), "vector 0 has 3 dimensions, expected 512"),
        ((UNIT, UNIT), "provider returned 2 vectors for 1 inputs"),
        ((), "provider returned 0 vectors for 1 inputs"),
    ],
)
def test_a_wrong_shape_is_a_response_error_with_a_row_and_no_vectors(
    harness: Harness, vectors: tuple[tuple[float, ...], ...], message: str
) -> None:
    harness.breaker = CircuitBreaker(threshold=1, open_seconds=60.0)
    harness.embedder.result = EmbeddingResult(vectors=vectors, model=SERVED, input_tokens=4)
    with pytest.raises(ProviderResponseError, match=message):
        harness.run(retrieval())
    [entry] = harness.ledger.entries
    assert (entry.status, entry.error_type) == (CallStatus.ERROR, "llm-provider-response-invalid")
    assert entry.cost_inr == Decimal("0.0000")
    assert harness.publisher.events == []
    assert harness.breaker.state(("vercel", ROUTE_MODEL)) is BreakerState.CLOSED


def test_a_refused_embeddings_override_leaves_the_models_completions_alone(
    harness: Harness,
) -> None:
    """The breaker is shared with completions: a model that serves no embeddings, named in an
    override, answers 4xx every time, and must not open the circuit for its completions."""
    harness.breaker = CircuitBreaker(threshold=1, open_seconds=60.0)
    for _ in range(3):
        harness.embedder.raise_next(
            ProviderResponseError("gateway rejected the request: not an embedding model")
        )
        with pytest.raises(ProviderResponseError, match="not an embedding model"):
            harness.run(retrieval(model="fake/echo"))
    assert harness.breaker.state(("fake", "fake/echo")) is BreakerState.CLOSED
    completion = CompletionRequest(
        feature="smoke", prompt_version="smoke.echo@1", system="", user="hi"
    )
    outcome = harness.complete().run(completion, correlation_id="req-2")
    assert (outcome.entry.status, outcome.entry.model_served) == (CallStatus.OK, "fake/echo")


def test_a_missing_provider_is_unavailable_with_an_error_row(harness: Harness) -> None:
    harness.providers = {"fake": harness.embedder}
    with pytest.raises(ProviderUnavailableError, match="no provider registered for 'vercel'"):
        harness.run(retrieval())
    [entry] = harness.ledger.entries
    assert (entry.error_type, entry.provider) == ("llm-provider-unavailable", "vercel")


def test_an_unexpected_exception_keeps_the_circuit_closed(harness: Harness) -> None:
    harness.breaker = CircuitBreaker(threshold=1, open_seconds=60.0)
    harness.embedder.raise_next(RuntimeError("socket closed"))
    with pytest.raises(RuntimeError, match="socket closed"):
        harness.run(retrieval())
    assert harness.ledger.entries[0].error_type == "RuntimeError"
    assert harness.breaker.state(("vercel", ROUTE_MODEL)) is BreakerState.CLOSED


def test_a_gateway_quota_is_re_raised_with_a_row(harness: Harness) -> None:
    harness.embedder.raise_next(BudgetExceededError("gateway quota exceeded", scope="gateway"))
    with pytest.raises(BudgetExceededError, match="gateway quota"):
        harness.run(retrieval())
    assert harness.ledger.entries[0].error_type == "llm-budget-exceeded"


def test_tracer_and_publisher_failures_do_not_fail_the_call(harness: Harness, caplog: Any) -> None:
    harness.tracer.fail = True
    harness.publisher.fail = True
    with caplog.at_level(logging.ERROR):
        outcome = harness.run(retrieval())
    assert outcome.vectors == (UNIT,)
    assert len(harness.ledger.entries) == 1
    messages = [r.getMessage() for r in caplog.records]
    assert any("tracing call" in m for m in messages)
    assert any("llm.call.completed" in m for m in messages)


def test_a_tracer_failure_on_the_error_path_is_logged(harness: Harness, caplog: Any) -> None:
    harness.tracer.fail = True
    harness.embedder.fail_next(1)
    with caplog.at_level(logging.ERROR), pytest.raises(ProviderUnavailableError):
        harness.run(retrieval())
    assert len(harness.ledger.entries) == 1
    assert any("tracing call" in r.getMessage() for r in caplog.records)
