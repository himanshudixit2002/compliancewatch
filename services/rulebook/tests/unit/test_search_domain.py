"""Reciprocal rank fusion, vector checks and the search query's rules."""

import math
from uuid import UUID

import pytest

from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import ClauseId
from domain_kernel.vectors import EMBEDDING_DIMS
from rulebook.application.search import pool_size
from rulebook.domain.errors import EmbeddingDimensionError
from rulebook.domain.search import RRF_K, ClauseEmbedding, SearchQuery, fuse, validate_vector

A, B, C, D = (ClauseId(UUID(int=n)) for n in (1, 2, 3, 4))


def unit(index: int) -> tuple[float, ...]:
    return tuple(1.0 if i == index else 0.0 for i in range(EMBEDDING_DIMS))


def test_fusion_adds_reciprocal_ranks_over_both_legs() -> None:
    fused = fuse([A, B, C], [C, D], limit=10)
    assert [hit.clause_id for hit in fused] == [C, A, B, D]
    by_id = {hit.clause_id: hit for hit in fused}
    assert by_id[C].score == pytest.approx(1 / (RRF_K + 3) + 1 / (RRF_K + 1))
    assert (by_id[C].lexical_rank, by_id[C].vector_rank) == (3, 1)
    assert (by_id[A].lexical_rank, by_id[A].vector_rank) == (1, None)
    assert (by_id[D].lexical_rank, by_id[D].vector_rank) == (None, 2)


def test_ties_go_to_the_smaller_clause_id() -> None:
    fused = fuse([B], [A], limit=10)
    assert [hit.clause_id for hit in fused] == [A, B]
    assert fused[0].score == fused[1].score


def test_fusion_keeps_the_first_rank_and_the_limit() -> None:
    fused = fuse([A, A, B], [], limit=1)
    assert [(hit.clause_id, hit.lexical_rank) for hit in fused] == [(A, 1)]
    assert fuse([], [], limit=5) == []
    assert fuse([A], [B], limit=0) == []


def test_a_vector_has_the_stored_dimensions() -> None:
    assert validate_vector(list(unit(3))) == unit(3)
    with pytest.raises(EmbeddingDimensionError):
        validate_vector([1.0] * (EMBEDDING_DIMS - 1))
    with pytest.raises(EmbeddingDimensionError):
        ClauseEmbedding(A, (1.0,) * (EMBEDDING_DIMS + 1))


@pytest.mark.parametrize("bad", [math.nan, math.inf])
def test_a_vector_is_finite(bad: float) -> None:
    with pytest.raises(InvariantViolationError, match="finite"):
        validate_vector((bad, *unit(0)[1:]))


def test_a_zero_vector_is_refused() -> None:
    with pytest.raises(InvariantViolationError, match="zero vector"):
        validate_vector((0.0,) * EMBEDDING_DIMS)


def test_a_query_vector_names_its_model() -> None:
    assert SearchQuery("due date", vector=unit(0), model="fake/hash-ngram-512").k == 8
    with pytest.raises(InvariantViolationError, match="model"):
        SearchQuery("due date", vector=unit(0))


@pytest.mark.parametrize("k", [0, 51])
def test_k_is_between_1_and_50(k: int) -> None:
    with pytest.raises(InvariantViolationError):
        SearchQuery("due date", k=k)


def test_a_query_has_text() -> None:
    with pytest.raises(InvariantViolationError):
        SearchQuery("   ")


@pytest.mark.parametrize(("k", "pool"), [(1, 40), (8, 40), (10, 40), (11, 44), (50, 200)])
def test_each_leg_draws_a_pool_larger_than_k(k: int, pool: int) -> None:
    assert pool_size(k) == pool
