from dataclasses import replace
from decimal import Decimal

import pytest

from domain_kernel.errors import InvariantViolationError
from domain_kernel.llm import CompletionResponse
from llm_gateway.domain.providers import ProviderResponse


def test_provider_response_extends_the_kernel_response() -> None:
    response = ProviderResponse("hi", "fake/echo", 3, 1)
    assert isinstance(response, CompletionResponse)
    assert (response.provider, response.cost_usd, response.generation_id) == ("", None, "")
    assert (response.cached, response.trace_id) == (False, "")
    full = ProviderResponse(
        "hi", "zai/glm-5.3", 3, 1, provider="morph", cost_usd=Decimal("0.01"), generation_id="g"
    )
    assert replace(full, cached=True).cached is True
    assert not hasattr(full, "__dict__")


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"model": ""}, "model must not be blank"),
        ({"input_tokens": -1}, "input_tokens must be at least 0"),
        ({"provider": None}, "provider must be str"),
        ({"cost_usd": 0.5}, "cost_usd must be a Decimal"),
        ({"cost_usd": Decimal("NaN")}, "cost_usd must be a Decimal"),
        ({"generation_id": 1}, "generation_id must be str"),
    ],
)
def test_provider_response_invariants(kwargs: dict[str, object], message: str) -> None:
    fields: dict[str, object] = {
        "text": "hi",
        "model": "fake/echo",
        "input_tokens": 1,
        "output_tokens": 1,
    }
    fields.update(kwargs)
    with pytest.raises(InvariantViolationError, match=message):
        ProviderResponse(**fields)  # type: ignore[arg-type]
