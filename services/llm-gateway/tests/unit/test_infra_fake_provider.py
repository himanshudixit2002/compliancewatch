"""The deterministic fake: same request, same answer; schema placeholders; injected failures."""

import hashlib
import json
import math
from types import MappingProxyType
from typing import Any

import pytest

from domain_kernel.errors import InvariantViolationError
from domain_kernel.llm import CompletionRequest
from llm_gateway.domain.errors import ProviderUnavailableError
from llm_gateway.domain.providers import ProviderResponse
from llm_gateway.infrastructure.providers.fake import JUDGEMENT_TEXT, FakeProvider


def request(**changes: Any) -> CompletionRequest:
    fields: dict[str, Any] = {
        "feature": "smoke",
        "prompt_version": "smoke.echo@1",
        "system": "",
        "user": "hello there",
    }
    fields.update(changes)
    return CompletionRequest(**fields)


def test_echoes_the_tail_of_the_user_text_deterministically() -> None:
    provider = FakeProvider()
    user = "x" * 300 + "tail"
    first = provider.complete(request(user=user))
    second = provider.complete(request(user=user))

    assert first == second
    assert isinstance(first, ProviderResponse)
    assert first.text == "fake:" + user[-200:]
    assert (first.model, first.provider, first.cost_usd, first.cached) == (
        "fake/echo",
        "fake",
        None,
        False,
    )
    assert first.generation_id == "fake-" + hashlib.sha256(first.text.encode()).hexdigest()[:16]
    assert provider.calls == 2


def test_token_counts_round_up_four_characters_per_token() -> None:
    response = FakeProvider().complete(request(system="ab", user="cde"))
    assert response.input_tokens == 2
    assert response.output_tokens == math.ceil(len(response.text) / 4)
    long = FakeProvider().complete(request(user="w" * 4032))
    assert (long.input_tokens, long.output_tokens) == (1008, 52)


def test_serves_the_model_id_the_request_names() -> None:
    assert FakeProvider().complete(request(model="fake/other")).model == "fake/other"


def test_judgement_gets_an_unsure_verdict() -> None:
    response = FakeProvider().complete(
        request(feature="judgement", prompt_version="judgement.applies@1")
    )
    assert response.text == JUDGEMENT_TEXT
    assert json.loads(response.text) == {"confidence": 0.5, "result": "unsure"}


def test_schema_gets_a_placeholder_for_every_required_field() -> None:
    schema = MappingProxyType(
        {
            "type": "object",
            "required": [
                "title",
                "score",
                "count",
                "ok",
                "tags",
                "extra",
                "mystery",
                "kind",
                "when",
            ],
            "properties": {
                "title": {"type": "string"},
                "score": {"type": "number"},
                "count": {"type": "integer"},
                "ok": {"type": "boolean"},
                "tags": {"type": "array"},
                "extra": {"type": "object"},
                "mystery": {"description": "no type"},
                "kind": {"type": "string", "enum": ["notification", "circular"]},
                "when": {"type": ["string", "null"], "format": "date"},
                "optional": {"type": "string"},
            },
        }
    )
    response = FakeProvider().complete(
        request(
            feature="extraction", prompt_version="extraction.rule_candidate@1", json_schema=schema
        )
    )
    assert json.loads(response.text) == {
        "title": "placeholder",
        "score": 0.0,
        "count": 0,
        "ok": False,
        "tags": [],
        "extra": {},
        "mystery": None,
        "kind": "notification",
        "when": None,
    }


def test_schema_without_required_fields_gives_an_empty_object() -> None:
    schema = {"type": "object", "properties": {"a": {"type": "string"}}}
    assert FakeProvider().complete(request(json_schema=schema)).text == "{}"


def test_schema_wins_over_the_judgement_verdict() -> None:
    schema = {"required": ["verdict"], "properties": {"verdict": {"type": "string"}}}
    response = FakeProvider().complete(request(feature="judgement", json_schema=schema))
    assert json.loads(response.text) == {"verdict": "placeholder"}


def test_required_entries_that_are_not_names_are_skipped() -> None:
    schema = {"required": ["a", 7], "properties": "not a mapping"}
    response = FakeProvider().complete(request(json_schema=schema))
    assert json.loads(response.text) == {"a": None}


def test_fail_next_raises_for_the_next_calls_only() -> None:
    provider = FakeProvider()
    provider.fail_next(2)
    with pytest.raises(ProviderUnavailableError, match="injected failure"):
        provider.complete(request())
    with pytest.raises(ProviderUnavailableError):
        provider.complete(request())
    assert provider.complete(request()).text.startswith("fake:")
    assert provider.calls == 3


def test_fail_next_defaults_to_one_and_rejects_negative_counts() -> None:
    provider = FakeProvider()
    provider.fail_next()
    with pytest.raises(ProviderUnavailableError):
        provider.complete(request())
    assert provider.complete(request()).provider == "fake"
    with pytest.raises(InvariantViolationError):
        provider.fail_next(-1)
