import httpx2
import pytest

from pipeline.infrastructure.http import (
    USER_AGENT,
    ClientConfig,
    DisallowedByRobotsError,
    FetchFailedError,
    PoliteClient,
)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


DEFAULT = ClientConfig()


def client_over(handler, config: ClientConfig = DEFAULT, clock: Clock | None = None):  # type: ignore[no-untyped-def]
    clock = clock or Clock()
    return PoliteClient(
        config, transport=httpx2.MockTransport(handler), clock=clock, sleep=clock.sleep
    ), clock


def test_sends_the_crawler_user_agent_and_checks_robots_once_per_host() -> None:
    seen: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.url.path)
        assert request.headers["user-agent"] == USER_AGENT
        if request.url.path == "/robots.txt":
            return httpx2.Response(200, text="User-agent: *\nDisallow: /private\n")
        return httpx2.Response(200, text="ok")

    client, _ = client_over(handler)
    with client:
        assert client.get("https://example.test/a").text == "ok"
        assert client.get("https://example.test/b").text == "ok"
        with pytest.raises(DisallowedByRobotsError):
            client.get("https://example.test/private/x")
    assert seen == ["/robots.txt", "/a", "/b"]


def test_a_missing_robots_file_allows_everything() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(404 if request.url.path == "/robots.txt" else 200)

    client, _ = client_over(handler)
    assert client.get("https://example.test/anything").status_code == 200


def test_waits_between_requests_to_the_same_host() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200)

    client, clock = client_over(handler, ClientConfig(min_delay_seconds=2.0, respect_robots=False))
    client.get("https://a.test/1")
    client.get("https://a.test/2")
    client.get("https://b.test/1")
    assert clock.sleeps == [2.0]


def test_retries_server_errors_with_backoff_then_succeeds() -> None:
    calls = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(503) if calls < 3 else httpx2.Response(200, text="ok")

    config = ClientConfig(min_delay_seconds=0, backoff_seconds=1.0, respect_robots=False)
    client, clock = client_over(handler, config)
    assert client.get("https://example.test/flaky").text == "ok"
    assert calls == 3
    assert clock.sleeps == [1.0, 2.0]


def test_gives_up_after_max_tries_and_keeps_the_cause() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused")

    config = ClientConfig(min_delay_seconds=0, max_tries=2, respect_robots=False)
    client, _ = client_over(handler, config)
    with pytest.raises(FetchFailedError) as excinfo:
        client.get("https://example.test/down")
    assert isinstance(excinfo.value.__cause__, httpx2.ConnectError)


def test_client_errors_are_returned_not_retried() -> None:
    calls = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(404)

    client, _ = client_over(handler, ClientConfig(respect_robots=False))
    assert client.post_json("https://example.test/x", {"a": 1}).status_code == 404
    assert calls == 1
