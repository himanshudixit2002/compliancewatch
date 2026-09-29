from decimal import Decimal
from types import MappingProxyType
from typing import Any

import pytest

from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import TenantId
from domain_kernel.vectors import EMBEDDING_DIMS
from llm_gateway.domain.embeddings import (
    EMBEDDING_LEDGER_REF,
    MAX_EMBEDDING_INPUT_CHARS,
    MAX_EMBEDDING_INPUTS,
    EmbeddingProvider,
    EmbeddingRequest,
    EmbeddingResult,
    require_vectors_for,
)
from llm_gateway.domain.errors import ProviderResponseError

UNIT = (1.0,) + (0.0,) * (EMBEDDING_DIMS - 1)


def request(**changes: Any) -> EmbeddingRequest:
    fields: dict[str, Any] = {"feature": "retrieval", "inputs": ("Section 7. Returns.",)}
    fields.update(changes)
    return EmbeddingRequest(**fields)


def result(*vectors: tuple[float, ...], **changes: Any) -> EmbeddingResult:
    fields: dict[str, Any] = {
        "vectors": vectors or (UNIT,),
        "model": "fake/hash-ngram-512",
        "input_tokens": 5,
    }
    fields.update(changes)
    return EmbeddingResult(**fields)


def test_the_bounds_and_the_ledger_reference() -> None:
    assert (MAX_EMBEDDING_INPUTS, MAX_EMBEDDING_INPUT_CHARS, EMBEDDING_DIMS) == (64, 8000, 512)
    assert str(EMBEDDING_LEDGER_REF) == "retrieval.embedding@1"


def test_request_defaults_and_frozen_metadata() -> None:
    tenant = TenantId.new()
    req = request(tenant_id=tenant, metadata={"document_id": "doc-1"}, model="fake/other")
    assert (req.model, req.tenant_id) == ("fake/other", tenant)
    assert isinstance(req.metadata, MappingProxyType)
    assert req.metadata == {"document_id": "doc-1"}
    assert request().metadata == {}
    longest = request(inputs=("x" * MAX_EMBEDDING_INPUT_CHARS,) * MAX_EMBEDDING_INPUTS)
    assert len(longest.inputs) == MAX_EMBEDDING_INPUTS
    assert request(inputs=("  padded  ",)).inputs == ("  padded  ",)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"feature": ""}, "feature must not be blank"),
        ({"inputs": ["a"]}, "inputs must be tuple"),
        ({"inputs": ()}, "inputs must hold 1 to 64 texts, got 0"),
        ({"inputs": ("a",) * 65}, "inputs must hold 1 to 64 texts, got 65"),
        ({"inputs": ("a", " ")}, r"inputs\[1\] must not be blank"),
        ({"inputs": ("a", 7)}, r"inputs\[1\] must be str"),
        ({"inputs": ("x" * 8001,)}, r"inputs\[0\] must be at most 8000 characters"),
        ({"model": ""}, "model must not be blank"),
        ({"tenant_id": "t-1"}, "tenant_id must be TenantId"),
        ({"metadata": {"pages": 3}}, "metadata values must be strings, got int for 'pages'"),
        ({"metadata": "x"}, "metadata must be a mapping"),
    ],
)
def test_request_invariants(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(InvariantViolationError, match=message):
        request(**changes)


def test_result_defaults() -> None:
    served = result(provider="fake", cost_usd=Decimal("0.000001"), generation_id="gen-1")
    assert served.vectors == (UNIT,)
    assert (served.provider, served.cost_usd, served.generation_id) == (
        "fake",
        Decimal("0.000001"),
        "gen-1",
    )
    assert result().cost_usd is None
    assert result((1, 2.5)).vectors == ((1, 2.5),)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"vectors": [UNIT]}, "vectors must be tuple"),
        ({"vectors": ([1.0],)}, r"vectors\[0\] must be tuple"),
        ({"vectors": ((),)}, r"vectors\[0\] must not be empty"),
        ({"vectors": ((1.0, float("nan")),)}, r"vectors\[0\] must hold finite numbers"),
        ({"vectors": ((1.0, float("inf")),)}, r"vectors\[0\] must hold finite numbers"),
        ({"vectors": ((True,),)}, r"vectors\[0\] must hold finite numbers"),
        ({"vectors": (("0.1",),)}, r"vectors\[0\] must hold finite numbers"),
        ({"model": " "}, "model must not be blank"),
        ({"input_tokens": -1}, "input_tokens must be at least 0"),
        ({"provider": None}, "provider must be str"),
        ({"cost_usd": 0.1}, "cost_usd must be a Decimal"),
        ({"cost_usd": Decimal("NaN")}, "cost_usd must be a Decimal"),
        ({"generation_id": None}, "generation_id must be str"),
    ],
)
def test_result_invariants(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(InvariantViolationError, match=message):
        result(**changes)


def test_require_vectors_for_accepts_one_full_length_vector_per_input() -> None:
    served = result(UNIT, UNIT)
    assert require_vectors_for(served, 2) is served


def test_a_wrong_count_is_a_provider_response_error() -> None:
    with pytest.raises(ProviderResponseError, match="provider returned 1 vectors for 2 inputs"):
        require_vectors_for(result(UNIT), 2)


def test_a_wrong_length_is_a_provider_response_error() -> None:
    with pytest.raises(ProviderResponseError, match="vector 1 has 3 dimensions, expected 512"):
        require_vectors_for(result(UNIT, (0.0, 0.6, 0.8)), 2)


def test_provider_protocol_is_structural() -> None:
    class Stub:
        def embed(self, req: EmbeddingRequest) -> EmbeddingResult:
            return result(*(UNIT for _ in req.inputs))

    provider: EmbeddingProvider = Stub()
    assert len(provider.embed(request(inputs=("a", "b"))).vectors) == 2
