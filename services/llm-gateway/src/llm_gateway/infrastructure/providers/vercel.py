"""The Vercel AI Gateway through the openai SDK: one key, many models, one OpenAI-compatible API.

The gateway's own options travel in ``extra_body``: host filters, zero data retention, its own
fallback list and the reasoning effort. The actual cost of a call comes back in the message's
``provider_metadata``. Every SDK error becomes one of the gateway's domain errors, so the use
case can tell a fallback attempt from a refusal.
"""

import math
import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any, Self

from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    Omit,
    OpenAI,
    RateLimitError,
    omit,
)
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
)
from openai.types.shared_params import ResponseFormatJSONSchema
from openai.types.shared_params.response_format_json_schema import JSONSchema

from domain_kernel.errors import DomainError, InvariantViolationError
from domain_kernel.llm import CompletionRequest
from llm_gateway.domain.errors import (
    BudgetExceededError,
    ProviderResponseError,
    ProviderUnavailableError,
)
from llm_gateway.domain.features import Feature, parse_feature
from llm_gateway.domain.pricing import quantize_usd
from llm_gateway.domain.providers import ProviderResponse
from llm_gateway.domain.routing import Route

DEFAULT_BASE_URL = "https://ai-gateway.vercel.sh/v1"
PROVIDER_NAME = "vercel"
"""Recorded as the provider when the gateway does not name the host that served the call."""
QUOTA_EXCEEDED = "quota_for_entity_exceeded"
"""The 402 code for a budget set on the Vercel side; any other 402 means no credits."""
NO_PROVIDERS_AVAILABLE = "no_providers_available"
"""The 400 code when the host filters and zero data retention exclude every host."""
SCHEMA_NAME_MAX = 64
_SCHEMA_NAME_CHARS = re.compile(r"[^A-Za-z0-9_]")
_UNAVAILABLE_STATUSES = frozenset({401, 403, 404, 408, 409})


class VercelGatewayProvider:
    """One ``OpenAI`` client per process (it is thread-safe); the timeout is set per call."""

    def __init__(
        self,
        client: OpenAI,
        *,
        routes: Mapping[Feature, Route],
        zero_data_retention: bool = True,
    ) -> None:
        self._client = client
        self._routes = routes
        self._zero_data_retention = zero_data_retention

    @classmethod
    def from_settings(
        cls,
        *,
        base_url: str,
        api_key: str,
        timeout: float,
        max_retries: int,
        routes: Mapping[Feature, Route],
        zero_data_retention: bool,
    ) -> Self:
        """Build the SDK client. ``timeout`` is the client default; each call uses its route's."""
        client = OpenAI(
            api_key=api_key, base_url=base_url, timeout=timeout, max_retries=max_retries
        )
        return cls(client, routes=routes, zero_data_retention=zero_data_retention)

    @property
    def client(self) -> OpenAI:
        return self._client

    def complete(self, req: CompletionRequest) -> ProviderResponse:
        route = self._routes[parse_feature(req.feature)]
        model = req.model or route.primary
        try:
            completion = self._client.chat.completions.create(
                model=model,
                messages=_messages(req),
                temperature=req.temperature,
                max_tokens=req.max_tokens,
                response_format=_response_format(req),
                extra_body=self._extra_body(route, model),
                timeout=route.timeout_seconds,
            )
        except APIError as exc:
            raise _map_error(exc) from exc
        return _parse(completion, model)

    def _extra_body(self, route: Route, model: str) -> dict[str, object]:
        """The gateway options for ``model`` on ``route``; empty options are left out.

        A model outside the route (a caller's override) gets zero data retention only: the host
        filters, sort and reasoning effort were chosen for the route's own models. The route's
        timeout still applies.
        """
        gateway: dict[str, object] = {"zeroDataRetention": self._zero_data_retention}
        if model not in route.models:
            return {"providerOptions": {"gateway": gateway}}
        if route.only:
            gateway["only"] = list(route.only)
        if route.has:
            gateway["has"] = list(route.has)
        if route.sort is not None:
            gateway["sort"] = route.sort
        later = _models_after(route, model)
        if later:
            gateway["models"] = later
        body: dict[str, object] = {"providerOptions": {"gateway": gateway}}
        if route.reasoning_effort is not None:
            body["reasoning"] = {"effort": route.reasoning_effort}
        return body


def _models_after(route: Route, model: str) -> list[str]:
    """The route's models after ``model``: the gateway's own fallbacks for this attempt.

    On the primary that is the fallback; on the fallback nothing, so a model that just failed is
    never retried by the gateway.
    """
    models = route.models
    return list(models[models.index(model) + 1 :])


def _messages(req: CompletionRequest) -> list[ChatCompletionMessageParam]:
    messages: list[ChatCompletionMessageParam] = []
    if req.system:
        messages.append(ChatCompletionSystemMessageParam(role="system", content=req.system))
    messages.append(ChatCompletionUserMessageParam(role="user", content=req.user))
    return messages


def _response_format(req: CompletionRequest) -> ResponseFormatJSONSchema | Omit:
    """A strict JSON schema response format named after the prompt, or nothing."""
    if req.json_schema is None:
        return omit
    schema = JSONSchema(
        name=_schema_name(req.prompt_version), strict=True, schema=_plain_mapping(req.json_schema)
    )
    return ResponseFormatJSONSchema(type="json_schema", json_schema=schema)


def _schema_name(prompt_ref: str) -> str:
    """``extraction.rule_candidate@0`` becomes ``extraction_rule_candidate_0``."""
    return _SCHEMA_NAME_CHARS.sub("_", prompt_ref)[:SCHEMA_NAME_MAX]


def _plain_mapping(value: Mapping[str, object]) -> dict[str, object]:
    return {str(key): _plain(item) for key, item in value.items()}


def _plain(value: object) -> object:
    """Read-only proxies and tuples as plain dicts and lists, so the SDK can serialise them."""
    if isinstance(value, Mapping):
        return _plain_mapping(value)
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    return value


def _parse(completion: ChatCompletion, model: str) -> ProviderResponse:
    if not completion.choices:
        raise ProviderResponseError("gateway returned no choices")
    message = completion.choices[0].message
    if message.content is None:
        raise ProviderResponseError("gateway returned a message without content")
    usage = completion.usage
    gateway = _gateway_metadata(message.model_extra)
    routing = gateway.get("routing")
    final_provider = routing.get("finalProvider") if isinstance(routing, Mapping) else None
    generation_id = gateway.get("generationId")
    try:
        return ProviderResponse(
            text=message.content,
            model=completion.model.strip() or model,
            input_tokens=0 if usage is None else usage.prompt_tokens,
            output_tokens=0 if usage is None else usage.completion_tokens,
            provider=final_provider if isinstance(final_provider, str) else PROVIDER_NAME,
            cost_usd=_cost(gateway.get("cost")),
            generation_id=generation_id if isinstance(generation_id, str) else completion.id,
        )
    except InvariantViolationError as exc:
        raise ProviderResponseError(f"gateway response is malformed: {exc.detail}") from exc


def _gateway_metadata(extra: Mapping[str, Any] | None) -> Mapping[str, object]:
    """``message.provider_metadata.gateway`` when present and well-formed, else empty."""
    if not isinstance(extra, Mapping):
        return {}
    provider_metadata = extra.get("provider_metadata")
    if not isinstance(provider_metadata, Mapping):
        return {}
    gateway = provider_metadata.get("gateway")
    return gateway if isinstance(gateway, Mapping) else {}


def _cost(value: object) -> Decimal | None:
    """The gateway's USD cost as a quantised Decimal; anything unusable estimates instead."""
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        return None
    try:
        cost = Decimal(str(value))
    except InvalidOperation:
        return None
    if not cost.is_finite() or cost < 0:
        return None
    return quantize_usd(cost)


def _map_error(exc: APIError) -> DomainError:
    """Rate limits, outages and missing credits are unavailability; bad requests are responses."""
    if isinstance(exc, APIStatusError):
        return _map_status_error(exc)
    if isinstance(exc, APIConnectionError):
        return ProviderUnavailableError(f"gateway unreachable: {exc.message}")
    return ProviderResponseError(f"gateway error: {exc.message}")


def _map_status_error(exc: APIStatusError) -> DomainError:
    status = exc.status_code
    codes = _error_codes(exc)
    if isinstance(exc, RateLimitError) or status == 429:
        return ProviderUnavailableError(
            "gateway rate limit reached", retry_after_seconds=_retry_after(exc)
        )
    if status == 402:
        if QUOTA_EXCEEDED in codes:
            return BudgetExceededError("gateway quota exceeded", scope="gateway")
        return ProviderUnavailableError("gateway has no credits")
    if status == 400 and NO_PROVIDERS_AVAILABLE in codes:
        return ProviderUnavailableError("no gateway host can serve this request")
    if status in (400, 422):
        return ProviderResponseError(f"gateway rejected the request: {exc.message}")
    if status in _UNAVAILABLE_STATUSES or status >= 500:
        return ProviderUnavailableError(
            f"gateway returned {status}", retry_after_seconds=_retry_after(exc)
        )
    return ProviderResponseError(f"gateway returned {status}: {exc.message}")


def _error_codes(exc: APIStatusError) -> frozenset[str]:
    """Every ``code`` and ``type`` the SDK or the error body carries."""
    found: set[str] = set()
    for value in (exc.code, exc.type):
        if isinstance(value, str):
            found.add(value)
    body = exc.body
    if isinstance(body, Mapping):
        nested = body.get("error")
        sources = [body, nested] if isinstance(nested, Mapping) else [body]
        for source in sources:
            for key in ("code", "type"):
                value = source.get(key)
                if isinstance(value, str):
                    found.add(value)
    return frozenset(found)


def _retry_after(exc: APIStatusError) -> float | None:
    """The ``Retry-After`` header in seconds when it is a non-negative number."""
    header = exc.response.headers.get("retry-after")
    if header is None:
        return None
    try:
        seconds = float(header)
    except ValueError:
        return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None
