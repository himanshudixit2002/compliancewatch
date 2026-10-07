"""The identity service's consent summary as the notification service's ``ConsentReader``.

``GET {CW_IDENTITY_URL}/v1/identity/consents?subject=&channel=&address=`` with the tenant in
``x-tenant-id`` answers the subject's current state per purpose (``states``, each with ``purpose``
and ``granted``) and its history, as that tenant recorded them, and ``address_matches``: whether
the address is the subject's own contact on the channel (null when identity knows none). A
purpose missing from ``states`` was never recorded; one whose state is not granted was withdrawn.
Identity serves the route to a service acting for the tenant, so in ``dual`` and ``token`` mode
every call carries this service's own access token (``auth``, from
``py_common.auth.service_auth_from``), whose client needs the tenant:act scope.

Anything but a 200 with the summary the client expects, a transport error, or a service token
the identity service could not issue raises ``DependencyUnavailableError``: the service cannot
tell whether the opt-in is covered, so it records nothing (503) and the caller may try again.
"""

from typing import Any, Final

import httpx2

from domain_kernel.channels import Channel
from domain_kernel.ids import TenantId
from notification.domain.errors import DependencyUnavailableError
from notification.domain.ports import ConsentAnswer
from py_common.auth import ServiceTokenUnavailableError

CONSENTS_PATH: Final = "/v1/identity/consents"
TENANT_HEADER: Final = "x-tenant-id"
DETAIL_CHARS: Final = 300


class HttpConsentReader:
    """``base_url`` is ``CW_IDENTITY_URL`` and ``auth`` the service's token auth (None sends no
    token). Pass ``client`` to talk to an in-process app or a mock transport instead of the
    network; ``auth`` applies to it too."""

    def __init__(
        self,
        base_url: str = "http://localhost:8001",
        *,
        client: httpx2.Client | None = None,
        auth: httpx2.Auth | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._client = client or httpx2.Client(base_url=base_url, timeout=timeout_seconds)
        self._auth = auth

    def check(
        self, tenant_id: TenantId, subject: str, purpose: str, *, channel: Channel, address: str
    ) -> ConsentAnswer:
        params = {"subject": subject, "channel": channel.value, "address": address}
        headers = {TENANT_HEADER: str(tenant_id)}
        try:
            if self._auth is None:
                response = self._client.get(CONSENTS_PATH, params=params, headers=headers)
            else:
                response = self._client.get(
                    CONSENTS_PATH, params=params, headers=headers, auth=self._auth
                )
        except httpx2.TransportError as exc:
            raise DependencyUnavailableError(f"identity service unreachable: {exc}") from exc
        except ServiceTokenUnavailableError as exc:
            raise DependencyUnavailableError(
                f"no service token for the identity service: {exc}"
            ) from exc
        if response.status_code != 200:
            raise DependencyUnavailableError(
                f"identity service answered {response.status_code}: {response.text[:DETAIL_CHARS]}"
            )
        try:
            summary: Any = response.json()
            states = [(str(s["purpose"]), s["granted"]) for s in summary["states"]]
            if any(not isinstance(granted, bool) for _, granted in states):
                raise TypeError("granted is not a boolean")
            matches = summary.get("address_matches")
            if matches is not None and not isinstance(matches, bool):
                raise TypeError("address_matches is not a boolean")
        except (ValueError, TypeError, KeyError) as exc:
            raise DependencyUnavailableError(
                f"identity service answered a consent summary the client cannot read: {exc}"
            ) from exc
        granted = any(found == purpose and given for found, given in states)
        return ConsentAnswer(granted=granted, address_is_theirs=matches)

    def close(self) -> None:
        self._client.close()
