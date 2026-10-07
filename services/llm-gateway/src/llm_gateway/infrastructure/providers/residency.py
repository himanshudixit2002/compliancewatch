"""The residency guard (``CW_LLM_RESIDENCY=india_only``, ADR-020): a provider that refuses.

Under ``india_only`` the composition root wraps every provider that would send text to a model
outside India, which today is every real one, since no routed model runs inference in India.
``ResidencyBlockedProvider`` raises ``ResidencyUnavailableError`` (503
``llm-residency-unavailable``) from ``complete`` and ``embed`` and never calls the provider it
wraps, so no text leaves the process. The use cases book the refusal in the ledger at no cost and
trace it, as any failed call; they try no fallback model and count no breaker failure for it.

The fake provider answers in process and is never wrapped, so ``fake/...`` models keep answering.
A provider that runs inference in India would be wired unwrapped.
"""

from domain_kernel.llm import CompletionRequest
from domain_kernel.protocols import LLMProvider
from llm_gateway.domain.embeddings import EmbeddingProvider, EmbeddingRequest, EmbeddingResult
from llm_gateway.domain.errors import ResidencyUnavailableError
from llm_gateway.domain.providers import ProviderResponse


class ResidencyBlockedProvider:
    """Stands in for ``provider``, registered as ``name``, and refuses every call to it."""

    def __init__(self, provider: LLMProvider | EmbeddingProvider, *, name: str) -> None:
        self.provider = provider
        self.name = name

    def complete(self, req: CompletionRequest) -> ProviderResponse:
        raise ResidencyUnavailableError(model=req.model or "", provider=self.name)

    def embed(self, req: EmbeddingRequest) -> EmbeddingResult:
        raise ResidencyUnavailableError(model=req.model or "", provider=self.name)
