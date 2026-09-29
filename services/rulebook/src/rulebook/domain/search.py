"""Hybrid clause search: a lexical leg and a vector leg, fused by reciprocal rank.

Each leg ranks clauses on its own: the lexical leg by full-text rank over the clause text, the
vector leg by cosine distance between the query's embedding and the clauses' embeddings from the
same model. Reciprocal rank fusion adds ``1 / (RRF_K + rank)`` over the legs a clause appears
in, so neither leg's scores have to be comparable and a clause both legs rank well comes first.
Ties go to the smaller clause id, so the order is the same on every call.

Vectors from two models do not compare, so a clause keeps one embedding per model and the vector
leg compares the query only with embeddings from the model that embedded it.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

from domain_kernel._validation import require_int, require_text
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import ClauseId, RuleVersionId
from domain_kernel.vectors import EMBEDDING_DIMS, ClauseFilter, Vector
from rulebook.domain.errors import EmbeddingDimensionError
from rulebook.domain.graph import ClauseDetail

RRF_K: Final = 60
"""The rank offset of reciprocal rank fusion: the usual 60 keeps one leg's first place from
outweighing a clause both legs rank near the top."""
MAX_K: Final = 50


def validate_vector(vector: Sequence[float]) -> Vector:
    """The vector as a tuple when it has ``EMBEDDING_DIMS`` finite components, not all zero (a
    zero vector has no direction, so its cosine distance to anything is undefined)."""
    if len(vector) != EMBEDDING_DIMS:
        raise EmbeddingDimensionError(
            f"vectors have {EMBEDDING_DIMS} dimensions, this one has {len(vector)}"
        )
    values = tuple(float(component) for component in vector)
    if not all(math.isfinite(component) for component in values):
        raise InvariantViolationError("vector components must be finite numbers")
    if not any(values):
        raise InvariantViolationError("a zero vector has no direction")
    return values


@dataclass(frozen=True, slots=True)
class ClauseEmbedding:
    """One clause's vector; the model travels with the batch."""

    clause_id: ClauseId
    vector: Vector

    def __post_init__(self) -> None:
        validate_vector(self.vector)


@dataclass(frozen=True, slots=True)
class SearchQuery:
    """What to search for: the text for the lexical leg and, with the model that embedded it,
    the text's vector for the vector leg. ``filters.as_of`` keeps documents published on or
    before that date; undated documents are left out then."""

    text: str
    filters: ClauseFilter = field(default_factory=ClauseFilter)
    vector: Vector | None = None
    model: str | None = None
    k: int = 8

    def __post_init__(self) -> None:
        require_text(self.text, "text", strip=False)
        if not 1 <= require_int(self.k, "k") <= MAX_K:
            raise InvariantViolationError(f"k must be between 1 and {MAX_K}, got {self.k}")
        if self.vector is not None:
            validate_vector(self.vector)
            if self.model is None:
                raise InvariantViolationError("a vector needs the model that embedded it")


@dataclass(frozen=True, slots=True)
class FusedRank:
    clause_id: ClauseId
    score: float
    lexical_rank: int | None
    vector_rank: int | None


@dataclass(frozen=True, slots=True)
class CitedClause:
    """A clause with the published or superseded versions that cite it with a verified quote
    (in force on the query's ``as_of`` when it has one), and whether the rule it states is out of
    force on that date (``rulebook.domain.rule_versions.out_of_force``)."""

    detail: ClauseDetail
    cited_by: tuple[RuleVersionId, ...]
    out_of_force: bool = False


@dataclass(frozen=True, slots=True)
class SearchHit:
    detail: ClauseDetail
    score: float
    lexical_rank: int | None
    vector_rank: int | None
    cited_by: tuple[RuleVersionId, ...]
    out_of_force: bool = False


def fuse(lexical: Sequence[ClauseId], vector: Sequence[ClauseId], limit: int) -> list[FusedRank]:
    """The ``limit`` best clauses by reciprocal rank over both legs. Ranks start at 1; a clause
    listed twice in one leg keeps its first rank."""
    ranks: dict[ClauseId, list[int | None]] = {}
    for leg, ranked in enumerate((lexical, vector)):
        for rank, clause_id in enumerate(ranked, 1):
            slots = ranks.setdefault(clause_id, [None, None])
            if slots[leg] is None:
                slots[leg] = rank
    fused = [
        FusedRank(
            clause_id=clause_id,
            score=sum(1.0 / (RRF_K + rank) for rank in slots if rank is not None),
            lexical_rank=slots[0],
            vector_rank=slots[1],
        )
        for clause_id, slots in ranks.items()
    ]
    fused.sort(key=lambda hit: (-hit.score, str(hit.clause_id)))
    return fused[: max(limit, 0)]
