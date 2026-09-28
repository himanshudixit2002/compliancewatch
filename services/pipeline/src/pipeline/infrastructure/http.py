"""A polite HTTP client for regulator sites.

Every request carries the crawler's user agent, respects the host's robots.txt (fetched once
per host and cached), waits a minimum delay between requests to the same host, and retries
transport errors and 5xx responses with exponential backoff, five tries in all (guide section 7).
Tests replace the transport with ``httpx2.MockTransport`` so nothing touches the network.
"""

import time
import urllib.robotparser
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx2

from py_common.logging import get_logger

log = get_logger(__name__)
USER_AGENT = "ComplianceWatch/0.1 (+https://github.com/himanshudixit2002/compliancewatch)"


class DisallowedByRobotsError(PermissionError):
    """The site's robots.txt forbids the path; the adapter must not fetch it."""


class FetchFailedError(RuntimeError):
    """The request failed after every retry."""


@dataclass(frozen=True, slots=True)
class ClientConfig:
    user_agent: str = USER_AGENT
    min_delay_seconds: float = 1.0
    timeout_seconds: float = 30.0
    max_tries: int = 5
    backoff_seconds: float = 1.0
    respect_robots: bool = True


class PoliteClient:
    def __init__(
        self,
        config: ClientConfig = ClientConfig(),  # noqa: B008 - frozen defaults
        *,
        transport: httpx2.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._config = config
        self._client = httpx2.Client(
            headers={"user-agent": config.user_agent},
            timeout=config.timeout_seconds,
            follow_redirects=True,
            transport=transport,
        )
        self._clock = clock
        self._sleep = sleep
        self._last_request_at: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "PoliteClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def get(self, url: str, *, headers: Mapping[str, str] | None = None) -> httpx2.Response:
        return self._request("GET", url, headers=headers)

    def post_json(
        self, url: str, body: object, *, headers: Mapping[str, str] | None = None
    ) -> httpx2.Response:
        return self._request("POST", url, headers=headers, json=body)

    def _request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        json: object = None,
    ) -> httpx2.Response:
        host = urlsplit(url).netloc
        if self._config.respect_robots and not self._allowed(url):
            raise DisallowedByRobotsError(f"{url} is disallowed by robots.txt")
        last_error: Exception | None = None
        for attempt in range(1, self._config.max_tries + 1):
            self._wait_for(host)
            try:
                response = self._client.request(method, url, headers=headers, json=json)
            except httpx2.TransportError as exc:
                last_error = exc
                log.warning("crawl.transport_error", url=url, attempt=attempt, error=str(exc))
            else:
                if response.status_code < 500:
                    return response
                last_error = httpx2.HTTPStatusError(
                    f"{response.status_code} from {url}",
                    request=response.request,
                    response=response,
                )
                log.warning(
                    "crawl.server_error", url=url, attempt=attempt, status=response.status_code
                )
            if attempt < self._config.max_tries:
                self._sleep(self._config.backoff_seconds * 2 ** (attempt - 1))
        raise FetchFailedError(
            f"{method} {url} failed after {self._config.max_tries} tries"
        ) from last_error

    def _wait_for(self, host: str) -> None:
        last = self._last_request_at.get(host)
        if last is not None:
            remaining = self._config.min_delay_seconds - (self._clock() - last)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request_at[host] = self._clock()

    def _allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        host = parts.netloc
        if host not in self._robots:
            self._robots[host] = self._load_robots(f"{parts.scheme}://{host}/robots.txt", host)
        parser = self._robots[host]
        return True if parser is None else parser.can_fetch(self._config.user_agent, url)

    def _load_robots(self, robots_url: str, host: str) -> urllib.robotparser.RobotFileParser | None:
        self._wait_for(host)
        try:
            response = self._client.get(robots_url)
        except httpx2.TransportError:
            return None
        if response.status_code != 200:
            return None
        parser = urllib.robotparser.RobotFileParser()
        parser.parse(response.text.splitlines())
        return parser
