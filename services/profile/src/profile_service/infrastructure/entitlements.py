"""The profile's ``EntitlementsReader``: the identity service's entitlements route, behind the flag.

- ``HttpEntitlements`` reads ``GET {CW_IDENTITY_URL}/v1/identity/entitlements`` with the tenant
  in ``x-tenant-id`` and this service's own access token (``auth``, from
  ``py_common.auth.service_auth_from``), whose client needs the ``entitlements:read`` scope.

  - An answer is kept for 60 seconds per tenant, so a plan change reaches the check within a
    minute. The limit counts only when identity says ``enforced`` (the flag
    ``identity.plan_limits`` as identity reads it); otherwise there is no limit.
  - It fails open only when identity cannot be reached: a transport error, a timeout, a 5xx, or
    a service token identity could not issue. That is no limit, with a warning, so an identity
    outage never stops a business from registering.
  - A 401 or 403, or an answer it cannot read, is a misconfiguration (a missing service client,
    a missing scope, a wrong URL): the registration is refused with 503
    ``EntitlementsMisconfiguredError`` and the error is logged, never let through unchecked.
  - Either failure is kept for 10 seconds (``failure_cache_seconds``), so while identity is down
    or misconfigured a registration does not wait for the timeout and the log gets one line per
    tenant every 10 seconds, not one per request.
- ``UnlimitedEntitlements``: no limit for anyone.
- ``FlaggedEntitlements`` asks the HTTP reader only for a tenant the flag ``identity.plan_limits``
  is on for, through the shared flags reader, and answers no limit otherwise. The limit applies
  only when both profile's flag and identity's ``enforced`` say so.
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

import httpx2

from domain_kernel.ids import TenantId
from profile_service.domain.entitlements import EntitlementsReader
from profile_service.domain.errors import EntitlementsMisconfiguredError
from profile_service.domain.flags import PLAN_LIMITS, FeatureFlags
from py_common.auth import ServiceTokenUnavailableError
from py_common.logging import get_logger

ENTITLEMENTS_PATH: Final = "/v1/identity/entitlements"
TENANT_HEADER: Final = "x-tenant-id"
CACHE_SECONDS: Final = 60.0
FAILURE_CACHE_SECONDS: Final = 10.0

log = get_logger(__name__)


class UnlimitedEntitlements:
    def registration_limit(self, tenant_id: TenantId) -> int | None:
        return None


@dataclass(frozen=True, slots=True)
class _Known:
    """What identity answered for a tenant, until ``expires``: a limit (None is no limit), or
    the misconfiguration to refuse with."""

    expires: float
    limit: int | None = None
    misconfigured: str | None = None


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
        failure_cache_seconds: float = FAILURE_CACHE_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client or httpx2.Client(base_url=base_url, timeout=timeout_seconds)
        self._auth = auth
        self._cache_seconds = cache_seconds
        self._failure_seconds = failure_cache_seconds
        self._monotonic = monotonic
        self._cache: dict[TenantId, _Known] = {}
        self._lock = threading.Lock()

    def registration_limit(self, tenant_id: TenantId) -> int | None:
        now = self._monotonic()
        with self._lock:
            known = self._cache.get(tenant_id)
        if known is None or now >= known.expires:
            known = self._fetch(tenant_id, now)
            with self._lock:
                self._cache[tenant_id] = known
        if known.misconfigured is not None:
            raise EntitlementsMisconfiguredError(known.misconfigured)
        return known.limit

    def _fetch(self, tenant_id: TenantId, now: float) -> _Known:
        headers = {TENANT_HEADER: str(tenant_id)}
        try:
            if self._auth is None:
                response = self._client.get(ENTITLEMENTS_PATH, headers=headers)
            else:
                response = self._client.get(ENTITLEMENTS_PATH, headers=headers, auth=self._auth)
        except (httpx2.TransportError, ServiceTokenUnavailableError) as exc:
            return self._open(tenant_id, now, type(exc).__name__)
        status = response.status_code
        if status >= 500:
            return self._open(tenant_id, now, f"status {status}")
        if status != 200:  # 401 or 403 above all: no client, no token, no scope
            return self._misconfigured(now, f"identity answered {status}")
        try:
            body: Any = response.json()
            limit = body["limits"]["registrations"]
            enforced = body["enforced"]
        except (ValueError, TypeError, KeyError):
            return self._misconfigured(now, "identity's answer could not be read")
        if not isinstance(enforced, bool):
            return self._misconfigured(now, "identity's answer could not be read")
        if not enforced or limit is None:
            return _Known(now + self._cache_seconds, None)
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            return self._misconfigured(now, "identity's limit could not be read")
        return _Known(now + self._cache_seconds, limit)

    def _open(self, tenant_id: TenantId, now: float, reason: str) -> _Known:
        log.warning("profile_entitlements_unavailable", tenant=str(tenant_id), reason=reason)
        return _Known(now + self._failure_seconds, None)

    def _misconfigured(self, now: float, reason: str) -> _Known:
        log.error("profile_entitlements_misconfigured", reason=reason)
        return _Known(now + self._failure_seconds, misconfigured=reason)

    def close(self) -> None:
        self._client.close()


class FlaggedEntitlements:
    """``reader`` for the tenants the flag is on for; no limit for the others."""

    def __init__(self, flags: FeatureFlags, reader: EntitlementsReader) -> None:
        self._flags = flags
        self._reader = reader

    def registration_limit(self, tenant_id: TenantId) -> int | None:
        if not self._flags.enabled(PLAN_LIMITS, tenant_id):
            return None
        return self._reader.registration_limit(tenant_id)
