"""The profile's ``EntitlementsReader``: the identity service's entitlements route, behind the flag.

- ``HttpEntitlements`` reads ``GET {CW_IDENTITY_URL}/v1/identity/entitlements`` with the tenant
  in ``x-tenant-id`` and this service's own access token (``auth``, from
  ``py_common.auth.service_auth_from``), whose client needs the ``entitlements:read`` scope. An
  answer is kept for 60 seconds per tenant, so a plan change reaches the check within a minute.
  It fails open: a transport error, a token identity could not issue, or any answer it cannot use
  is no limit, with a warning, so an identity outage never stops a business from registering.
- ``UnlimitedEntitlements``: no limit for anyone.
- ``FlaggedEntitlements`` asks the HTTP reader only for a tenant the flag ``identity.plan_limits``
  is on for, through the shared flags reader, and answers no limit otherwise.
"""

import threading
import time
from collections.abc import Callable
from typing import Any, Final

import httpx2

from domain_kernel.ids import TenantId
from profile_service.domain.entitlements import EntitlementsReader
from profile_service.domain.flags import PLAN_LIMITS, FeatureFlags
from py_common.auth import ServiceTokenUnavailableError
from py_common.logging import get_logger

ENTITLEMENTS_PATH: Final = "/v1/identity/entitlements"
TENANT_HEADER: Final = "x-tenant-id"
CACHE_SECONDS: Final = 60.0

log = get_logger(__name__)


class UnlimitedEntitlements:
    def registration_limit(self, tenant_id: TenantId) -> int | None:
        return None


class HttpEntitlements:
    """``base_url`` is ``CW_IDENTITY_URL`` and ``auth`` the service's token auth (None sends no
    token). Pass ``client`` to talk to an in-process app or a mock transport instead."""

    def __init__(
        self,
        base_url: str = "http://localhost:8001",
        *,
        client: httpx2.Client | None = None,
        auth: httpx2.Auth | None = None,
        timeout_seconds: float = 2.0,
        cache_seconds: float = CACHE_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client or httpx2.Client(base_url=base_url, timeout=timeout_seconds)
        self._auth = auth
        self._cache_seconds = cache_seconds
        self._monotonic = monotonic
        self._cache: dict[TenantId, tuple[float, int | None]] = {}
        self._lock = threading.Lock()

    def registration_limit(self, tenant_id: TenantId) -> int | None:
        now = self._monotonic()
        with self._lock:
            cached = self._cache.get(tenant_id)
        if cached is not None and now - cached[0] < self._cache_seconds:
            return cached[1]
        limit, usable = self._fetch(tenant_id)
        if usable:
            with self._lock:
                self._cache[tenant_id] = (now, limit)
        return limit

    def _fetch(self, tenant_id: TenantId) -> tuple[int | None, bool]:
        """The limit and whether identity answered it; (None, False) when it failed open."""
        headers = {TENANT_HEADER: str(tenant_id)}
        try:
            if self._auth is None:
                response = self._client.get(ENTITLEMENTS_PATH, headers=headers)
            else:
                response = self._client.get(ENTITLEMENTS_PATH, headers=headers, auth=self._auth)
        except (httpx2.TransportError, ServiceTokenUnavailableError) as exc:
            return _open(tenant_id, type(exc).__name__)
        if response.status_code != 200:
            return _open(tenant_id, f"status {response.status_code}")
        try:
            body: Any = response.json()
            limit = body["limits"]["registrations"]
        except (ValueError, TypeError, KeyError):
            return _open(tenant_id, "unreadable answer")
        if limit is None:
            return None, True
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            return _open(tenant_id, "unreadable limit")
        return limit, True

    def close(self) -> None:
        self._client.close()


def _open(tenant_id: TenantId, reason: str) -> tuple[None, bool]:
    log.warning("profile_entitlements_unavailable", tenant=str(tenant_id), reason=reason)
    return None, False


class FlaggedEntitlements:
    """``reader`` for the tenants the flag is on for; no limit for the others."""

    def __init__(self, flags: FeatureFlags, reader: EntitlementsReader) -> None:
        self._flags = flags
        self._reader = reader

    def registration_limit(self, tenant_id: TenantId) -> int | None:
        if not self._flags.enabled(PLAN_LIMITS, tenant_id):
            return None
        return self._reader.registration_limit(tenant_id)
