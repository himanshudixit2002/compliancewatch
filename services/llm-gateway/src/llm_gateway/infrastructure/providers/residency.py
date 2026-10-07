"""The residency guard (``CW_LLM_RESIDENCY=india_only``, ADR-020): providers that refuse.

``guarded(policy, providers)`` is what the composition root registers, once every provider is in
place. Under ``india_only`` it wraps in ``ResidencyBlockedProvider`` every provider that is not an
adapter of ``IN_INDIA``, whatever it is and whatever name it is registered under: the Vercel
provider, a provider added later, the eval harness's in-process completion provider. The guard
does not rely on an adapter remembering to wrap itself, and a provider it does not know is
refused. Only the fake provider is in ``IN_INDIA`` today, since no routed model runs inference in
India; it answers wherever it is registered, so with ``CW_LLM_PROVIDER=fake`` every route does.
Under ``global`` nothing is wrapped.

``ResidencyBlockedProvider`` raises ``ResidencyUnavailableError`` (503
``llm-residency-unavailable``) from ``complete`` and ``embed`` and never calls the provider it
wraps, so no text leaves the process. The use cases book the refusal in the ledger at no cost and
trace it, as any failed call; they try no fallback model and count no breaker failure for it.
"""

from collections.abc import Mapping
from typing import Final

from domain_kernel.llm import CompletionRequest
from domain_kernel.protocols import LLMProvider
from llm_gateway.domain.embeddings import EmbeddingProvider, EmbeddingRequest, EmbeddingResult
from llm_gateway.domain.errors import ResidencyUnavailableError
from llm_gateway.domain.providers import ProviderResponse
from llm_gateway.domain.residency import ResidencyPolicy
from llm_gateway.infrastructure.providers.fake import FakeProvider

IN_INDIA: Final[frozenset[type]] = frozenset({FakeProvider})
"""The provider adapters that keep the text in India, by class (a subclass is not one of them):
the fake one, which answers in process. A provider in India would be added here."""


class ResidencyBlockedProvider:
    """Stands in for ``provider``, registered as ``name``, and refuses every call to it."""

    def __init__(self, provider: LLMProvider | EmbeddingProvider, *, name: str) -> None:
        self.provider = provider
        self.name = name

    def complete(self, req: CompletionRequest) -> ProviderResponse:
        raise ResidencyUnavailableError(model=req.model or "", provider=self.name)

    def embed(self, req: EmbeddingRequest) -> EmbeddingResult:
        raise ResidencyUnavailableError(model=req.model or "", provider=self.name)


def in_india(provider: object) -> bool:
    """Whether ``provider`` is an adapter of ``IN_INDIA``."""
    return type(provider) in IN_INDIA


def guarded[P: LLMProvider | EmbeddingProvider](
    policy: ResidencyPolicy, providers: Mapping[str, P]
) -> dict[str, P | ResidencyBlockedProvider]:
    """``providers`` by name, under ``india_only`` each one outside ``IN_INDIA`` wrapped in the
    guard."""
    if policy.real_models_allowed:
        return dict(providers)
    return {
        name: provider if in_india(provider) else ResidencyBlockedProvider(provider, name=name)
        for name, provider in providers.items()
    }
