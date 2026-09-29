"""Embedding calls: what a caller sends, what a provider returns, and the checks between them.

Vectors from two models do not compare, so an embedding call has one model and no fallback, and
the caller stores the model that served it with every vector. There is no prompt text; the
ledger names the input preparation (masking) as ``EMBEDDING_LEDGER_REF``, bumped when it changes.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType
from typing import Final, Protocol

from domain_kernel._validation import freeze_mapping, require_instance, require_int, require_text
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import TenantId
from domain_kernel.vectors import EMBEDDING_DIMS, Vector
from llm_gateway.domain.errors import ProviderResponseError
from llm_gateway.domain.prompts import PromptRef

MAX_EMBEDDING_INPUTS: Final = 64
"""Inputs per call: a batch of clauses, or one query."""
MAX_EMBEDDING_INPUT_CHARS: Final = 8000
"""Characters per input: a clause with its header, well inside every model's token window."""
EMBEDDING_LEDGER_REF: Final = PromptRef("retrieval.embedding", "1")
"""What the ledger records as the prompt of an embedding call: the input preparation."""


@dataclass(frozen=True, slots=True)
class EmbeddingRequest:
    """Texts to embed. ``feature`` must be an embedding feature; ``model`` overrides the route.

    ``metadata`` carries caller tags for the trace, string keys and values only.
    """

    feature: str
    inputs: tuple[str, ...]
    model: str | None = None
    tenant_id: TenantId | None = None
    metadata: Mapping[str, str] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        require_text(self.feature, "feature")
        inputs = require_instance(self.inputs, tuple, "inputs")
        if not 1 <= len(inputs) <= MAX_EMBEDDING_INPUTS:
            raise InvariantViolationError(
                f"inputs must hold 1 to {MAX_EMBEDDING_INPUTS} texts, got {len(inputs)}"
            )
        for index, text in enumerate(inputs):
            require_text(text, f"inputs[{index}]", strip=False)
            if len(text) > MAX_EMBEDDING_INPUT_CHARS:
                raise InvariantViolationError(
                    f"inputs[{index}] must be at most {MAX_EMBEDDING_INPUT_CHARS} characters"
                )
        if self.model is not None:
            require_text(self.model, "model")
        if self.tenant_id is not None:
            require_instance(self.tenant_id, TenantId, "tenant_id")
        tags: dict[str, str] = {}
        for key, value in freeze_mapping(self.metadata, "metadata").items():
            if not isinstance(value, str):
                raise InvariantViolationError(
                    f"metadata values must be strings, got {value.__class__.__name__} for {key!r}"
                )
            tags[key] = value
        object.__setattr__(self, "metadata", MappingProxyType(tags))


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    """One vector per input, in input order, with what the ledger wants.

    Every vector is a non-empty tuple of finite numbers. Whether the count and the length are
    right is ``require_vectors_for``'s question: a wrong answer is the provider's fault.
    ``cost_usd`` is None when the provider gave no figure and the price table estimates it.
    """

    vectors: tuple[Vector, ...]
    model: str
    input_tokens: int
    provider: str = ""
    cost_usd: Decimal | None = None
    generation_id: str = ""

    def __post_init__(self) -> None:
        vectors = require_instance(self.vectors, tuple, "vectors")
        for index, vector in enumerate(vectors):
            _require_vector(vector, f"vectors[{index}]")
        require_text(self.model, "model")
        require_int(self.input_tokens, "input_tokens", minimum=0)
        require_instance(self.provider, str, "provider")
        if self.cost_usd is not None and (
            not isinstance(self.cost_usd, Decimal) or not self.cost_usd.is_finite()
        ):
            raise InvariantViolationError(f"cost_usd must be a Decimal, got {self.cost_usd!r}")
        require_instance(self.generation_id, str, "generation_id")


def _require_vector(value: object, name: str) -> None:
    vector = require_instance(value, tuple, name)
    if not vector:
        raise InvariantViolationError(f"{name} must not be empty")
    for component in vector:
        if (
            isinstance(component, bool)
            or not isinstance(component, int | float)
            or not math.isfinite(component)
        ):
            raise InvariantViolationError(f"{name} must hold finite numbers, got {component!r}")


def require_vectors_for(result: EmbeddingResult, count: int) -> EmbeddingResult:
    """``result`` when it holds ``count`` vectors of ``EMBEDDING_DIMS`` each.

    Anything else is a ``ProviderResponseError``: vectors of another length would not compare
    with the stored ones, so nothing of the answer may be kept.
    """
    if len(result.vectors) != count:
        raise ProviderResponseError(
            f"provider returned {len(result.vectors)} vectors for {count} inputs"
        )
    for index, vector in enumerate(result.vectors):
        if len(vector) != EMBEDDING_DIMS:
            raise ProviderResponseError(
                f"vector {index} has {len(vector)} dimensions, expected {EMBEDDING_DIMS}"
            )
    return result


class EmbeddingProvider(Protocol):
    """Embeds every input of a request with the request's model."""

    def embed(self, req: EmbeddingRequest) -> EmbeddingResult: ...
