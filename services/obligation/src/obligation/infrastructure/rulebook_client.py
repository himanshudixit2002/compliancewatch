"""The rulebook's read API as the obligation service's ``RuleVersionReader``.

``GET {CW_RULEBOOK_URL}/v1/rulebook/rule-versions/{id}`` gives a version's detail
(``RuleVersionDetailOut``) with its citations, which ``read_from`` turns into the kernel's
``RuleVersionSnapshot`` and the facts the ``rule_version_ref`` cache keeps (``ref_from``). The
specification, obligation template and recurrence mappings are the kernel's own
(``specification_from_mapping``, ``ObligationTemplate.from_mapping``, ``Recurrence.from_mapping``),
and ``effective_to`` is exclusive like ``EffectivePeriod.end``. Only verified citations are kept.
``approved_by`` (the approvers of the round the version was published from) is read when the
rulebook gives it and empty otherwise.

A 404 is None: the rulebook has no such version. Any other answer that is not a 2xx, a transport
error, a service token the identity service could not issue, or a body the reader cannot read
raises ``RulebookUnavailableError``; the consumer that asked retries the event and then
dead-letters it. With ``CW_SERVICE_CLIENT_SECRET`` set, every read carries the service's own
access token (``auth``, from ``py_common.auth.service_auth_from``).

A version's published content does not change, but its status and its end do (superseded,
withdrawn), so a read is kept for ``cache_seconds`` (60) only, at most ``CACHE_SIZE`` of them;
``read(..., fresh=True)`` asks the rulebook again and keeps the answer, which is what the rule
events consumer does, so the decision consumer of the same process sees the new status at once.
None and failures are not kept.
"""

import threading
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from typing import Any, Final
from uuid import UUID

import httpx2

from domain_kernel.errors import InvariantViolationError
from domain_kernel.events import utc_now
from domain_kernel.ids import RuleId, RuleVersionId, UserId
from domain_kernel.periods import EffectivePeriod
from domain_kernel.predicates import specification_from_mapping
from domain_kernel.recurrence import Recurrence
from domain_kernel.rules import ObligationTemplate, RuleVersionSnapshot
from domain_kernel.status import RuleVersionStatus
from obligation.domain.errors import RulebookUnavailableError
from obligation.domain.rule_versions import Citation, RuleVersionRead, RuleVersionRef
from py_common.auth import ServiceTokenUnavailableError

PREFIX: Final = "/v1/rulebook"
CACHE_SIZE: Final = 1024
CACHE_SECONDS: Final = 60.0
DETAIL_CHARS: Final = 300


class HttpRuleVersionReader:
    """``base_url`` is ``CW_RULEBOOK_URL`` and ``auth`` the service's token auth (None sends no
    token). Pass ``client`` to talk to an in-process app or a mock transport instead of the
    network; ``auth`` applies to it too."""

    def __init__(
        self,
        base_url: str = "http://localhost:8003",
        *,
        client: httpx2.Client | None = None,
        auth: httpx2.Auth | None = None,
        timeout_seconds: float = 5.0,
        cache_seconds: float = CACHE_SECONDS,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._client = client or httpx2.Client(base_url=base_url, timeout=timeout_seconds)
        self._auth = auth
        self._cache_seconds = cache_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._cache: dict[RuleVersionId, RuleVersionRead] = {}

    def read(
        self, rule_version_id: RuleVersionId, *, fresh: bool = False
    ) -> RuleVersionRead | None:
        if not fresh:
            with self._lock:
                cached = self._cache.get(rule_version_id)
            if cached is not None and self._recent(cached):
                return cached
        found = self._fetch(rule_version_id)
        with self._lock:
            if found is None:
                self._cache.pop(rule_version_id, None)
            else:
                if len(self._cache) >= CACHE_SIZE and rule_version_id not in self._cache:
                    self._cache.clear()
                self._cache[rule_version_id] = found
        return found

    def _recent(self, cached: RuleVersionRead) -> bool:
        age = (self._clock() - cached.ref.fetched_at).total_seconds()
        return 0 <= age < self._cache_seconds

    def _fetch(self, rule_version_id: RuleVersionId) -> RuleVersionRead | None:
        path = f"{PREFIX}/rule-versions/{rule_version_id}"
        try:
            if self._auth is None:
                response = self._client.get(path)
            else:
                response = self._client.get(path, auth=self._auth)
        except httpx2.TransportError as exc:
            raise RulebookUnavailableError(f"rulebook unreachable: {exc}") from exc
        except ServiceTokenUnavailableError as exc:
            raise RulebookUnavailableError(f"no service token for the rulebook: {exc}") from exc
        if response.status_code == 404:
            return None
        if not 200 <= response.status_code < 300:
            raise RulebookUnavailableError(
                f"rulebook answered {response.status_code} for rule version {rule_version_id}: "
                f"{response.text[:DETAIL_CHARS]}"
            )
        try:
            return read_from(response.json(), fetched_at=self._clock())
        except (ValueError, TypeError, KeyError, InvariantViolationError) as exc:
            raise RulebookUnavailableError(
                f"rulebook answered a rule version the reader cannot read: {exc}"
            ) from exc

    def close(self) -> None:
        self._client.close()


def read_from(data: Mapping[str, Any], *, fetched_at: datetime) -> RuleVersionRead:
    """The snapshot and the cached facts of the rulebook's ``RuleVersionDetailOut``."""
    return RuleVersionRead(snapshot_from(data), ref_from(data, fetched_at=fetched_at))


def snapshot_from(data: Mapping[str, Any]) -> RuleVersionSnapshot:
    """The kernel's snapshot of the rulebook's ``RuleVersionDetailOut``."""
    recurrence = data.get("recurrence")
    return RuleVersionSnapshot(
        rule_id=RuleId.parse(str(data["rule_id"])),
        rule_version_id=RuleVersionId.parse(str(data["rule_version_id"])),
        version=data["version"],
        regulator=data["regulator"],
        title=data["title"],
        specification=specification_from_mapping(data["specification"]),
        effective=EffectivePeriod(_day(data["effective_from"]), _optional_day(data)),
        obligation_template=ObligationTemplate.from_mapping(data["obligation_template"]),
        recurrence=None if recurrence is None else Recurrence.from_mapping(recurrence),
    )


def ref_from(data: Mapping[str, Any], *, fetched_at: datetime) -> RuleVersionRef:
    """What the cache keeps of the rulebook's ``RuleVersionDetailOut``: its verified citations
    only, and the approvers when the rulebook names them."""
    published_at = data.get("published_at")
    return RuleVersionRef(
        rule_version_id=RuleVersionId.parse(str(data["rule_version_id"])),
        rule_key=str(data["rule_key"]),
        status=RuleVersionStatus(str(data["status"])),
        title=str(data["title"]),
        effective_from=_day(data["effective_from"]),
        effective_to=_optional_day(data),
        seed_status=str(data["seed_status"]),
        approved_by=tuple(UserId(UUID(str(user))) for user in data.get("approved_by") or ()),
        published_at=None if published_at is None else _instant(published_at),
        citations=tuple(
            _citation(item) for item in data.get("citations") or () if item.get("verified") is True
        ),
        fetched_at=fetched_at,
    )


def _citation(item: Mapping[str, Any]) -> Citation:
    verified_at = item.get("verified_at")
    score = item.get("match_score")
    return Citation(
        citation_id=UUID(str(item["citation_id"])),
        clause_id=UUID(str(item["clause_id"])),
        document_id=UUID(str(item["document_id"])),
        clause_ref=str(item["clause_ref"]),
        quote=str(item["quote"]),
        match_score=None if score is None else float(score),
        verified_at=None if verified_at is None else _instant(verified_at),
    )


def _day(value: object) -> date:
    return date.fromisoformat(str(value))


def _optional_day(data: Mapping[str, Any]) -> date | None:
    value = data.get("effective_to")
    return None if value is None else _day(value)


def _instant(value: object) -> datetime:
    moment = datetime.fromisoformat(str(value))
    if moment.tzinfo is None:
        raise ValueError(f"{value} has no time zone")
    return moment.astimezone(UTC)
