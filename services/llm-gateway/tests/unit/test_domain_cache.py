import re
from types import MappingProxyType

from domain_kernel.llm import CompletionRequest
from llm_gateway.domain.cache import ResponseCache, cache_key, is_cacheable
from llm_gateway.domain.providers import ProviderResponse

BASE: dict[str, object] = {
    "model": "fake/echo",
    "prompt": "smoke.echo@1",
    "system": "You echo.",
    "user": "hello",
    "json_schema": None,
    "temperature": 0.0,
    "max_tokens": 1024,
}


def _key(**changes: object) -> str:
    return cache_key(**{**BASE, **changes})  # type: ignore[arg-type]


def test_key_is_stable_and_hex() -> None:
    assert _key() == _key()
    assert re.fullmatch(r"[0-9a-f]{64}", _key())


def test_each_input_changes_the_key() -> None:
    base = _key()
    variants = [
        _key(model="fake/other"),
        _key(prompt="smoke.echo@2"),
        _key(system="You shout."),
        _key(user="hello "),
        _key(json_schema={}),
        _key(json_schema={"type": "object"}),
        _key(temperature=0.1),
        _key(max_tokens=1025),
    ]
    assert base not in variants
    assert len(set(variants)) == len(variants)


def test_schema_key_order_and_proxies_do_not_matter() -> None:
    ordered = _key(json_schema={"type": "object", "properties": {"a": {"type": "string"}}})
    shuffled = _key(json_schema={"properties": {"a": {"type": "string"}}, "type": "object"})
    proxied = _key(
        json_schema=MappingProxyType(
            {"properties": MappingProxyType({"a": {"type": "string"}}), "type": "object"}
        )
    )
    assert ordered == shuffled == proxied
    assert _key(json_schema={"required": ["a", "b"]}) == _key(json_schema={"required": ("a", "b")})
    assert _key(json_schema={"required": ["a", "b"]}) != _key(json_schema={"required": ["b", "a"]})


def test_non_ascii_text_is_part_of_the_key() -> None:
    assert _key(user="नमस्ते") != _key(user="namaste")


def test_only_deterministic_requests_are_cacheable() -> None:
    assert is_cacheable(CompletionRequest("qa", "qa.answer@1", "", "q"))
    assert is_cacheable(CompletionRequest("qa", "qa.answer@1", "", "q", temperature=0))
    assert not is_cacheable(CompletionRequest("qa", "qa.answer@1", "", "q", temperature=0.5))


class _Cache:
    def __init__(self) -> None:
        self.items: dict[str, ProviderResponse] = {}

    def get(self, key: str) -> ProviderResponse | None:
        return self.items.get(key)

    def put(self, key: str, response: ProviderResponse) -> None:
        self.items[key] = response


def test_cache_protocol_is_structural() -> None:
    cache: ResponseCache = _Cache()
    response = ProviderResponse("hi", "fake/echo", 1, 1, provider="fake")
    assert cache.get("k") is None
    cache.put("k", response)
    assert cache.get("k") == response
