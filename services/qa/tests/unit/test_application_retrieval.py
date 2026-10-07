"""Hybrid search: the embedded question, the lexical fallback, no evidence."""

from collections.abc import Mapping
from datetime import date
from typing import Any

import pytest

from domain_kernel.ids import TenantId
from domain_kernel.vectors import Vector
from qa.application.retrieval import OUT_OF_FORCE, HybridLayer
from qa.domain.answer import Outcome, Reason
from qa.domain.errors import ModelBudgetExceededError, ModelResidencyRefusedError
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


class RefusedHere:
    """The gateway refusing the embedding under its residency policy."""

    def embed(
        self, text: str, *, tenant: TenantId | None, metadata: Mapping[str, str]
    ) -> QueryEmbedding:
        raise ModelResidencyRefusedError("llm-gateway refuses the call")


def test_an_embedding_refused_under_the_residency_policy_ends_the_question(world: World) -> None:
    """The answer's call would be refused too: no lexical search, no second call."""
    search = Search(world)
    hybrid = HybridLayer(search, RefusedHere(), world.answerer(), world.tracer)
    with pytest.raises(ModelResidencyRefusedError):
        hybrid.run(world.context("GSTR-3B March"))
    assert (search.asked, world.provider.requests) == ([], [])


def test_an_answer_refused_for_its_budget_ends_the_question(world: World) -> None:
    world.provider.add("q1", world.ANSWER, ModelBudgetExceededError("llm-gateway answered 429"))
    with pytest.raises(ModelBudgetExceededError):
        layer(world).run(world.context("GSTR-3B March"))


def test_a_clause_whose_rule_is_out_of_force_is_dropped(world: World) -> None:
    """Cited only by a version that ended before the question's date: dropped. A clause no
    version cites stays, dated by its document alone."""
    rulebook = world.rulebook
    ended = rulebook.add_clause(
        "The return in FORM GSTR-3B for the month of March, 2025 may be furnished till the "
        "22nd day of April, 2025.",
        external_ref="TEST-00",
        published_at=date(2025, 3, 1),
    )
    rule = rulebook.add_version(
        "gstr3b_extension_2025_03",
        effective_from=date(2025, 3, 1),
        effective_to=date(2025, 5, 1),
    )
    rulebook.cite(rule, ended, "may be furnished till the 22nd day of April, 2025")
    rulebook.add_clause(
        "A test circular on the GSTR-3B return for March.",
        external_ref="TEST-05",
        published_at=date(2026, 1, 1),
    )
    world.provider.add("q1", world.ANSWER, answer_text("", covered=False))
    question = "GSTR-3B March return furnished till April"
    layer(world).run(world.context(question))
    span = world.tracer.named("qa.retrieve")[0]
    assert (span.attributes[OUT_OF_FORCE], span.attributes["qa.retrieve.hits"]) == (1, 3)
    prompt = world.provider.requests[0].user
    assert ("TEST-00" in prompt, "TEST-02" in prompt, "TEST-05" in prompt) == (False, True, True)
    layer(world).run(world.context(question, as_of=date(2025, 4, 10)))
    assert OUT_OF_FORCE not in world.tracer.named("qa.retrieve")[1].attributes
    assert "TEST-00" in world.provider.requests[1].user


def test_no_hit_is_not_covered_without_a_model_call(world: World) -> None:
    answer = layer(world).run(world.context("What is the rate on cement?"))
    assert (answer.outcome, answer.reason) == (Outcome.NOT_COVERED, Reason.NO_EVIDENCE)
    assert world.provider.requests == []
