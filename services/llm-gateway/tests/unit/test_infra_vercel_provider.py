"""The Vercel adapter against a stub SDK client: request shape, parsing, error mapping."""

from decimal import Decimal
from types import MappingProxyType
from typing import Any, cast

import httpx2
import pytest
from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
    RateLimitError,
    omit,
)
from openai.types import CreateEmbeddingResponse
from openai.types.chat import ChatCompletion

from domain_kernel.llm import CompletionRequest
from domain_kernel.vectors import EMBEDDING_DIMS
from llm_gateway.domain.embeddings import EmbeddingRequest, EmbeddingResult
from llm_gateway.domain.errors import (
    BudgetExceededError,
    ProviderResponseError,
    ProviderUnavailableError,
    UnknownFeatureError,
)
from llm_gateway.domain.features import Feature
from llm_gateway.domain.providers import ProviderResponse
from llm_gateway.domain.routing import DEFAULT_ROUTES
from llm_gateway.infrastructure.providers.vercel import VercelGatewayProvider

PRIMARY = DEFAULT_ROUTES[Feature.EXTRACTION].primary
FALLBACK = DEFAULT_ROUTES[Feature.EXTRACTION].models[1]
QA_PRIMARY = DEFAULT_ROUTES[Feature.QA].primary
QA_FALLBACK = DEFAULT_ROUTES[Feature.QA].models[1]
RETRIEVAL = DEFAULT_ROUTES[Feature.RETRIEVAL].primary
REQUEST = httpx2.Request("POST", "https://ai-gateway.vercel.sh/v1/chat/completions")
GATEWAY_METADATA: dict[str, Any] = {
    "cost": "0.000123",
    "generationId": "gen-1",
    "routing": {"finalProvider": "deepinfra"},
}


# ---- stub client ------------------------------------------------------------------------------


class Completions:
    def __init__(self, outcomes: list[ChatCompletion | Exception]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> ChatCompletion:
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class Chat:
    def __init__(self, completions: Completions) -> None:
        self.completions = completions


class StubClient:
    def __init__(self, *outcomes: ChatCompletion | Exception) -> None:
        self.completions = Completions(list(outcomes))
        self.chat = Chat(self.completions)


def provider(
    *outcomes: ChatCompletion | Exception, zero_data_retention: bool = True
) -> tuple[VercelGatewayProvider, Completions]:
    stub = StubClient(*outcomes)
    adapter = VercelGatewayProvider(
        cast(OpenAI, stub), routes=DEFAULT_ROUTES, zero_data_retention=zero_data_retention
    )
    return adapter, stub.completions


def completion(
    content: str | None = "hi",
    *,
    model: str = PRIMARY,
    gateway: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
    usage: bool = True,
    prompt_tokens: int = 10,
    completion_tokens: int = 2,
    choices: bool = True,
) -> ChatCompletion:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if gateway is not None:
        message["provider_metadata"] = {"gateway": gateway}
    if extra is not None:
        message.update(extra)
    payload: dict[str, Any] = {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1,
        "model": model,
        "choices": [{"index": 0, "finish_reason": "stop", "message": message}] if choices else [],
    }
    if usage:
        payload["usage"] = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }
    return ChatCompletion.model_validate(payload)


def status_error(
    status: int,
    *,
    code: str | None = None,
    headers: dict[str, str] | None = None,
    kind: type[APIStatusError] = APIStatusError,
) -> APIStatusError:
    """Built the way the SDK does it: the nested ``error`` object is the body."""
    body: dict[str, Any] = {"message": "boom", "type": code, "code": code}
    response = httpx2.Response(status, request=REQUEST, headers=headers or {}, json={"error": body})
    return kind("boom", response=response, body=body)


def request(**changes: Any) -> CompletionRequest:
    fields: dict[str, Any] = {
        "feature": "extraction",
        "prompt_version": "extraction.rule_candidate@0",
        "system": "Extract rules.",
        "user": "Section 7 says the return is due monthly.",
        "model": PRIMARY,
    }
    fields.update(changes)
    return CompletionRequest(**fields)


# ---- request shape ----------------------------------------------------------------------------


def test_extraction_sends_the_route_options_and_a_strict_schema() -> None:
    vercel, completions = provider(completion())
    schema = MappingProxyType(
        {
            "type": "object",
            "properties": MappingProxyType({"n": {"type": "integer"}}),
            "required": ("n",),
        }
    )
    vercel.complete(request(json_schema=schema))

    [call] = completions.calls
    assert call["model"] == PRIMARY
    assert call["messages"] == [
        {"role": "system", "content": "Extract rules."},
        {"role": "user", "content": "Section 7 says the return is due monthly."},
    ]
    assert (call["temperature"], call["max_tokens"], call["timeout"]) == (0.0, 1024, 120.0)
    assert call["extra_body"] == {
        "providerOptions": {
            "gateway": {
                "zeroDataRetention": True,
                "only": ["deepinfra", "parasail", "digitalocean", "morph", "togetherai"],
                "has": ["structured-output"],
                "models": [FALLBACK],
            }
        },
        "reasoning": {"effort": "none"},
    }
    assert call["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "extraction_rule_candidate_0",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {"n": {"type": "integer"}},
                "required": ["n"],
            },
        },
    }
    sent = call["response_format"]["json_schema"]["schema"]
    assert type(sent) is dict
    assert type(sent["properties"]) is dict
    assert type(sent["required"]) is list


def test_qa_sends_sort_ttft_and_only_a_user_message_when_system_is_empty() -> None:
    vercel, completions = provider(completion(model=QA_PRIMARY))
    vercel.complete(request(feature="qa", prompt_version="qa.answer@1", system="", model=None))

    [call] = completions.calls
    assert call["model"] == QA_PRIMARY
    assert call["messages"] == [
        {"role": "user", "content": "Section 7 says the return is due monthly."}
    ]
    assert call["timeout"] == 8.0
    assert call["extra_body"]["providerOptions"]["gateway"]["sort"] == "ttft"
    assert call["extra_body"]["providerOptions"]["gateway"]["models"] == [QA_FALLBACK]
    assert call["extra_body"]["reasoning"] == {"effort": "none"}
    assert call["response_format"] is omit


def test_a_route_without_filters_sends_only_zero_data_retention() -> None:
    vercel, completions = provider(completion(model="fake/echo"), zero_data_retention=False)
    vercel.complete(request(feature="smoke", prompt_version="smoke.echo@1", model="fake/echo"))

    [call] = completions.calls
    assert call["extra_body"] == {"providerOptions": {"gateway": {"zeroDataRetention": False}}}
    assert call["timeout"] == 5.0


def test_the_fallback_attempt_sends_no_gateway_models() -> None:
    vercel, completions = provider(completion(model=FALLBACK))
    vercel.complete(request(model=FALLBACK))
    [call] = completions.calls
    assert "models" not in call["extra_body"]["providerOptions"]["gateway"]


def test_a_model_outside_the_route_gets_zero_data_retention_only() -> None:
    """An override keeps the route's timeout and schema but not its filters, sort or reasoning."""
    vercel, completions = provider(completion(model="zai/glm-4.7-flash"))
    vercel.complete(request(model="zai/glm-4.7-flash", json_schema={"type": "object"}))
    [call] = completions.calls
    assert call["model"] == "zai/glm-4.7-flash"
    assert call["extra_body"] == {"providerOptions": {"gateway": {"zeroDataRetention": True}}}
    assert call["timeout"] == 120.0
    assert call["response_format"]["type"] == "json_schema"


def test_a_model_outside_the_qa_route_drops_sort_and_reasoning() -> None:
    vercel, completions = provider(completion(model=PRIMARY), zero_data_retention=False)
    vercel.complete(request(feature="qa", prompt_version="qa.answer@1", model=PRIMARY))
    [call] = completions.calls
    assert call["extra_body"] == {"providerOptions": {"gateway": {"zeroDataRetention": False}}}
    assert call["timeout"] == 8.0


def test_a_long_prompt_reference_gives_a_bounded_schema_name() -> None:
    vercel, completions = provider(completion())
    name = "extraction." + "a" * 80
    vercel.complete(request(prompt_version=f"{name}@1", json_schema={"type": "object"}))
    [call] = completions.calls
    sent = call["response_format"]["json_schema"]["name"]
    assert sent == ("extraction_" + "a" * 80 + "_1")[:64]
    assert len(sent) == 64


def test_an_unknown_feature_is_refused_before_any_call() -> None:
    vercel, completions = provider(completion())
    with pytest.raises(UnknownFeatureError):
        vercel.complete(request(feature="haiku"))
    assert completions.calls == []


# ---- response parsing -------------------------------------------------------------------------


def test_parses_text_tokens_cost_provider_and_generation_id() -> None:
    vercel, _ = provider(completion(gateway=GATEWAY_METADATA))
    response = vercel.complete(request())
    assert response == ProviderResponse(
        text="hi",
        model=PRIMARY,
        input_tokens=10,
        output_tokens=2,
        provider="deepinfra",
        cost_usd=Decimal("0.000123"),
        generation_id="gen-1",
    )
    assert response.cached is False
    assert response.trace_id == ""


def test_the_served_model_comes_from_the_answer() -> None:
    vercel, _ = provider(completion(model=FALLBACK, gateway=GATEWAY_METADATA))
    assert vercel.complete(request()).model == FALLBACK


def test_missing_gateway_metadata_falls_back_to_defaults() -> None:
    vercel, _ = provider(completion())
    response = vercel.complete(request())
    assert (response.provider, response.cost_usd, response.generation_id) == (
        "vercel",
        None,
        "chatcmpl-1",
    )


@pytest.mark.parametrize(
    "extra",
    [
        {"provider_metadata": "not a mapping"},
        {"provider_metadata": {"gateway": "not a mapping"}},
        {"provider_metadata": {"gateway": {"routing": "deepinfra", "generationId": 5}}},
        {"provider_metadata": {"gateway": {"routing": {"finalProvider": 7}}}},
    ],
)
def test_partial_or_malformed_metadata_falls_back_to_defaults(extra: dict[str, Any]) -> None:
    vercel, _ = provider(completion(extra=extra))
    response = vercel.complete(request())
    assert (response.provider, response.cost_usd, response.generation_id) == (
        "vercel",
        None,
        "chatcmpl-1",
    )


@pytest.mark.parametrize("cost", ["abc", "-1", "nan", "Infinity", True, None, {"usd": 1}, [1]])
def test_an_unusable_cost_is_left_to_the_estimate(cost: object) -> None:
    vercel, _ = provider(completion(gateway={"cost": cost}))
    assert vercel.complete(request()).cost_usd is None


@pytest.mark.parametrize(
    ("cost", "expected"),
    [
        ("0.0005", "0.000500"),
        (0.0005, "0.000500"),
        (0, "0.000000"),
        ("0.0000004", "0.000000"),
        ("0.0000005", "0.000001"),
    ],
)
def test_the_cost_is_quantised_to_six_places(cost: object, expected: str) -> None:
    vercel, _ = provider(completion(gateway={"cost": cost}))
    assert str(vercel.complete(request()).cost_usd) == expected


def test_empty_choices_are_a_response_error() -> None:
    vercel, _ = provider(completion(choices=False))
    with pytest.raises(ProviderResponseError, match="no choices"):
        vercel.complete(request())


def test_null_content_is_a_response_error() -> None:
    vercel, _ = provider(completion(content=None))
    with pytest.raises(ProviderResponseError, match="without content"):
        vercel.complete(request())


def test_missing_usage_gives_zero_tokens() -> None:
    vercel, _ = provider(completion(usage=False))
    response = vercel.complete(request())
    assert (response.input_tokens, response.output_tokens) == (0, 0)


def test_a_blank_model_in_the_answer_falls_back_to_the_requested_one() -> None:
    vercel, _ = provider(completion(model="  "))
    assert vercel.complete(request()).model == PRIMARY


def test_negative_tokens_are_a_response_error() -> None:
    vercel, _ = provider(completion(prompt_tokens=-1))
    with pytest.raises(ProviderResponseError, match="malformed"):
        vercel.complete(request())


# ---- error mapping ----------------------------------------------------------------------------


def test_a_gateway_quota_is_a_budget_error_with_the_gateway_scope() -> None:
    vercel, _ = provider(status_error(402, code="quota_for_entity_exceeded"))
    with pytest.raises(BudgetExceededError) as info:
        vercel.complete(request())
    assert info.value.scope == "gateway"
    assert info.value.detail == "gateway quota exceeded"
    assert info.value.problem_headers == {}
    assert isinstance(info.value.__cause__, APIStatusError)


def test_any_other_402_means_no_credits() -> None:
    vercel, _ = provider(status_error(402, code="insufficient_credits"))
    with pytest.raises(ProviderUnavailableError, match="no credits"):
        vercel.complete(request())


def test_a_rate_limit_carries_retry_after() -> None:
    vercel, _ = provider(status_error(429, headers={"retry-after": "7"}, kind=RateLimitError))
    with pytest.raises(ProviderUnavailableError, match="rate limit") as info:
        vercel.complete(request())
    assert info.value.retry_after_seconds == 7.0
    assert info.value.problem_headers == {"Retry-After": "7"}


@pytest.mark.parametrize(
    "headers", [{}, {"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"}, {"retry-after": "-3"}]
)
def test_a_rate_limit_without_a_usable_retry_after(headers: dict[str, str]) -> None:
    vercel, _ = provider(status_error(429, headers=headers))
    with pytest.raises(ProviderUnavailableError) as info:
        vercel.complete(request())
    assert info.value.retry_after_seconds is None


@pytest.mark.parametrize("status", [401, 403, 404, 408, 409, 500, 502, 503, 504])
def test_outages_and_auth_failures_are_unavailable(status: int) -> None:
    vercel, _ = provider(status_error(status))
    with pytest.raises(ProviderUnavailableError) as info:
        vercel.complete(request())
    assert info.value.detail == f"gateway returned {status}"
    assert info.value.retry_after_seconds is None


def test_a_5xx_retry_after_is_kept() -> None:
    vercel, _ = provider(status_error(503, headers={"retry-after": "2.5"}))
    with pytest.raises(ProviderUnavailableError) as info:
        vercel.complete(request())
    assert info.value.retry_after_seconds == 2.5
    assert info.value.problem_headers == {"Retry-After": "3"}


def test_no_providers_available_is_unavailable() -> None:
    vercel, _ = provider(status_error(400, code="no_providers_available"))
    with pytest.raises(ProviderUnavailableError, match="no gateway host"):
        vercel.complete(request())


@pytest.mark.parametrize("status", [400, 422])
def test_bad_requests_are_response_errors(status: int) -> None:
    vercel, _ = provider(status_error(status, code="invalid_request"))
    with pytest.raises(ProviderResponseError, match="rejected the request"):
        vercel.complete(request())


def test_an_unexpected_status_is_a_response_error() -> None:
    vercel, _ = provider(status_error(418))
    with pytest.raises(ProviderResponseError, match="gateway returned 418"):
        vercel.complete(request())


def test_connection_errors_and_timeouts_are_unavailable() -> None:
    vercel, _ = provider(
        APIConnectionError(message="refused", request=REQUEST), APITimeoutError(request=REQUEST)
    )
    with pytest.raises(ProviderUnavailableError, match="unreachable: refused"):
        vercel.complete(request())
    with pytest.raises(ProviderUnavailableError, match="unreachable"):
        vercel.complete(request())


def test_a_bare_sdk_error_is_a_response_error() -> None:
    vercel, _ = provider(APIError("odd", REQUEST, body=None))
    with pytest.raises(ProviderResponseError, match="gateway error: odd"):
        vercel.complete(request())


def test_error_codes_are_read_wherever_the_body_puts_them() -> None:
    flat = APIStatusError(
        "boom",
        response=httpx2.Response(402, request=REQUEST),
        body={"code": "quota_for_entity_exceeded"},
    )
    nested_only = APIStatusError(
        "boom",
        response=httpx2.Response(402, request=REQUEST),
        body={"error": {"type": "quota_for_entity_exceeded"}},
    )
    no_body = APIStatusError("boom", response=httpx2.Response(402, request=REQUEST), body=None)
    vercel, _ = provider(flat, nested_only, no_body)
    for _ in range(2):
        with pytest.raises(BudgetExceededError):
            vercel.complete(request())
    with pytest.raises(ProviderUnavailableError):
        vercel.complete(request())


def test_other_exceptions_pass_through_untouched() -> None:
    vercel, _ = provider(RuntimeError("bug"))
    with pytest.raises(RuntimeError, match="bug"):
        vercel.complete(request())


# ---- embeddings -------------------------------------------------------------------------------


class Embeddings:
    def __init__(self, outcomes: list[CreateEmbeddingResponse | Exception]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> CreateEmbeddingResponse:
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class EmbeddingClient:
    def __init__(self, *outcomes: CreateEmbeddingResponse | Exception) -> None:
        self.embeddings = Embeddings(list(outcomes))


def embedder(
    *outcomes: CreateEmbeddingResponse | Exception,
    zero_data_retention: bool = True,
    embedding_dimensions_param: bool = True,
) -> tuple[VercelGatewayProvider, Embeddings]:
    stub = EmbeddingClient(*outcomes)
    adapter = VercelGatewayProvider(
        cast(OpenAI, stub),
        routes=DEFAULT_ROUTES,
        zero_data_retention=zero_data_retention,
        embedding_dimensions_param=embedding_dimensions_param,
    )
    return adapter, stub.embeddings


def vector(slot: int) -> list[float]:
    values = [0.0] * EMBEDDING_DIMS
    values[slot] = 1.0
    return values


def embeddings(
    *slots: int,
    indexes: list[int] | None = None,
    model: str = RETRIEVAL,
    gateway: dict[str, Any] | None = None,
    usage: bool = True,
) -> CreateEmbeddingResponse:
    """One unit vector per slot; ``indexes`` defaults to the slots' order."""
    order = indexes if indexes is not None else list(range(len(slots)))
    payload: dict[str, Any] = {
        "object": "list",
        "model": model,
        "data": [
            {"object": "embedding", "index": index, "embedding": vector(slot)}
            for index, slot in zip(order, slots, strict=True)
        ],
    }
    if gateway is not None:
        payload["provider_metadata"] = {"gateway": gateway}
    if not usage:
        return CreateEmbeddingResponse.model_construct(**payload)
    payload["usage"] = {"prompt_tokens": 12, "total_tokens": 12}
    return CreateEmbeddingResponse.model_validate(payload)


def embedding_request(*inputs: str, model: str | None = None) -> EmbeddingRequest:
    return EmbeddingRequest(feature="retrieval", inputs=inputs or ("Section 7.",), model=model)


def test_embed_sends_float_512_dimensions_and_zero_data_retention() -> None:
    vercel, calls = embedder(embeddings(0, 1))
    vercel.embed(embedding_request("Section 7.", "Section 8."))

    [call] = calls.calls
    assert call == {
        "model": RETRIEVAL,
        "input": ["Section 7.", "Section 8."],
        "dimensions": 512,
        "encoding_format": "float",
        "extra_body": {"providerOptions": {"gateway": {"zeroDataRetention": True}}},
        "timeout": 15.0,
    }


def test_embed_can_leave_out_the_dimensions_parameter() -> None:
    vercel, calls = embedder(
        embeddings(0, model="voyage/voyage-3.5"),
        zero_data_retention=False,
        embedding_dimensions_param=False,
    )
    vercel.embed(embedding_request(model="voyage/voyage-3.5"))
    [call] = calls.calls
    assert call["model"] == "voyage/voyage-3.5"
    assert call["dimensions"] is omit
    assert call["extra_body"] == {"providerOptions": {"gateway": {"zeroDataRetention": False}}}
    assert call["timeout"] == 15.0


def test_embed_parses_vectors_in_input_order_with_cost_and_host() -> None:
    gateway = {"cost": "0.000004", "generationId": "gen-7", "routing": {"finalProvider": "voyage"}}
    vercel, _ = embedder(embeddings(5, 9, indexes=[1, 0], gateway=gateway))
    result = vercel.embed(embedding_request("a", "b"))
    assert result == EmbeddingResult(
        vectors=(tuple(vector(9)), tuple(vector(5))),
        model=RETRIEVAL,
        input_tokens=12,
        provider="voyage",
        cost_usd=Decimal("0.000004"),
        generation_id="gen-7",
    )


def test_embed_without_metadata_or_usage_falls_back_to_defaults() -> None:
    vercel, _ = embedder(embeddings(0, model=" ", usage=False))
    result = vercel.embed(embedding_request())
    assert (result.model, result.provider, result.cost_usd, result.generation_id) == (
        RETRIEVAL,
        "vercel",
        None,
        "",
    )
    assert result.input_tokens == 0


@pytest.mark.parametrize("indexes", [[0], [0, 0], [1, 2], []])
def test_embed_refuses_answers_that_do_not_cover_every_input(indexes: list[int]) -> None:
    response = embeddings(*range(len(indexes)), indexes=indexes)
    vercel, _ = embedder(response)
    with pytest.raises(ProviderResponseError, match="embeddings for indexes"):
        vercel.embed(embedding_request("a", "b"))


def test_an_empty_vector_is_a_response_error() -> None:
    response = CreateEmbeddingResponse.model_validate(
        {
            "object": "list",
            "model": RETRIEVAL,
            "data": [{"object": "embedding", "index": 0, "embedding": []}],
            "usage": {"prompt_tokens": 1, "total_tokens": 1},
        }
    )
    vercel, _ = embedder(response)
    with pytest.raises(ProviderResponseError, match="malformed"):
        vercel.embed(embedding_request())


def test_embed_maps_sdk_errors_like_completions() -> None:
    vercel, _ = embedder(
        status_error(429, headers={"retry-after": "3"}, kind=RateLimitError),
        status_error(400, code="invalid_request"),
        APIConnectionError(message="refused", request=REQUEST),
    )
    with pytest.raises(ProviderUnavailableError, match="rate limit") as info:
        vercel.embed(embedding_request())
    assert info.value.retry_after_seconds == 3.0
    with pytest.raises(ProviderResponseError, match="rejected the request"):
        vercel.embed(embedding_request())
    with pytest.raises(ProviderUnavailableError, match="unreachable"):
        vercel.embed(embedding_request())


# ---- construction -----------------------------------------------------------------------------


def test_from_settings_builds_the_sdk_client() -> None:
    vercel = VercelGatewayProvider.from_settings(
        base_url="https://example.test/v1",
        api_key="placeholder",
        timeout=60.0,
        max_retries=1,
        routes=DEFAULT_ROUTES,
        zero_data_retention=True,
    )
    client = vercel.client
    assert isinstance(client, OpenAI)
    assert str(client.base_url) == "https://example.test/v1/"
    assert client.max_retries == 1
    assert client.timeout == 60.0
    assert client.api_key == "placeholder"
