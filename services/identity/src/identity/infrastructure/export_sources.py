"""The other services' data of a tenant, for an export: ``GET /v1/<service>/data-export``.

``HttpExportSource`` calls one service's export route with the tenant in ``x-tenant-id`` and an
access token identity mints for itself in the process (``token``): a service principal with the
data:export and tenant:act scopes, living a couple of minutes. A service in header mode ignores
the token and reads the header, as every tenant route does there.

The list of services comes from ``CW_IDENTITY_EXPORT_SOURCES``
(``identity.domain.data_requests.parse_export_sources``),
``service=base_url`` pairs separated by commas; the default is the dev stack's ports. A service
that is unreachable, answers anything but a 200, or answers an export of another service or
another tenant gives a section without data and the reason: the export goes on without it, and
the request stays in progress with that service pending. The reason names the status or the kind
of error only, never the body.
"""

from collections.abc import Callable
from typing import Any, Final

import httpx2

from domain_kernel.ids import TenantId
from identity.domain.data_requests import SourceSection
from py_common.logging import get_logger

TENANT_HEADER: Final = "x-tenant-id"
DEFAULT_TIMEOUT_SECONDS: Final = 30.0

log = get_logger(__name__)


def export_path(service: str) -> str:
    return f"/v1/{service}/data-export"


class HttpExportSource:
    """``service`` at ``base_url``. ``token`` returns the bearer to send (None sends none);
    ``client`` replaces the network, as tests and the demo do, and ``base_url`` is then unused."""

    def __init__(
        self,
        service: str,
        base_url: str,
        *,
        token: Callable[[], str] | None = None,
        client: httpx2.Client | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._service = service
        self._token = token
        self._client = client or httpx2.Client(base_url=base_url, timeout=timeout_seconds)

    @property
    def service(self) -> str:
        return self._service

    def export(self, tenant_id: TenantId) -> SourceSection:
        headers = {TENANT_HEADER: str(tenant_id)}
        try:
            if self._token is not None:
                headers["Authorization"] = f"Bearer {self._token()}"
            response = self._client.get(export_path(self._service), headers=headers)
        except httpx2.HTTPError as exc:
            return self._failed(f"unreachable ({type(exc).__name__})")
        except Exception as exc:  # a token that could not be minted, say
            return self._failed(f"not asked ({type(exc).__name__})")
        if response.status_code != 200:
            return self._failed(f"answered {response.status_code}")
        try:
            body: Any = response.json()
        except ValueError:
            return self._failed("answered something other than JSON")
        problem = _check(body, self._service, tenant_id)
        if problem:
            return self._failed(problem)
        return SourceSection(self._service, body)

    def _failed(self, reason: str) -> SourceSection:
        log.warning("identity.export_source_failed", service=self._service, reason=reason)
        return SourceSection(self._service, None, reason)

    def close(self) -> None:
        self._client.close()


def _check(body: Any, service: str, tenant_id: TenantId) -> str:
    """Why the answer is not this service's export of this tenant, or ''."""
    if not isinstance(body, dict):
        return "answered an export identity cannot read"
    if body.get("service") != service:
        return "answered the export of another service"
    if body.get("tenant_id") != str(tenant_id):
        return "answered the export of another tenant"
    if not isinstance(body.get("sections"), dict) or not isinstance(body.get("generated_at"), str):
        return "answered an export identity cannot read"
    return ""
