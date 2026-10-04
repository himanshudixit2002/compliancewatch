"""The rulebook's ``GET /v1/rulebook/rule-versions/{rule_version_id}`` and
``GET /v1/rulebook/rule-versions?as_of=`` as the engine's ``RulebookReader``: one version's
status and specification, the kernel's predicate tree mapping, and the versions in force on a
day.

``rules_in_force(as_of, level)`` pages the in-force listing by rule key (``limit`` 500 and
``after``), keeps the published versions and answers those of the level. The listing of a day
is cached for ``cache_seconds`` (0 turns the cache off), so a burst of profile.updated events
reads the rulebook once; a version published meanwhile is evaluated once the entry expires.
"""

import threading
import time
from collections.abc import Callable, Sequence
from datetime import date
from typing import Any, Final
from uuid import UUID

import httpx2

from applicability_engine.domain.model import RuleInForce, RuleVersionSpec
from applicability_engine.infrastructure.http import JsonHttp, http_client, reading
from domain_kernel.ids import RuleVersionId
from domain_kernel.ontology import AttributeLevel
from domain_kernel.predicates import specification_from_mapping
from domain_kernel.status import RuleVersionStatus

RULE_VERSION_PATH: Final = "/v1/rulebook/rule-versions/{rule_version_id}"
IN_FORCE_PATH: Final = "/v1/rulebook/rule-versions"
PAGE: Final = 500
"""The longest page the rulebook's listing gives."""
SERVICE: Final = "rulebook"


class HttpRulebook:
    """``base_url`` is ``CW_RULEBOOK_URL`` and ``auth`` the service's token auth (None sends no
    token). Pass ``client`` to talk to an in-process app (a FastAPI ``TestClient``) instead of the
    network."""

    def __init__(
        self,
        base_url: str = "http://localhost:8003",
        *,
        client: httpx2.Client | None = None,
        auth: httpx2.Auth | None = None,
        timeout_seconds: float = 5.0,
        cache_seconds: float = 0.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if cache_seconds < 0:
            raise ValueError("cache_seconds must not be negative")
        self._http = JsonHttp(http_client(base_url, timeout_seconds, client), SERVICE, auth=auth)
        self._cache_seconds = cache_seconds
        self._monotonic = monotonic
        self._cached: dict[date, tuple[float, tuple[RuleInForce, ...]]] = {}
        self._lock = threading.Lock()

    def rule_version(self, rule_version_id: RuleVersionId) -> RuleVersionSpec | None:
        data = self._http.get(RULE_VERSION_PATH.format(rule_version_id=rule_version_id))
        if data is None:
            return None
        with reading(SERVICE):
            return RuleVersionSpec(
                rule_version_id=RuleVersionId(UUID(str(data["rule_version_id"]))),
                status=RuleVersionStatus(data["status"]),
                specification=specification_from_mapping(data["specification"]),
            )

    def rules_in_force(self, as_of: date, level: AttributeLevel) -> Sequence[RuleInForce]:
        return tuple(rule for rule in self._in_force(as_of) if rule.level is level)

    def _in_force(self, as_of: date) -> tuple[RuleInForce, ...]:
        now = self._monotonic()
        with self._lock:
            cached = self._cached.get(as_of)
            if cached is not None and now < cached[0]:
                return cached[1]
        found = self._read_in_force(as_of)
        if self._cache_seconds > 0:
            with self._lock:
                self._cached = {day: entry for day, entry in self._cached.items() if now < entry[0]}
                self._cached[as_of] = (now + self._cache_seconds, found)
        return found

    def _read_in_force(self, as_of: date) -> tuple[RuleInForce, ...]:
        found: list[RuleInForce] = []
        after: str | None = None
        while True:
            params: dict[str, str | int] = {"as_of": as_of.isoformat(), "limit": PAGE}
            if after is not None:
                params["after"] = after
            page = self._http.get(IN_FORCE_PATH, params=params)
            with reading(SERVICE):
                versions: list[dict[str, Any]] = list(page or [])
                found.extend(
                    _in_force(version)
                    for version in versions
                    if version["status"] == RuleVersionStatus.PUBLISHED.value
                )
                if len(versions) < PAGE:
                    return tuple(found)
                after = str(versions[-1]["rule_key"])

    def close(self) -> None:
        self._http.close()


def _in_force(version: dict[str, Any]) -> RuleInForce:
    effective_to = version.get("effective_to")
    return RuleInForce(
        spec=RuleVersionSpec(
            rule_version_id=RuleVersionId(UUID(str(version["rule_version_id"]))),
            status=RuleVersionStatus(version["status"]),
            specification=specification_from_mapping(version["specification"]),
        ),
        rule_key=str(version["rule_key"]),
        level=AttributeLevel(version["level"]),
        effective_from=date.fromisoformat(str(version["effective_from"])),
        effective_to=None if effective_to is None else date.fromisoformat(str(effective_to)),
    )
