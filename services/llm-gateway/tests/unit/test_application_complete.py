"""The completion use case against local stubs of every port; no infrastructure imported."""

import hashlib
import logging
import math
from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Any
from uuid import uuid4

import pytest

from domain_kernel.errors import DomainError, InvariantViolationError
from domain_kernel.events import DomainEvent
from domain_kernel.ids import CorrelationId, TenantId
from domain_kernel.llm import CompletionRequest, CompletionResponse
from llm_gateway.application.complete import Complete, CompletionOutcome
from llm_gateway.domain.breaker import BreakerState, CircuitBreaker
from llm_gateway.domain.budgets import BudgetLimits, BudgetScope, month_bounds
from llm_gateway.domain.config import GatewayConfig
from llm_gateway.domain.errors import (
    BudgetExceededError,
    ProviderResponseError,
    ProviderUnavailableError,
    UnknownFeatureError,
    UnknownPromptError,
)
from llm_gateway.domain.events import BudgetAlarmed, LLMCallCompleted
from llm_gateway.domain.features import CallStatus, CostSource, Feature
from llm_gateway.domain.ledger import MAX_CORRELATION_ID, MAX_MODEL_ID, LedgerEntry
from llm_gateway.domain.prompts import PromptSpec
from llm_gateway.domain.providers import ProviderResponse
from llm_gateway.domain.routing import DEFAULT_ROUTES
from llm_gateway.domain.tracing import CallRecord

NOW = datetime(2026, 9, 27, 10, 0, tzinfo=UTC)
PRIMARY = DEFAULT_ROUTES[Feature.EXTRACTION].primary
FALLBACK = DEFAULT_ROUTES[Feature.EXTRACTION].models[1]
LONG_TEXT = "The registered person shall furnish the return in FORM GSTR-3B. " * 63
assert len(LONG_TEXT) == 4032
FIRST_CALL_INR = Decimal("0.0107")
"""1,008 input + 52 output tokens on fake/echo at the table price, times 88."""


# ---- stubs -----------------------------------------------------------------------------------


class FakeProvider:
    """Same contract as the infrastructure fake: deterministic echo, injectable failures."""

    MODEL = "fake/echo"

    def __init__(self) -> None:
        self.calls = 0
        self.requests: list[CompletionRequest] = []
        self._failures = 0
        self._raise: Exception | None = None
        self.response: CompletionResponse | None = None

    def fail_next(self, count: int = 1) -> None:
        self._failures = count

    def raise_next(self, exc: Exception) -> None:
        self._raise = exc

    def complete(self, req: CompletionRequest) -> CompletionResponse:
        self.calls += 1
        self.requests.append(req)
        if self._raise is not None:
            exc, self._raise = self._raise, None
            raise exc
        if self._failures:
            self._failures -= 1
            raise ProviderUnavailableError("fake provider: injected failure")
        if self.response is not None:
            return self.response
        text = "fake:" + req.user[-200:]
        return ProviderResponse(
            text=text,
            model=req.model or self.MODEL,
            input_tokens=math.ceil(len(req.user) / 4),
            output_tokens=math.ceil(len(text) / 4),
            provider="fake",
            generation_id="fake-" + hashlib.sha256(text.encode()).hexdigest()[:16],
        )


class Registry:
    def __init__(self, *specs: PromptSpec) -> None:
        self.specs = list(specs)

    def get(self, name: str, version: str) -> PromptSpec | None:
        return next((s for s in self.specs if (s.name, s.version) == (name, version)), None)

    def list(self) -> Sequence[PromptSpec]:
        return tuple(self.specs)


class Ledger:
    def __init__(self) -> None:
        self.entries: list[LedgerEntry] = []
        self.fail = False

    def add(self, entry: LedgerEntry) -> None:
        if self.fail:
            raise RuntimeError("ledger down")
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


class Cache:
    def __init__(self) -> None:
        self.items: dict[str, ProviderResponse] = {}

    def get(self, key: str) -> ProviderResponse | None:
        return self.items.get(key)

    def put(self, key: str, response: ProviderResponse) -> None:
        self.items[key] = response


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
    """Everything wired with stubs; tests tweak the pieces before calling ``run``."""

    def __init__(self, **config: Any) -> None:
        self.fake = FakeProvider()
        self.vercel = FakeProvider()
        self.registry = Registry(
            PromptSpec("smoke.echo", "1", "ai-platform", 1),
            PromptSpec("extraction.rule_candidate", "0", "ai-platform", 1),
            PromptSpec("qa.answer", "2", "ai-platform", 1),
        )
        self.ledger = Ledger()
        self.cache: Cache | None = Cache()
        self.tracer = Tracer()
        self.publisher = Publisher()
        self.breaker = CircuitBreaker(threshold=3, open_seconds=60.0)
        self.clock_now = NOW
        self.ticks = [0.0]
        values: dict[str, Any] = {
            "routes": DEFAULT_ROUTES,
            "budgets": BudgetLimits(Decimal("1500"), Decimal("20000"), Decimal("0.8")),
            "usd_inr": Decimal("88.00"),
        }
        values.update(config)
        self.config = GatewayConfig(**values)
        self.providers: dict[str, Any] = {"fake": self.fake, "vercel": self.vercel}
        self._complete: Complete | None = None

    def _monotonic(self) -> float:
        self.ticks[0] += 0.005
        return self.ticks[0]

    def complete(self) -> Complete:
        """Built once, on first use, so per-instance state (the alarm markers) persists."""
        if self._complete is None:
            self._complete = self._build()
        return self._complete

    def _build(self) -> Complete:
        return Complete(
            registry=self.registry,
            providers=self.providers,
            breaker=self.breaker,
            cache=self.cache,
            ledger=self.ledger,
            tracer=self.tracer,
            publisher=self.publisher,
            config=self.config,
            clock=lambda: self.clock_now,
            monotonic=self._monotonic,
        )

    def run(self, req: CompletionRequest, correlation_id: str = "req-1") -> CompletionOutcome:
        return self.complete().run(req, correlation_id=correlation_id)


def smoke(user: str = LONG_TEXT, **changes: Any) -> CompletionRequest:
    fields: dict[str, Any] = {
        "feature": "smoke",
        "prompt_version": "smoke.echo@1",
        "system": "",
        "user": user,
    }
    fields.update(changes)
    return CompletionRequest(**fields)


def extraction(**changes: Any) -> CompletionRequest:
    return smoke(feature="extraction", prompt_version="extraction.rule_candidate@0", **changes)


@pytest.fixture
def harness() -> Harness:
    return Harness()


# ---- happy path, cache, scrubbing ------------------------------------------------------------


def test_happy_path_books_cost_traces_and_publishes(harness: Harness) -> None:
    tenant = TenantId.new()
    outcome = harness.run(smoke(tenant_id=tenant, metadata={"document_id": "doc-1"}))

    assert outcome.text == "fake:" + LONG_TEXT[-200:]
    assert (outcome.model_requested, outcome.model_served, outcome.provider) == (
        "fake/echo",
        "fake/echo",
        "fake",
    )
    assert (outcome.input_tokens, outcome.output_tokens) == (1008, 52)
    assert outcome.cached is False
    assert outcome.cost_source is CostSource.ESTIMATE
    assert outcome.cost_usd == Decimal("0.000122")
    assert outcome.cost_inr == Decimal("0.0107")
    assert outcome.cost_inr > 0
    assert outcome.latency_ms == 5  # one clock tick between the run's start and its end
    assert outcome.generation_id.startswith("fake-")
    assert dict(outcome.pii_counts) == {"gstin": 0, "pan": 0, "aadhaar": 0, "phone": 0, "email": 0}
    assert outcome.response.cached is False
    assert outcome.response.trace_id == outcome.trace_id

    [entry] = harness.ledger.entries
    assert outcome.entry is entry
    assert entry.trace_id == str(entry.id)
    assert (entry.tenant_id, entry.feature, entry.status) == (tenant, Feature.SMOKE, CallStatus.OK)
    assert (entry.prompt_name, entry.prompt_version) == ("smoke.echo", "1")
    assert entry.occurred_at == NOW
    assert entry.correlation_id == "req-1"

    [record] = harness.tracer.records
    assert record.entry is entry
    assert record.output == outcome.text
    assert record.metadata == {"document_id": "doc-1"}
    assert (record.temperature, record.max_tokens, record.has_schema) == (0.0, 1024, False)

    [event] = harness.publisher.events
    assert isinstance(event, LLMCallCompleted)
    assert event.entry is entry
    assert event.tenant_id == tenant
    assert isinstance(event.correlation_id, CorrelationId)


def test_correlation_id_that_is_a_uuid_reaches_the_event(harness: Harness) -> None:
    correlation = uuid4().hex
    harness.run(smoke(), correlation_id=correlation)
    [event] = harness.publisher.events
    assert str(event.correlation_id) == str(CorrelationId.parse(correlation))
    assert harness.ledger.entries[0].correlation_id == correlation


def test_second_identical_call_is_served_from_the_cache(harness: Harness) -> None:
    first = harness.run(smoke())
    second = harness.run(smoke())

    assert harness.fake.calls == 1
    assert second.cached is True
    assert second.response.cached is True
    assert second.text == first.text
    assert (second.cost_usd, second.cost_inr, second.cost_source) == (
        Decimal("0.000000"),
        Decimal("0.0000"),
        CostSource.CACHE,
    )
    assert second.latency_ms == 0
    assert second.generation_id == first.generation_id
    assert second.trace_id != first.trace_id
    assert second.response.trace_id == second.trace_id
    assert [e.cached for e in harness.ledger.entries] == [False, True]
    assert (second.input_tokens, second.output_tokens) == (first.input_tokens, first.output_tokens)
    assert len(harness.publisher.events) == 2
    assert len(harness.tracer.records) == 2


def test_a_fallback_answer_is_not_cached_for_the_primary(harness: Harness) -> None:
    harness.vercel.fail_next(1)
    first = harness.run(extraction())
    assert first.model_served == FALLBACK
    assert harness.cache is not None
    assert harness.cache.items == {}

    second = harness.run(extraction())
    assert second.cached is False
    assert second.model_served == PRIMARY
    assert harness.vercel.calls == 3
    [cached] = harness.cache.items.values()
    assert cached.model == PRIMARY


def test_sampled_calls_are_never_cached(harness: Harness) -> None:
    harness.run(smoke(temperature=0.5))
    harness.run(smoke(temperature=0.5))
    assert harness.fake.calls == 2
    assert harness.cache is not None
    assert harness.cache.items == {}


def test_without_a_cache_every_call_reaches_the_provider(harness: Harness) -> None:
    harness.cache = None
    harness.run(smoke())
    outcome = harness.run(smoke())
    assert harness.fake.calls == 2
    assert outcome.cached is False


def test_pii_is_scrubbed_before_the_provider_sees_it(harness: Harness) -> None:
    outcome = harness.run(
        smoke(
            user="PAN ABCDE1234F, phone 9876543210, mail a@b.co",
            system="GSTIN 29ABCDE1234F1Z5 is the client",
        )
    )
    [req] = harness.fake.requests
    assert req.user == "PAN [PAN], phone [PHONE], mail [EMAIL]"
    assert req.system == "GSTIN [GSTIN] is the client"
    assert dict(outcome.pii_counts) == {"gstin": 1, "pan": 1, "aadhaar": 0, "phone": 1, "email": 1}
    assert "ABCDE1234F" not in outcome.text
    [record] = harness.tracer.records
    assert record.user == req.user
    assert record.system == req.system
    assert record.pii_counts == outcome.pii_counts


def test_schema_and_model_reach_the_provider(harness: Harness) -> None:
    schema = {"type": "object", "required": ["result"]}
    outcome = harness.run(smoke(json_schema=schema, model="fake/other", max_tokens=32))
    [req] = harness.fake.requests
    assert req.json_schema == schema
    assert isinstance(req.json_schema, MappingProxyType)
    assert req.model == "fake/other"
    assert outcome.model_requested == outcome.model_served == "fake/other"
    assert harness.tracer.records[0].has_schema is True
    assert harness.tracer.records[0].max_tokens == 32


# ---- budgets ---------------------------------------------------------------------------------


def test_tenant_budget_exceeded_after_the_first_call() -> None:
    harness = Harness(budgets=BudgetLimits(Decimal("0.0001"), Decimal("20000"), Decimal("0.8")))
    tenant = TenantId.new()
    harness.run(smoke(tenant_id=tenant))
    with pytest.raises(BudgetExceededError) as info:
        harness.run(smoke(tenant_id=tenant, user="another question"))
    error = info.value
    assert error.scope == "tenant"
    assert error.spent_inr == FIRST_CALL_INR
    assert error.limit_inr == Decimal("0.0001")
    assert error.resets_at == datetime(2026, 10, 1, tzinfo=UTC)
    assert "2026-09" in str(error)
    assert int(error.problem_headers["Retry-After"]) >= 1
    assert harness.fake.calls == 1
    assert len(harness.ledger.entries) == 1
    other = harness.run(smoke(tenant_id=TenantId.new(), user="another tenant"))
    assert other.cached is False


def test_regulatory_call_ignores_the_tenant_budget_but_not_the_feature_budget() -> None:
    harness = Harness(budgets=BudgetLimits(Decimal("0.0001"), Decimal("0.0100"), Decimal("0.8")))
    harness.run(smoke(tenant_id=None))
    with pytest.raises(BudgetExceededError) as info:
        harness.run(smoke(tenant_id=None, user="second regulatory call"))
    assert info.value.scope == "feature"
    assert info.value.limit_inr == Decimal("0.0100")
    assert harness.run(extraction(tenant_id=None)).cost_inr > 0


def test_alarm_fires_once_per_scope_and_month(caplog: Any) -> None:
    harness = Harness(budgets=BudgetLimits(Decimal("0.0120"), Decimal("20000"), Decimal("0.8")))
    tenant = TenantId.new()
    with caplog.at_level(logging.WARNING, logger="llm_gateway.application.complete"):
        harness.run(smoke(tenant_id=tenant))
        assert not [e for e in harness.publisher.events if isinstance(e, BudgetAlarmed)]
        harness.run(smoke(tenant_id=tenant))
        harness.run(smoke(tenant_id=tenant))
    alarms = [e for e in harness.publisher.events if isinstance(e, BudgetAlarmed)]
    [alarm] = alarms
    assert (alarm.scope, alarm.key, alarm.month) == (
        BudgetScope.TENANT,
        str(tenant),
        date(2026, 9, 1),
    )
    assert alarm.spent_inr == FIRST_CALL_INR
    assert alarm.limit_inr == Decimal("0.0120")
    assert alarm.ratio == alarm.spent_inr / Decimal("0.0120")
    assert alarm.tenant_id == tenant
    assert [r for r in caplog.records if "budget alarm" in r.getMessage()]
    assert len(harness.ledger.entries) == 3


def test_alarm_publisher_failure_does_not_fail_the_call(caplog: Any) -> None:
    harness = Harness(budgets=BudgetLimits(Decimal("0.0120"), Decimal("20000"), Decimal("0.8")))
    tenant = TenantId.new()
    harness.run(smoke(tenant_id=tenant))
    harness.publisher.fail = True
    with caplog.at_level(logging.ERROR):
        outcome = harness.run(smoke(tenant_id=tenant))
    assert outcome.cached is True
    assert [r for r in caplog.records if "llm.budget.alarmed" in r.getMessage()]


def test_alarm_is_independent_per_tenant() -> None:
    harness = Harness(budgets=BudgetLimits(Decimal("0.0120"), Decimal("20000"), Decimal("0.8")))
    first, second = TenantId.new(), TenantId.new()
    for tenant in (first, second, first, second):
        harness.run(smoke(user=f"{LONG_TEXT} {tenant}", tenant_id=tenant))
    alarms = [e for e in harness.publisher.events if isinstance(e, BudgetAlarmed)]
    assert {a.key for a in alarms} == {str(first), str(second)}


# ---- routing, fallback, breaker --------------------------------------------------------------


def test_fallback_after_the_primary_fails(harness: Harness) -> None:
    harness.vercel.fail_next(1)
    outcome = harness.run(extraction())
    assert [r.model for r in harness.vercel.requests] == [PRIMARY, FALLBACK]
    assert outcome.model_requested == PRIMARY
    assert outcome.model_served == FALLBACK
    assert outcome.provider == "fake"
    assert harness.breaker.state(("vercel", PRIMARY)) is BreakerState.CLOSED
    [entry] = harness.ledger.entries
    assert entry.status is CallStatus.OK
    assert entry.model_served == FALLBACK


def test_a_fallback_call_latency_covers_the_failed_attempt(harness: Harness) -> None:
    class SlowProvider(FakeProvider):
        """Each call moves the injected clock 100 ms."""

        def complete(self, req: CompletionRequest) -> CompletionResponse:
            harness.ticks[0] += 0.1
            return super().complete(req)

    slow = SlowProvider()
    harness.providers["vercel"] = slow
    single = harness.run(extraction())
    assert single.model_served == PRIMARY
    assert single.latency_ms == 105  # 100 ms in the provider plus the 5 ms closing tick

    slow.fail_next(1)
    fallback = harness.run(extraction(user="another clause"))
    assert fallback.model_served == FALLBACK
    assert fallback.latency_ms == 205  # both attempts plus the closing tick
    assert [e.latency_ms for e in harness.ledger.entries] == [105, 205]


def test_both_models_failing_writes_an_error_row_and_no_event(harness: Harness) -> None:
    harness.vercel.fail_next(2)
    with pytest.raises(ProviderUnavailableError, match="injected failure"):
        harness.run(extraction(tenant_id=TenantId.new()))
    [entry] = harness.ledger.entries
    assert entry.status is CallStatus.ERROR
    assert entry.error_type == "llm-provider-unavailable"
    # The provider is the registered name the attempt went to; there is no answer to name a host.
    assert (entry.model_requested, entry.model_served, entry.provider) == (
        PRIMARY,
        FALLBACK,
        "vercel",
    )
    assert (entry.input_tokens, entry.output_tokens) == (0, 0)
    assert (entry.cost_usd, entry.cost_inr, entry.cost_source) == (
        Decimal("0.000000"),
        Decimal("0.0000"),
        CostSource.ESTIMATE,
    )
    assert entry.latency_ms > 0
    assert entry.trace_id == str(entry.id)
    assert harness.publisher.events == []
    [record] = harness.tracer.records
    assert record.error_detail == "fake provider: injected failure"
    assert record.output == ""


def test_open_breaker_skips_the_primary(harness: Harness) -> None:
    harness.breaker = CircuitBreaker(threshold=1, open_seconds=60.0)
    harness.breaker.record_failure(("vercel", PRIMARY))
    outcome = harness.run(extraction())
    assert [r.model for r in harness.vercel.requests] == [FALLBACK]
    assert outcome.model_served == FALLBACK


def test_every_circuit_open_is_unavailable_with_an_error_row(harness: Harness) -> None:
    clock = [100.0]
    harness.breaker = CircuitBreaker(threshold=1, open_seconds=60.0, clock=lambda: clock[0])
    harness.breaker.record_failure(("vercel", PRIMARY))
    harness.breaker.record_failure(("vercel", FALLBACK))
    clock[0] += 12.5
    with pytest.raises(ProviderUnavailableError, match=f"circuit open for {FALLBACK}") as info:
        harness.run(extraction())
    assert info.value.retry_after_seconds == 48
    assert info.value.problem_headers == {"Retry-After": "48"}
    assert harness.vercel.calls == 0
    [entry] = harness.ledger.entries
    assert (entry.status, entry.model_served, entry.provider) == (
        CallStatus.ERROR,
        FALLBACK,
        "vercel",
    )


def test_repeated_failures_open_the_circuit(harness: Harness) -> None:
    harness.vercel.fail_next(6)
    for _ in range(3):
        with pytest.raises(ProviderUnavailableError):
            harness.run(extraction())
    assert harness.breaker.state(("vercel", PRIMARY)) is BreakerState.OPEN
    assert harness.breaker.state(("vercel", FALLBACK)) is BreakerState.OPEN
    assert harness.vercel.calls == 6


def test_explicit_model_disables_the_fallback(harness: Harness) -> None:
    harness.vercel.fail_next(1)
    with pytest.raises(ProviderUnavailableError):
        harness.run(extraction(model=PRIMARY))
    assert [r.model for r in harness.vercel.requests] == [PRIMARY]
    [entry] = harness.ledger.entries
    assert entry.model_requested == entry.model_served == PRIMARY


def test_malformed_explicit_model_is_rejected_before_any_call(harness: Harness) -> None:
    with pytest.raises(InvariantViolationError, match="model must look like creator/model"):
        harness.run(smoke(model="gpt-4"))
    assert harness.fake.calls == 0
    assert harness.ledger.entries == []


def test_an_overlong_model_id_is_refused_before_any_call(harness: Harness) -> None:
    model = "fake/" + "m" * 130
    assert len(model) == 135
    with pytest.raises(InvariantViolationError, match="model must be at most 120 characters"):
        harness.run(smoke(model=model))
    assert harness.fake.calls == 0
    assert harness.ledger.entries == []


def test_an_overlong_correlation_id_is_refused_before_any_call(harness: Harness) -> None:
    with pytest.raises(InvariantViolationError, match="correlation_id must be at most 64"):
        harness.run(smoke(), correlation_id="c" * (MAX_CORRELATION_ID + 1))
    assert harness.fake.calls == 0
    assert harness.ledger.entries == []

    longest = "c" * MAX_CORRELATION_ID
    assert harness.run(smoke(), correlation_id=longest).entry.correlation_id == longest
    assert harness.run(smoke(model="fake/" + "m" * (MAX_MODEL_ID - 5))).model_served.endswith("m")


def test_missing_provider_is_unavailable_with_an_error_row(harness: Harness) -> None:
    harness.providers = {"fake": harness.fake}
    with pytest.raises(ProviderUnavailableError, match="no provider registered for 'vercel'"):
        harness.run(extraction())
    [entry] = harness.ledger.entries
    assert entry.error_type == "llm-provider-unavailable"
    assert (entry.model_served, entry.provider) == (PRIMARY, "vercel")
    assert harness.publisher.events == []


# ---- registry and feature checks -------------------------------------------------------------


def test_unregistered_prompt_is_refused_unless_allowed(harness: Harness) -> None:
    message = r"prompt 'smoke\.echo@9' is not registered"
    with pytest.raises(UnknownPromptError, match=message) as info:
        harness.run(smoke(prompt_version="smoke.echo@9"))
    assert info.value.ref == "smoke.echo@9"
    assert harness.fake.calls == 0
    assert harness.ledger.entries == []

    allowed = Harness(allow_unregistered_prompts=True)
    outcome = allowed.run(smoke(prompt_version="smoke.echo@9"))
    assert outcome.entry.prompt_version == "9"


def test_malformed_prompt_reference(harness: Harness) -> None:
    with pytest.raises(InvariantViolationError, match="name@version"):
        harness.run(smoke(prompt_version="v3"))


def test_unknown_feature(harness: Harness) -> None:
    with pytest.raises(UnknownFeatureError, match="unknown feature 'summary'"):
        harness.run(smoke(feature="summary"))
    assert harness.ledger.entries == []


# ---- provider errors and side effects ---------------------------------------------------------


def test_provider_response_error_is_re_raised_with_an_error_row(harness: Harness) -> None:
    harness.breaker = CircuitBreaker(threshold=1, open_seconds=60.0)
    harness.vercel.raise_next(ProviderResponseError("empty choices"))
    with pytest.raises(ProviderResponseError, match="empty choices"):
        harness.run(extraction())
    assert harness.vercel.calls == 1
    [entry] = harness.ledger.entries
    assert entry.error_type == "llm-provider-response-invalid"
    assert entry.model_served == PRIMARY
    assert harness.breaker.state(("vercel", PRIMARY)) is BreakerState.OPEN
    assert harness.tracer.records[0].error_detail == "empty choices"


def test_gateway_quota_error_is_re_raised_without_tripping_the_breaker(harness: Harness) -> None:
    harness.breaker = CircuitBreaker(threshold=1, open_seconds=60.0)
    harness.vercel.raise_next(BudgetExceededError("gateway quota exceeded", scope="gateway"))
    with pytest.raises(BudgetExceededError, match="gateway quota exceeded"):
        harness.run(extraction())
    [entry] = harness.ledger.entries
    assert entry.error_type == "llm-budget-exceeded"
    assert harness.breaker.state(("vercel", PRIMARY)) is BreakerState.CLOSED


def test_unexpected_exception_is_re_raised_with_its_class_name(harness: Harness) -> None:
    harness.fake.raise_next(RuntimeError("socket closed"))
    with pytest.raises(RuntimeError, match="socket closed"):
        harness.run(smoke())
    [entry] = harness.ledger.entries
    assert (entry.error_type, entry.provider) == ("RuntimeError", "fake")
    assert harness.breaker.state(("fake", "fake/echo")) is BreakerState.CLOSED


def test_tracer_and_publisher_failures_do_not_fail_the_call(harness: Harness, caplog: Any) -> None:
    harness.tracer.fail = True
    harness.publisher.fail = True
    with caplog.at_level(logging.ERROR):
        outcome = harness.run(smoke())
    assert outcome.cached is False
    assert len(harness.ledger.entries) == 1
    messages = [r.getMessage() for r in caplog.records]
    assert any("tracing call" in m for m in messages)
    assert any("llm.call.completed" in m for m in messages)


def test_tracer_failure_on_the_error_path_is_logged(harness: Harness, caplog: Any) -> None:
    harness.tracer.fail = True
    harness.fake.fail_next(1)
    with caplog.at_level(logging.ERROR), pytest.raises(ProviderUnavailableError):
        harness.run(smoke())
    assert len(harness.ledger.entries) == 1
    assert any("tracing call" in r.getMessage() for r in caplog.records)


def test_ledger_failure_fails_the_call(harness: Harness) -> None:
    harness.ledger.fail = True
    with pytest.raises(RuntimeError, match="ledger down"):
        harness.run(smoke())
    assert harness.publisher.events == []


# ---- response normalisation and cost source --------------------------------------------------


def test_gateway_cost_and_host_are_taken_from_the_response(harness: Harness) -> None:
    harness.vercel.response = ProviderResponse(
        text="{}",
        model=PRIMARY,
        input_tokens=100,
        output_tokens=10,
        provider="deepinfra",
        cost_usd=Decimal("0.001234"),
        generation_id="gen-1",
    )
    outcome = harness.run(extraction())
    assert outcome.cost_source is CostSource.GATEWAY
    assert (outcome.cost_usd, outcome.cost_inr) == (Decimal("0.001234"), Decimal("0.1086"))
    assert (outcome.provider, outcome.generation_id) == ("deepinfra", "gen-1")


def test_plain_kernel_response_is_widened_with_the_routing_provider(harness: Harness) -> None:
    harness.fake.response = CompletionResponse("plain", "fake/echo", 3, 2)
    outcome = harness.run(smoke())
    assert outcome.provider == "fake"
    assert outcome.cost_source is CostSource.ESTIMATE
    assert outcome.generation_id == ""
    assert isinstance(outcome.response, ProviderResponse)


def test_empty_provider_name_is_filled_from_routing(harness: Harness) -> None:
    harness.fake.response = ProviderResponse("x", "fake/echo", 1, 1, provider="")
    assert harness.run(smoke()).provider == "fake"
    assert harness.ledger.entries[0].provider == "fake"


def test_error_type_is_a_domain_slug_for_domain_errors(harness: Harness) -> None:
    class CustomError(DomainError):
        type_slug = "llm-test-custom"
        title = "Test custom"

    harness.fake.raise_next(CustomError("x"))
    with pytest.raises(CustomError):
        harness.run(smoke())
    assert harness.ledger.entries[0].error_type == "llm-test-custom"
