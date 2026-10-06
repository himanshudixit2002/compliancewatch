"""The rulebook's ``GET /v1/rulebook/rule-versions/{rule_version_id}`` and
``GET /v1/rulebook/rule-versions`` as the engine's ``RulebookReader``: one version's status,
specification (the kernel's predicate tree mapping) and schedule, the versions in force on a day
and the versions superseded since a day.

``rule_version`` answers the version in any status with its rule key and level, which a fan-out
pages the directory by, and its schedule (effective dates, recurrence and the template's
``due_in_days``). ``rules_in_force(as_of, level)`` pages the in-force listing (``as_of``) by rule
key (``limit`` 500 and ``after``), keeps the published versions and answers those of the level.
``rules_superseded_since(since, level)`` pages the listing of the versions that ended on or after
``since`` (``ended_on_or_after``, ``status=superseded``: never a withdrawn one) by rule key and
version (``after`` and ``after_version``, since a rule can have several), keeps the superseded
ones and answers those of the level. Each listing of a day is cached for ``cache_seconds`` (0
turns the cache off), so a burst of profile.updated events reads the rulebook once; a version
published meanwhile is evaluated once the entry expires, or at once after ``forget_in_force``,
which the rule events consumer calls on every rule.published and rule.withdrawn.
"""

import threading
import time
from collections.abc import Callable, Sequence
from datetime import date
from typing import Any, Final
from uuid import UUID

import httpx2

from applicability_engine.domain.model import RuleInForce, RuleVersionSpec, Schedule
from applicability_engine.infrastructure.http import JsonHttp, http_client, reading
from domain_kernel.ids import RuleVersionId
from domain_kernel.ontology import AttributeLevel
from domain_kernel.periods import EffectivePeriod
from domain_kernel.predicates import specification_from_mapping
from domain_kernel.recurrence import Recurrence
from domain_kernel.status import RuleVersionStatus

RULE_VERSION_PATH: Final = "/v1/rulebook/rule-versions/{rule_version_id}"
IN_FORCE_PATH: Final = "/v1/rulebook/rule-versions"
PAGE: Final = 500
"""The longest page the rulebook's listing gives."""
SERVICE: Final = "rulebook"
IN_FORCE: Final = "as_of"
ENDED: Final = "ended_on_or_after"
LISTED: Final = {IN_FORCE: RuleVersionStatus.PUBLISHED, ENDED: RuleVersionStatus.SUPERSEDED}
"""Each listing's query parameter, and the status of the versions the engine keeps of it."""


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
        self._cached: dict[tuple[str, date], tuple[float, tuple[RuleInForce, ...]]] = {}
        self._lock = threading.Lock()

    def rule_version(self, rule_version_id: RuleVersionId) -> RuleVersionSpec | None:
        data = self._http.get(RULE_VERSION_PATH.format(rule_version_id=rule_version_id))
        if data is None:
            return None
        with reading(SERVICE):
            rule_key, level = data.get("rule_key"), data.get("level")
            return _spec(
                data,
                _schedule(data),
                rule_key=None if rule_key is None else str(rule_key),
                level=None if level is None else AttributeLevel(level),
            )

    def rules_in_force(self, as_of: date, level: AttributeLevel) -> Sequence[RuleInForce]:
        return tuple(rule for rule in self._listing(IN_FORCE, as_of) if rule.level is level)

    def rules_superseded_since(self, since: date, level: AttributeLevel) -> Sequence[RuleInForce]:
        return tuple(rule for rule in self._listing(ENDED, since) if rule.level is level)

    def forget_in_force(self) -> None:
        with self._lock:
            self._cached = {}

    def _listing(self, listing: str, day: date) -> tuple[RuleInForce, ...]:
        now = self._monotonic()
        with self._lock:
            cached = self._cached.get((listing, day))
            if cached is not None and now < cached[0]:
                return cached[1]
        found = self._read(listing, day)
        if self._cache_seconds > 0:
            with self._lock:
                self._cached = {key: entry for key, entry in self._cached.items() if now < entry[0]}
                self._cached[(listing, day)] = (now + self._cache_seconds, found)
        return found

    def _read(self, listing: str, day: date) -> tuple[RuleInForce, ...]:
        """Every page of one listing of ``day``. A listing of ended versions can hold several
        versions of a rule, so it continues after a rule key and a version."""
        kept = LISTED[listing]
        found: list[RuleInForce] = []
        after: dict[str, str | int] = {}
        while True:
            params: dict[str, str | int] = {listing: day.isoformat(), "limit": PAGE, **after}
            if listing == ENDED:
                params["status"] = kept.value
            page = self._http.get(IN_FORCE_PATH, params=params)
            with reading(SERVICE):
                versions: list[dict[str, Any]] = list(page or [])
                found.extend(_listed(version) for version in versions if version["status"] == kept)
                if len(versions) < PAGE:
                    return tuple(found)
                last = versions[-1]
                after = {"after": str(last["rule_key"])}
                if listing == ENDED:
                    after["after_version"] = int(last["version"])

    def close(self) -> None:
        self._http.close()


def _schedule(version: dict[str, Any]) -> Schedule:
    """When the version's duties fall due: its effective dates, its recurrence and its
    template's ``due_in_days``."""
    effective_to = version.get("effective_to")
    recurrence = version.get("recurrence")
    template = version.get("obligation_template") or {}
    return Schedule(
        effective=EffectivePeriod(
            date.fromisoformat(str(version["effective_from"])),
            None if effective_to is None else date.fromisoformat(str(effective_to)),
        ),
        recurrence=None if recurrence is None else Recurrence.from_mapping(recurrence),
        due_in_days=template.get("due_in_days"),
    )


def _spec(
    version: dict[str, Any],
    schedule: Schedule,
    *,
    rule_key: str | None,
    level: AttributeLevel | None,
) -> RuleVersionSpec:
    return RuleVersionSpec(
        rule_version_id=RuleVersionId(UUID(str(version["rule_version_id"]))),
        status=RuleVersionStatus(version["status"]),
        specification=specification_from_mapping(version["specification"]),
        rule_key=rule_key,
        level=level,
        schedule=schedule,
    )


def _listed(version: dict[str, Any]) -> RuleInForce:
    rule_key, level = str(version["rule_key"]), AttributeLevel(version["level"])
    schedule = _schedule(version)
    return RuleInForce(
        spec=_spec(version, schedule, rule_key=rule_key, level=level),
        rule_key=rule_key,
        level=level,
        effective_from=schedule.effective.start,
        effective_to=schedule.effective.end,
    )
