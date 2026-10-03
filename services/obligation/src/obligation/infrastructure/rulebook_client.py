"""The rulebook's read API as the obligation service's ``RuleVersionReader``.

``GET {CW_RULEBOOK_URL}/v1/rulebook/rule-versions/{id}`` gives a version's detail
(``RuleVersionDetailOut``), which ``snapshot_from`` turns into the kernel's
``RuleVersionSnapshot``: the specification, obligation template and recurrence mappings are the
kernel's own (``specification_from_mapping``, ``ObligationTemplate.from_mapping``,
``Recurrence.from_mapping``), and ``effective_to`` is exclusive like ``EffectivePeriod.end``.

A 404 is None: the rulebook has no such version. Any other answer that is not a 2xx, a transport
error, a service token the identity service could not issue, or a body the reader cannot read
raises ``RulebookUnavailableError``; the consumer that asked retries the event and then
dead-letters it. With ``CW_SERVICE_CLIENT_SECRET`` set, every read carries the service's own
access token (``auth``, from ``py_common.auth.service_auth_from``). A version's published content
does not change, so found versions are kept for the life of the process (at most
``CACHE_SIZE``); None and failures are not kept.
"""

import threading
from collections.abc import Mapping
from datetime import date
from typing import Any, Final

import httpx2

from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import RuleId, RuleVersionId
from domain_kernel.periods import EffectivePeriod
from domain_kernel.predicates import specification_from_mapping
from domain_kernel.recurrence import Recurrence
from domain_kernel.rules import ObligationTemplate, RuleVersionSnapshot
from obligation.domain.errors import RulebookUnavailableError
from py_common.auth import ServiceTokenUnavailableError

PREFIX: Final = "/v1/rulebook"
CACHE_SIZE: Final = 1024
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
    ) -> None:
        self._client = client or httpx2.Client(base_url=base_url, timeout=timeout_seconds)
        self._auth = auth
        self._lock = threading.Lock()
        self._cache: dict[RuleVersionId, RuleVersionSnapshot] = {}

    def get(self, rule_version_id: RuleVersionId) -> RuleVersionSnapshot | None:
        with self._lock:
            cached = self._cache.get(rule_version_id)
        if cached is not None:
            return cached
        found = self._fetch(rule_version_id)
        if found is not None:
            with self._lock:
                if len(self._cache) >= CACHE_SIZE:
                    self._cache.clear()
                self._cache[rule_version_id] = found
        return found

    def _fetch(self, rule_version_id: RuleVersionId) -> RuleVersionSnapshot | None:
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
            return snapshot_from(response.json())
        except (ValueError, TypeError, KeyError, InvariantViolationError) as exc:
            raise RulebookUnavailableError(
                f"rulebook answered a rule version the reader cannot read: {exc}"
            ) from exc

    def close(self) -> None:
        self._client.close()


def snapshot_from(data: Mapping[str, Any]) -> RuleVersionSnapshot:
    """The kernel's snapshot of the rulebook's ``RuleVersionDetailOut``."""
    recurrence = data.get("recurrence")
    effective_to = data.get("effective_to")
    return RuleVersionSnapshot(
        rule_id=RuleId.parse(str(data["rule_id"])),
        rule_version_id=RuleVersionId.parse(str(data["rule_version_id"])),
        version=data["version"],
        regulator=data["regulator"],
        title=data["title"],
        specification=specification_from_mapping(data["specification"]),
        effective=EffectivePeriod(
            date.fromisoformat(str(data["effective_from"])),
            None if effective_to is None else date.fromisoformat(str(effective_to)),
        ),
        obligation_template=ObligationTemplate.from_mapping(data["obligation_template"]),
        recurrence=None if recurrence is None else Recurrence.from_mapping(recurrence),
    )
