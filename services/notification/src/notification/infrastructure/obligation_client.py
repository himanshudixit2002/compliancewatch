"""The obligation service's list route as the notification service's ``ObligationReader``.

``GET {CW_OBLIGATION_URL}/v1/obligation/obligations?business_id=&rule_version_id=`` with the
tenant in ``x-tenant-id`` lists the business's obligations of a rule version in any status, due
date first, as that tenant reads them: row-level security keeps another tenant's out, so a
business of another tenant has none. The open ones (open or in progress) are what a CA firm's
bulk change card is about. The obligation service serves the route to a service acting for the
tenant, so in ``dual`` and ``token`` mode every call carries this service's own access token
(``auth``, from ``py_common.auth.service_auth_from``), whose client needs the tenant:act scope.

Anything but a 200 with the list the client expects, a transport error, or a service token the
identity service could not issue raises ``DependencyUnavailableError``: the bulk notification
cannot tell which obligations a change asks of the business now, so it is refused (503) and a
retry with the same Idempotency-Key runs it again.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Final
from uuid import UUID

import httpx2

from domain_kernel.ids import BusinessId, ObligationId, RuleVersionId, TenantId
from notification.domain.errors import DependencyUnavailableError
from notification.domain.ports import OpenObligation
from py_common.auth import ServiceTokenUnavailableError

OBLIGATIONS_PATH: Final = "/v1/obligation/obligations"
TENANT_HEADER: Final = "x-tenant-id"
OPEN_STATUSES: Final = frozenset({"open", "in_progress"})
DETAIL_CHARS: Final = 300


class HttpObligationReader:
    """``base_url`` is ``CW_OBLIGATION_URL`` and ``auth`` the service's token auth (None sends no
    token). Pass ``client`` to talk to an in-process app or a mock transport instead of the
    network; ``auth`` applies to it too."""

    def __init__(
        self,
        base_url: str = "http://localhost:8005",
        *,
        client: httpx2.Client | None = None,
        auth: httpx2.Auth | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._client = client or httpx2.Client(base_url=base_url, timeout=timeout_seconds)
        self._auth = auth

    def open_obligations(
        self, tenant_id: TenantId, business_id: BusinessId, rule_version_id: RuleVersionId
    ) -> Sequence[OpenObligation]:
        params = {"business_id": str(business_id), "rule_version_id": str(rule_version_id)}
        headers = {TENANT_HEADER: str(tenant_id)}
        try:
            if self._auth is None:
                response = self._client.get(OBLIGATIONS_PATH, params=params, headers=headers)
            else:
                response = self._client.get(
                    OBLIGATIONS_PATH, params=params, headers=headers, auth=self._auth
                )
        except httpx2.TransportError as exc:
            raise DependencyUnavailableError(f"obligation service unreachable: {exc}") from exc
        except ServiceTokenUnavailableError as exc:
            raise DependencyUnavailableError(
                f"no service token for the obligation service: {exc}"
            ) from exc
        if response.status_code != 200:
            raise DependencyUnavailableError(
                f"obligation service answered {response.status_code}: "
                f"{response.text[:DETAIL_CHARS]}"
            )
        try:
            items: Any = response.json()
            found = [_open(item) for item in items if item["status"] in OPEN_STATUSES]
        except (ValueError, TypeError, KeyError) as exc:
            raise DependencyUnavailableError(
                f"obligation service answered a list the client cannot read: {exc}"
            ) from exc
        return sorted(found, key=_due_first)

    def close(self) -> None:
        self._client.close()


def _open(item: Any) -> OpenObligation:
    due_at = item.get("due_at")
    return OpenObligation(
        obligation_id=ObligationId(UUID(str(item["obligation_id"]))),
        business_id=BusinessId(UUID(str(item["business_id"]))),
        rule_version_id=RuleVersionId(UUID(str(item["rule_version_id"]))),
        title=str(item["title"]),
        steps=tuple(str(step) for step in item.get("steps") or ()),
        due_at=None if due_at is None else datetime.fromisoformat(str(due_at)),
    )


def _due_first(obligation: OpenObligation) -> tuple[bool, datetime | None, UUID]:
    """Due date with none last, then id: the list's order, kept whatever the answer's."""
    return (obligation.due_at is None, obligation.due_at, obligation.obligation_id.value)
