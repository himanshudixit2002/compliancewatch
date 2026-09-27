import pytest

from domain_kernel.errors import InvariantViolationError
from llm_gateway.domain.breaker import BreakerState, CircuitBreaker

PRIMARY = ("vercel", "deepseek/deepseek-v4-pro-0813")
FALLBACK = ("vercel", "zai/glm-5.3")


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> _Clock:
    return _Clock()


@pytest.fixture
def breaker(clock: _Clock) -> CircuitBreaker:
    return CircuitBreaker(threshold=3, open_seconds=60.0, clock=clock)


def test_closed_until_the_threshold(breaker: CircuitBreaker) -> None:
    assert breaker.state(PRIMARY) is BreakerState.CLOSED
    assert breaker.allows(PRIMARY)
    breaker.record_failure(PRIMARY)
    breaker.record_failure(PRIMARY)
    assert breaker.state(PRIMARY) is BreakerState.CLOSED
    assert breaker.allows(PRIMARY)
    breaker.record_failure(PRIMARY)
    assert breaker.state(PRIMARY) is BreakerState.OPEN
    assert not breaker.allows(PRIMARY)


def test_open_then_one_probe_then_closed(breaker: CircuitBreaker, clock: _Clock) -> None:
    for _ in range(3):
        breaker.record_failure(PRIMARY)
    clock.now += 59.9
    assert breaker.state(PRIMARY) is BreakerState.OPEN
    assert not breaker.allows(PRIMARY)
    clock.now += 0.1
    assert breaker.state(PRIMARY) is BreakerState.HALF_OPEN
    assert breaker.allows(PRIMARY)
    assert not breaker.allows(PRIMARY)
    assert breaker.state(PRIMARY) is BreakerState.HALF_OPEN
    breaker.record_success(PRIMARY)
    assert breaker.state(PRIMARY) is BreakerState.CLOSED
    assert breaker.allows(PRIMARY)
    assert breaker.allows(PRIMARY)


def test_failed_probe_reopens_for_a_full_window(breaker: CircuitBreaker, clock: _Clock) -> None:
    for _ in range(3):
        breaker.record_failure(PRIMARY)
    clock.now += 60
    assert breaker.allows(PRIMARY)
    breaker.record_failure(PRIMARY)
    assert breaker.state(PRIMARY) is BreakerState.OPEN
    clock.now += 30
    assert not breaker.allows(PRIMARY)
    clock.now += 30
    assert breaker.allows(PRIMARY)


def test_success_resets_the_failure_count(breaker: CircuitBreaker) -> None:
    breaker.record_failure(PRIMARY)
    breaker.record_failure(PRIMARY)
    breaker.record_success(PRIMARY)
    breaker.record_failure(PRIMARY)
    breaker.record_failure(PRIMARY)
    assert breaker.state(PRIMARY) is BreakerState.CLOSED
    breaker.record_success(FALLBACK)
    assert breaker.state(FALLBACK) is BreakerState.CLOSED


def test_keys_are_independent(breaker: CircuitBreaker) -> None:
    for _ in range(3):
        breaker.record_failure(PRIMARY)
    assert not breaker.allows(PRIMARY)
    assert breaker.allows(FALLBACK)
    assert breaker.state(FALLBACK) is BreakerState.CLOSED
    assert breaker.allows(("fake", "fake/echo"))


def test_retry_after_counts_down_to_the_probe(breaker: CircuitBreaker, clock: _Clock) -> None:
    assert breaker.retry_after(PRIMARY) is None
    breaker.record_failure(PRIMARY)
    breaker.record_failure(PRIMARY)
    assert breaker.retry_after(PRIMARY) is None  # still closed
    breaker.record_failure(PRIMARY)
    assert breaker.retry_after(PRIMARY) == 60
    clock.now = 112.5
    assert breaker.retry_after(PRIMARY) == 48  # whole seconds, rounded up
    clock.now = 159.9
    assert breaker.retry_after(PRIMARY) == 1  # never zero while the circuit is open
    clock.now = 160.0
    assert breaker.retry_after(PRIMARY) is None  # the probe may go out now
    assert breaker.allows(PRIMARY)
    assert breaker.retry_after(PRIMARY) is None  # half open: the probe decides
    breaker.record_failure(PRIMARY)
    assert breaker.retry_after(PRIMARY) == 60
    breaker.record_success(PRIMARY)
    assert breaker.retry_after(PRIMARY) is None
    assert breaker.retry_after(FALLBACK) is None


def test_defaults_and_invariants() -> None:
    default = CircuitBreaker()
    assert (default.threshold, default.open_seconds) == (3, 60.0)
    assert CircuitBreaker(threshold=1, open_seconds=1).open_seconds == 1.0
    with pytest.raises(InvariantViolationError, match="threshold must be at least 1"):
        CircuitBreaker(threshold=0)
    with pytest.raises(InvariantViolationError, match="open_seconds must be positive"):
        CircuitBreaker(open_seconds=0)
    with pytest.raises(InvariantViolationError, match="open_seconds must be a finite number"):
        CircuitBreaker(open_seconds=float("nan"))


def test_threshold_one_opens_on_the_first_failure(clock: _Clock) -> None:
    breaker = CircuitBreaker(threshold=1, open_seconds=5, clock=clock)
    breaker.record_failure(PRIMARY)
    assert breaker.state(PRIMARY) is BreakerState.OPEN
    assert not breaker.allows(PRIMARY)
