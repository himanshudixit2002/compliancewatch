"""The in-memory cache: TTL, least recently used eviction, thread safety."""

import math
import threading

import pytest

from domain_kernel.errors import InvariantViolationError
from llm_gateway.domain.providers import ProviderResponse
from llm_gateway.infrastructure.cache.memory import MemoryCache


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def response(text: str = "answer") -> ProviderResponse:
    return ProviderResponse(
        text=text, model="fake/echo", input_tokens=1, output_tokens=1, provider="fake"
    )


def test_put_then_get_returns_the_same_response() -> None:
    cache = MemoryCache(ttl_seconds=10, max_entries=5)
    stored = response()
    cache.put("k", stored)
    assert cache.get("k") is stored
    assert cache.get("missing") is None
    assert len(cache) == 1


def test_entries_expire_after_the_ttl() -> None:
    clock = Clock()
    cache = MemoryCache(ttl_seconds=10, max_entries=5, clock=clock)
    cache.put("k", response())
    clock.now = 9.99
    assert cache.get("k") is not None
    clock.now = 10.0
    assert cache.get("k") is None
    assert len(cache) == 0


def test_least_recently_used_entry_is_evicted_first() -> None:
    cache = MemoryCache(ttl_seconds=10, max_entries=2)
    cache.put("a", response("a"))
    cache.put("b", response("b"))
    assert cache.get("a") is not None
    cache.put("c", response("c"))
    assert cache.get("b") is None
    assert [cache.get("a"), cache.get("c")] == [response("a"), response("c")]
    assert len(cache) == 2


def test_putting_an_existing_key_refreshes_ttl_and_recency() -> None:
    clock = Clock()
    cache = MemoryCache(ttl_seconds=10, max_entries=2, clock=clock)
    cache.put("a", response("a1"))
    cache.put("b", response("b"))
    clock.now = 8.0
    cache.put("a", response("a2"))
    cache.put("c", response("c"))
    assert cache.get("b") is None
    clock.now = 15.0
    assert cache.get("a") == response("a2")


def test_clear_empties_the_cache() -> None:
    cache = MemoryCache(ttl_seconds=10, max_entries=5)
    cache.put("a", response())
    cache.clear()
    assert len(cache) == 0
    assert cache.get("a") is None


@pytest.mark.parametrize(
    ("ttl_seconds", "max_entries", "message"),
    [
        (0, 1, "ttl_seconds must be positive"),
        (-1.0, 1, "ttl_seconds must be positive"),
        (math.nan, 1, "ttl_seconds must be a finite number"),
        (10, 0, "max_entries must be at least 1"),
        (10, True, "max_entries must be an integer"),
    ],
)
def test_invariants(ttl_seconds: float, max_entries: int, message: str) -> None:
    with pytest.raises(InvariantViolationError, match=message):
        MemoryCache(ttl_seconds=ttl_seconds, max_entries=max_entries)


def test_defaults_to_the_monotonic_clock() -> None:
    cache = MemoryCache(ttl_seconds=60, max_entries=1)
    cache.put("k", response())
    assert cache.get("k") is not None
    assert cache.ttl_seconds == 60.0
    assert cache.max_entries == 1


def test_concurrent_puts_and_gets_never_exceed_the_bound() -> None:
    cache = MemoryCache(ttl_seconds=60, max_entries=20)
    errors: list[BaseException] = []

    def worker(index: int) -> None:
        try:
            for step in range(100):
                key = f"{index}-{step % 30}"
                cache.put(key, response(key))
                cache.get(key)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert 0 < len(cache) <= 20
