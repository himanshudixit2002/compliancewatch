"""The fake embedder: deterministic hashed features, unit length, lexical nearness."""

import hashlib
import math

import pytest

from domain_kernel.vectors import EMBEDDING_DIMS, Vector
from llm_gateway.domain.embeddings import EmbeddingRequest
from llm_gateway.domain.errors import ProviderUnavailableError
from llm_gateway.infrastructure.providers.fake import EMBEDDING_MODEL, FakeProvider, hash_embedding

PINNED_TEXT = "The registered person shall furnish the return. The return is due monthly."
PINNED_SHA256 = "cc2dc00c358ed5210c0199ac99ebde742202d5923c59536e619f6e93e269400b"
"""Over the components at six places, so a last-digit libm difference cannot move it. A change
to the features, weights or hashing changes every stored fake vector: bump it deliberately."""


def _checksum(vector: Vector) -> str:
    return hashlib.sha256(",".join(f"{c:.6f}" for c in vector).encode()).hexdigest()


def _cosine(a: Vector, b: Vector) -> float:
    return math.fsum(x * y for x, y in zip(a, b, strict=True))


def _request(*inputs: str, model: str | None = None) -> EmbeddingRequest:
    return EmbeddingRequest(feature="retrieval", inputs=inputs, model=model)


def test_the_pinned_vector() -> None:
    vector = hash_embedding(PINNED_TEXT)
    assert len(vector) == EMBEDDING_DIMS
    assert _checksum(vector) == PINNED_SHA256
    assert hash_embedding(PINNED_TEXT) == vector


@pytest.mark.parametrize(
    "text",
    [PINNED_TEXT, "a", "return return return", "\u0915\u0930 \u0935\u093e\u092a\u0938\u0940"],
)
def test_every_vector_has_unit_length(text: str) -> None:
    vector = hash_embedding(text)
    assert math.isclose(math.fsum(c * c for c in vector), 1.0, rel_tol=1e-12)
    assert all(isinstance(c, float) and math.isfinite(c) for c in vector)


def test_shared_words_score_closer_than_unrelated_text() -> None:
    query = hash_embedding("When is the return due?")
    near = hash_embedding("The return is due on the twentieth of the following month.")
    far = hash_embedding("Input tax credit on capital goods is available in instalments.")
    assert _cosine(query, near) > 0.4
    assert _cosine(query, near) > _cosine(query, far) + 0.3


def test_case_and_width_do_not_matter() -> None:
    assert hash_embedding("RETURN due") == hash_embedding("return DUE")
    assert hash_embedding("\uff32\uff25\uff34\uff35\uff32\uff2e") == hash_embedding("return")


def test_text_without_features_gets_its_own_unit_vector() -> None:
    dots = hash_embedding("...!!!")
    assert sorted(c for c in dots if c) == [1.0]
    assert (
        dots.index(1.0)
        == int.from_bytes(hashlib.blake2b(b"...!!!", digest_size=8).digest(), "big")
        % EMBEDDING_DIMS
    )
    assert hash_embedding("???") != dots


def test_devanagari_words_are_features() -> None:
    refund = hash_embedding("\u0915\u0930 \u0935\u093e\u092a\u0938\u0940")
    assert sum(1 for c in refund if c) > 2
    assert _cosine(refund, hash_embedding("\u0915\u0930")) > 0.3


def test_embed_serves_the_fake_model_whatever_was_asked() -> None:
    provider = FakeProvider()
    result = provider.embed(_request("first clause", "second", model="voyage/voyage-3.5-lite"))
    assert result.model == EMBEDDING_MODEL == "fake/hash-ngram-512"
    assert result.vectors == (hash_embedding("first clause"), hash_embedding("second"))
    assert (result.input_tokens, result.provider, result.cost_usd) == (5, "fake", None)
    assert result.generation_id.startswith("fake-")
    assert provider.embed(_request("first clause", "second")) == result
    assert provider.calls == 2


def test_embed_shares_the_injected_failures() -> None:
    provider = FakeProvider()
    provider.fail_next(1)
    with pytest.raises(ProviderUnavailableError, match="injected failure"):
        provider.embed(_request("a"))
    assert len(provider.embed(_request("a")).vectors) == 1
