"""The rulebook's read API as the notification service's ``RuleVersionReader``.

``GET {CW_RULEBOOK_URL}/v1/rulebook/rule-versions/{id}`` gives a version's detail. The facts a
message states are taken from it: the obligation template's title (the rule's own title when
the template has none), the summary, ``effective_from``, the template's steps, and the source
as '<instrument>, <reference>'.

A 404 is None: the rulebook has no such version. A transport error, any other status that is
not a success, or an answer that is not the expected JSON raises
``DependencyUnavailableError``, and the dispatcher tries again later. Answers, None included,
are kept for an hour (``CACHE_SECONDS``): a dispatch of many notifications of one rule asks once,
and a version's published facts do not change while it is in force. Failures are not kept.
"""

import threading
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from typing import Any, Final

import httpx2

from domain_kernel.events import utc_now
from domain_kernel.ids import RuleVersionId
from notification.domain.errors import DependencyUnavailableError
from notification.domain.ports import RuleVersionFacts

PREFIX: Final = "/v1/rulebook"
CACHE_SECONDS: Final = 3600.0
DETAIL_CHARS: Final = 300


class HttpRuleVersionReader:
    """``base_url`` is ``CW_RULEBOOK_URL``. Pass ``client`` to talk to an in-process app (a
    FastAPI ``TestClient``) or a mock transport instead of the network."""

    def __init__(
        self,
        base_url: str = "http://localhost:8003",
        *,
        client: httpx2.Client | None = None,
        timeout_seconds: float = 5.0,
        cache_seconds: float = CACHE_SECONDS,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._client = client or httpx2.Client(base_url=base_url, timeout=timeout_seconds)
        self._ttl = timedelta(seconds=cache_seconds)
        self._clock = clock
        self._lock = threading.Lock()
        self._cache: dict[RuleVersionId, tuple[datetime, RuleVersionFacts | None]] = {}

    def get(self, rule_version_id: RuleVersionId) -> RuleVersionFacts | None:
        now = self._clock()
        with self._lock:
            cached = self._cache.get(rule_version_id)
        if cached is not None and now - cached[0] < self._ttl:
            return cached[1]
        facts = self._fetch(rule_version_id)
        with self._lock:
            self._cache[rule_version_id] = (now, facts)
        return facts

    def _fetch(self, rule_version_id: RuleVersionId) -> RuleVersionFacts | None:
        try:
            response = self._client.get(f"{PREFIX}/rule-versions/{rule_version_id}")
        except httpx2.TransportError as exc:
            raise DependencyUnavailableError(f"rulebook unreachable: {exc}") from exc
        if response.status_code == 404:
            return None
        if not 200 <= response.status_code < 300:
            raise DependencyUnavailableError(
                f"rulebook answered {response.status_code}: {response.text[:DETAIL_CHARS]}"
            )
        try:
            return facts_from(response.json())
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise DependencyUnavailableError(
                f"rulebook answered a rule version the reader cannot read: {exc}"
            ) from exc

    def close(self) -> None:
        self._client.close()


def facts_from(data: Mapping[str, Any]) -> RuleVersionFacts:
    """The facts of the rulebook's ``RuleVersionDetailOut``."""
    template = data.get("obligation_template") or {}
    source = data.get("source") or {}
    steps = template.get("steps") or []
    if not isinstance(steps, list):
        raise TypeError("obligation_template.steps is not a list")
    cited = [str(source[name]).strip() for name in ("instrument", "reference") if source.get(name)]
    return RuleVersionFacts(
        title=str(template.get("title") or data["title"]),
        summary=str(data.get("summary") or ""),
        effective_from=date.fromisoformat(str(data["effective_from"])),
        steps=tuple(str(step) for step in steps if str(step).strip()),
        source_ref=", ".join(part for part in cited if part),
    )
