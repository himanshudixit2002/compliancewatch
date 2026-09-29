"""The HTTP helper: 404 is nothing, 429 a used-up budget, everything else that fails is a
dependency failure."""

import httpx2
import pytest

from qa.domain.errors import DependencyUnavailableError, ModelBudgetExceededError
from qa.infrastructure.http import JsonHttp, http_client, reading


def http(handler: httpx2.MockTransport) -> JsonHttp:
    return JsonHttp(httpx2.Client(base_url="http://svc.test", transport=handler), "rulebook")


def test_a_success_is_its_json_and_the_request_is_as_asked() -> None:
    seen: list[httpx2.Request] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json={"ok": True})

    client = http(httpx2.MockTransport(answer))
    assert client.get("/a", params={"x": "1", "n": 2}, headers={"x-tenant-id": "t"}) == {"ok": True}
    assert client.post("/b", {"text": "q"}) == {"ok": True}
    client.close()
    first, second = seen
    assert (first.method, str(first.url)) == ("GET", "http://svc.test/a?x=1&n=2")
    assert first.headers["x-tenant-id"] == "t"
    assert (second.method, second.content) == ("POST", b'{"text":"q"}')


def test_not_found_is_none() -> None:
    client = http(httpx2.MockTransport(lambda _: httpx2.Response(404, json={"title": "gone"})))
    assert client.get("/missing") is None


@pytest.mark.parametrize(
    ("response", "detail"),
    [
        (httpx2.Response(503, text="down for maintenance"), "rulebook answered 503: down for"),
        (httpx2.Response(422, json={"title": "Request is invalid"}), "rulebook answered 422"),
        (httpx2.Response(200, text="<html>"), "rulebook answered with no JSON"),
    ],
)
def test_other_answers_are_a_dependency_failure(response: httpx2.Response, detail: str) -> None:
    client = http(httpx2.MockTransport(lambda _: response))
    with pytest.raises(DependencyUnavailableError, match=detail):
        client.get("/x")


def test_too_many_requests_is_a_used_up_budget() -> None:
    refused = httpx2.Response(
        429, headers={"retry-after": "120"}, json={"title": "LLM budget exceeded"}
    )
    client = JsonHttp(
        httpx2.Client(base_url="http://gw.test", transport=httpx2.MockTransport(lambda _: refused)),
        "llm-gateway",
    )
    with pytest.raises(ModelBudgetExceededError, match="llm-gateway answered 429") as caught:
        client.post("/v1/llm-gateway/embeddings", {"inputs": ["q"]})
    assert caught.value.problem_headers == {"Retry-After": "120"}


def test_a_transport_error_is_a_dependency_failure() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    with pytest.raises(DependencyUnavailableError, match="rulebook unreachable"):
        http(httpx2.MockTransport(refuse)).get("/x")


def test_an_unexpected_shape_is_a_dependency_failure() -> None:
    shape = "profile answered an unexpected shape: 'missing'"
    with pytest.raises(DependencyUnavailableError, match=shape), reading("profile"):
        raise KeyError("missing")


def test_a_client_is_made_for_a_base_url_unless_given() -> None:
    given = httpx2.Client()
    assert http_client("http://x.test", 1.0, given) is given
    made = http_client("http://x.test", 2.5, None)
    assert str(made.base_url) == "http://x.test"
    assert made.timeout.read == 2.5
