"""Exact-match response cache: same model, prompt and parameters give the same answer."""

import hashlib
import json
from collections.abc import Mapping
from typing import Protocol

from domain_kernel.llm import CompletionRequest
from llm_gateway.domain.providers import ProviderResponse


class ResponseCache(Protocol):
    def get(self, key: str) -> ProviderResponse | None: ...

    def put(self, key: str, response: ProviderResponse) -> None: ...


def is_cacheable(req: CompletionRequest) -> bool:
    """Only deterministic calls are cached: a sampled answer is not reproducible."""
    return req.temperature == 0


def cache_key(
    *,
    model: str,
    prompt: str,
    system: str,
    user: str,
    json_schema: Mapping[str, object] | None,
    temperature: float,
    max_tokens: int,
) -> str:
    """SHA-256 of the canonical JSON of everything that shapes the answer.

    ``prompt`` is the ``name@version`` reference, so a prompt bump misses the cache. Schema key
    order does not matter.
    """
    payload = {
        "model": model,
        "prompt": prompt,
        "system": system,
        "user": user,
        "json_schema": None if json_schema is None else _plain(json_schema),
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _plain(value: object) -> object:
    """Mappings and sequences as plain dicts and lists, so proxies serialise."""
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    return value
