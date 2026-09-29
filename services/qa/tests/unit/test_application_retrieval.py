"""Hybrid search: the embedded question, the lexical fallback, no evidence."""

from collections.abc import Mapping
from datetime import date
from typing import Any

import pytest

from domain_kernel.ids import TenantId
from domain_kernel.vectors import Vector
from qa.application.retrieval import HybridLayer
from qa.domain.answer import Outcome, Reason
from qa.domain.errors import ModelBudgetExceededError
from qa.domain.records import QueryEmbedding, SearchHit
from qa.testing import FakeEmbedder, answer_text

World = Any


def layer(world: World) -> HybridLayer:
    return HybridLayer(world.rulebook, world.embedder, world.answerer(), world.tracer)


class Search:
    """The memory rulebook's search, keeping what it was asked."""

    def __init__(self, world: World) -> None:
        self.world = world
        self.asked: list[dict[str, Any]] = []

    def search(
        self,
        text: str,
        *,
        vector: Vector | None,
        model: str | None,
        as_of: date | None,
        k: int,
    ) -> tuple[SearchHit, ...]:
        self.asked.append({"text": text, "vector": vector, "model": model, "as_of": as_of, "k": k})
        found: tuple[SearchHit, ...] = self.world.rulebook.search(
            text, vector=vector, model=model, as_of=as_of, k=k
        )
        return found


def test_the_hits_are_answered_with_the_served_model(world: World) -> None:
    search = Search(world)
    world.provider.add(
        "q1", world.ANSWER, answer_text("By 24 April.", ("C1", world.EXTENSION_QUOTE))
    )
    hybrid = HybridLayer(search, world.embedder, world.answerer(), world.tracer)
    answer = hybrid.run(world.context("Was the March 2026 GSTR-3B extended?"))
    assert answer.outcome is Outcome.ANSWERED
    (asked,) = search.asked
    assert asked["model"] == FakeEmbedder.MODEL
    assert asked["vector"] is not None
    assert (asked["k"], asked["as_of"]) == (8, world.AS_OF)
    (span,) = world.tracer.named("qa.retrieve")
    assert span.attributes == {"qa.k": 8, "qa.retrieve.hits": 2}
    request = world.provider.requests[0]
    assert (request.metadata["layer"], "[C1] en.p3 (TEST-02)" in request.user) == ("hybrid", True)


def test_without_embeddings_the_search_is_lexical(world: World) -> None:
    world.embedder.fail = True
    search = Search(world)
    world.provider.add("q1", world.ANSWER, answer_text("", covered=False))
    hybrid = HybridLayer(search, world.embedder, world.answerer(), world.tracer)
    answer = hybrid.run(world.context("GSTR-3B March"))
    assert (answer.outcome, answer.reason) == (Outcome.NOT_COVERED, Reason.ANSWERER_DECLINED)
    assert (search.asked[0]["vector"], search.asked[0]["model"]) == (None, None)
    assert world.tracer.named("qa.retrieve")[0].attributes["qa.retrieve.lexical_only"] is True


class Refused:
    """The gateway refusing the embedding because a budget is used up."""

    def embed(
        self, text: str, *, tenant: TenantId | None, metadata: Mapping[str, str]
    ) -> QueryEmbedding:
        raise ModelBudgetExceededError("llm-gateway answered 429")


def test_an_embedding_refused_for_its_budget_leaves_the_search_lexical(world: World) -> None:
    search = Search(world)
    world.provider.add("q1", world.ANSWER, answer_text("", covered=False))
    hybrid = HybridLayer(search, Refused(), world.answerer(), world.tracer)
    answer = hybrid.run(world.context("GSTR-3B March"))
    assert answer.reason is Reason.ANSWERER_DECLINED
    assert search.asked[0]["vector"] is None
    assert world.tracer.named("qa.retrieve")[0].attributes["qa.retrieve.lexical_only"] is True


def test_an_answer_refused_for_its_budget_ends_the_question(world: World) -> None:
    world.provider.add("q1", world.ANSWER, ModelBudgetExceededError("llm-gateway answered 429"))
    with pytest.raises(ModelBudgetExceededError):
        layer(world).run(world.context("GSTR-3B March"))


def test_no_hit_is_not_covered_without_a_model_call(world: World) -> None:
    answer = layer(world).run(world.context("What is the rate on cement?"))
    assert (answer.outcome, answer.reason) == (Outcome.NOT_COVERED, Reason.NO_EVIDENCE)
    assert world.provider.requests == []
