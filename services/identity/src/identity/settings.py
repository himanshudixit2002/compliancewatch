"""Process configuration of the identity service: ``CW_*`` on top of py-common's.

Nothing here creates an account. ``identity_store`` picks memory or postgres for consent
records. Billing stays ``none`` until the maintainer has a Razorpay account, plans and keys
(docs in identity/infrastructure/billing/razorpay.py); ``razorpay_plan_ids`` maps our plan
keys to Razorpay plan ids as ``owner_monthly=plan_x,ca_seat_monthly=plan_y``.

``plan_free_registrations`` and ``plan_free_seats`` (``CW_PLAN_FREE_REGISTRATIONS`` and
``CW_PLAN_FREE_SEATS``, one each) are what a tenant without a paid subscription is entitled to:
placeholders the maintainer decides with the pricing. They are refused past only while the flag
``identity.plan_limits`` (``CW_PLAN_LIMITS_ENFORCED``, per tenant with
``CW_PLAN_LIMITS_TENANTS``) is on; ``GET /v1/identity/entitlements`` reports them either way.
``plan_past_due_grace_days`` (``CW_PLAN_PAST_DUE_GRACE_DAYS``, 14) is how long a past-due or
halted subscription keeps its plan, another placeholder the maintainer decides; then the tenant
has the free allowance. ``plan_max_quantity`` (``CW_PLAN_MAX_QUANTITY``, 1000) bounds the units a
start or a webhook may give a subscription; it can lower the API's ceiling of 1000, not raise it.

``identity_channel_token`` is the shared secret the WhatsApp bot sends in
``x-cw-service-token`` to record and read channel consents. Unset, both routes refuse every call
(503): consents keyed by a phone number are personal data no tenant guards, so they fail closed.

``auth_provider`` picks the identity provider people sign in with (``CW_AUTH_PROVIDER``; owner
identity-partner): ``fake`` (the default) signs provider tokens in the process, with
``identity_fake_provider_secret`` when several dev processes must accept each other's tokens;
``supabase`` verifies Supabase Auth tokens and manages accounts with ``supabase_url`` and
``supabase_service_role_key`` (``supabase_jwt_secret`` only for a project still on the legacy
HS256 secret). Production refuses ``fake``.

``identity_signing_keys`` are the ES256 keys access tokens are signed with, the JSON array
``identity-admin signing-key new`` prints (secret; the first key signs, all are published at
``/v1/identity/.well-known/jwks.json``). They are required except in local and test, where a key
is made at start with a warning, and every token signed with it stops verifying when the process
restarts. ``access_token_ttl_seconds`` and ``service_token_ttl_seconds`` bound how long a user's
and a service's token live (ten minutes each): the longest a revoked session lasts in the other
services.

``identity_dev_clients`` are the service clients local and test runs create, all with the secret
``identity_dev_client_secret``: the committed ``identity_dev_clients.toml`` unless
``CW_IDENTITY_DEV_CLIENTS`` gives ``client=scope+scope,client=scope``. The secret is refused
outside local and test.

``identity_export_sources`` are the services whose data a tenant's export holds besides
identity's own, as ``service=base_url`` pairs (``CW_IDENTITY_EXPORT_SOURCES``): by default the
dev stack's profile, applicability engine, obligation and notification ports, which only local
and test accept: anywhere else the setting is required, and each URL is https or a loopback
address (the export token must not cross a network in clear). ``make web-stack`` passes its own
ports and the combined product points them at its internal listener (loopback).
``identity_export_timeout_seconds`` (20 s) bounds each service's answer; the services are asked
``identity_export_concurrency`` (4) at a time, all of them within
``identity_export_deadline_seconds`` (45 s), so a download answers within about a minute, below
a proxy's usual timeout, and a service still answering at the deadline counts as pending.
"""

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Final, Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator

from domain_kernel.access import Scope
from identity.domain.billing import MAX_QUANTITY
from identity.domain.data_requests import parse_export_sources
from py_common.settings import Settings

MIN_FAKE_SECRET_BYTES = 32
MIN_DEV_CLIENT_SECRET_CHARS = 32
DEV_ENVIRONMENTS: Final = ("local", "test")
DEFAULT_EXPORT_SOURCES: Final = (
    "profile=http://localhost:8002,applicability-engine=http://localhost:8004,"
    "obligation=http://localhost:8005,notification=http://localhost:8006"
)
LOOPBACK_HOSTS: Final = frozenset({"localhost", "127.0.0.1", "::1"})
DEV_CLIENTS_FILE: Final = Path(__file__).with_name("identity_dev_clients.toml")
Store = Literal["memory", "postgres"]
Billing = Literal["none", "memory", "razorpay"]
AuthProvider = Literal["fake", "supabase"]


class IdentitySettings(Settings):
    identity_store: Store = "postgres"
    billing_provider: Billing = "none"
    razorpay_key_id: str = ""
    razorpay_key_secret: SecretStr | None = None
    razorpay_webhook_secret: SecretStr | None = None
    razorpay_plan_ids: dict[str, str] = Field(default_factory=dict)
    plan_free_registrations: int = Field(default=1, ge=0)
    plan_free_seats: int = Field(default=1, ge=0)
    plan_past_due_grace_days: int = Field(default=14, ge=0, le=365)
    plan_max_quantity: int = Field(default=MAX_QUANTITY, ge=1, le=MAX_QUANTITY)
    identity_channel_token: SecretStr | None = None
    auth_provider: AuthProvider = "fake"
    identity_fake_provider_secret: SecretStr | None = None
    supabase_url: str = ""
    supabase_service_role_key: SecretStr | None = None
    supabase_jwt_secret: SecretStr | None = None
    identity_signing_keys: SecretStr | None = None
    access_token_ttl_seconds: int = Field(default=600, ge=60, le=3600)
    service_token_ttl_seconds: int = Field(default=600, ge=60, le=3600)
    identity_dev_clients: str = ""
    identity_dev_client_secret: SecretStr | None = None
    identity_export_sources: str = DEFAULT_EXPORT_SOURCES
    identity_export_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    identity_export_concurrency: int = Field(default=4, ge=1, le=16)
    identity_export_deadline_seconds: float = Field(default=45.0, gt=0, le=120)

    @field_validator("razorpay_plan_ids", mode="before")
    @classmethod
    def _parse_plan_ids(cls, value: object) -> object:
        if isinstance(value, str):
            pairs = [item.split("=", 1) for item in value.split(",") if "=" in item]
            return {key.strip(): plan_id.strip() for key, plan_id in pairs}
        return value

    @model_validator(mode="after")
    def _check_the_provider(self) -> Self:
        if self.auth_provider == "fake" and self.env == "prod":
            raise ValueError(
                "CW_ENV=prod needs CW_AUTH_PROVIDER=supabase: the fake provider signs anyone in"
            )
        if self.auth_provider == "supabase" and (
            not self.supabase_url or not _secret(self.supabase_service_role_key)
        ):
            raise ValueError(
                "CW_AUTH_PROVIDER=supabase needs CW_SUPABASE_URL and CW_SUPABASE_SERVICE_ROLE_KEY"
            )
        secret = _secret(self.identity_fake_provider_secret)
        if secret and len(secret.encode("utf-8")) < MIN_FAKE_SECRET_BYTES:
            raise ValueError(
                f"CW_IDENTITY_FAKE_PROVIDER_SECRET needs at least {MIN_FAKE_SECRET_BYTES} bytes"
            )
        return self

    @model_validator(mode="after")
    def _check_the_keys_and_dev_clients(self) -> Self:
        if not self.is_dev and not _secret(self.identity_signing_keys):
            raise ValueError(
                f"CW_ENV={self.env} needs CW_IDENTITY_SIGNING_KEYS (identity-admin signing-key new)"
            )
        dev_secret = _secret(self.identity_dev_client_secret)
        if dev_secret and not self.is_dev:
            raise ValueError(
                f"CW_IDENTITY_DEV_CLIENT_SECRET is for local and test only, not CW_ENV={self.env}"
            )
        if dev_secret and len(dev_secret) < MIN_DEV_CLIENT_SECRET_CHARS:
            raise ValueError(
                f"CW_IDENTITY_DEV_CLIENT_SECRET needs at least {MIN_DEV_CLIENT_SECRET_CHARS} "
                "characters"
            )
        if self.is_dev:
            parse_dev_clients(self.identity_dev_clients)
        return self

    @model_validator(mode="after")
    def _check_the_export_sources(self) -> Self:
        sources = self.export_sources
        if "identity" in sources:
            raise ValueError("CW_IDENTITY_EXPORT_SOURCES lists the other services, not identity")
        if self.is_dev:
            return self
        if self.identity_export_sources.strip() == DEFAULT_EXPORT_SOURCES:
            raise ValueError(
                f"CW_ENV={self.env} needs CW_IDENTITY_EXPORT_SOURCES: the default names the dev "
                "stack's ports, where every export would stay pending"
            )
        for service, url in sources.items():
            if not secure_source(url):
                raise ValueError(
                    f"CW_IDENTITY_EXPORT_SOURCES: {service} is called over plain http outside "
                    f"local and test (CW_ENV={self.env}); use https, or a loopback address for "
                    "a service in the same process"
                )
        return self

    @property
    def export_sources(self) -> Mapping[str, str]:
        """The services an export calls, by name, with their base URLs."""
        return parse_export_sources(self.identity_export_sources)

    @property
    def is_dev(self) -> bool:
        """Whether this is a local or test run, where dev conveniences are allowed."""
        return self.env in DEV_ENVIRONMENTS

    @property
    def dev_clients(self) -> Mapping[str, frozenset[Scope]]:
        """The dev service clients and their scopes."""
        return parse_dev_clients(self.identity_dev_clients)


def secure_source(url: str) -> bool:
    """Whether an export source's URL keeps the export token off the network in clear: https,
    or http to a loopback address (the combined deployable calls its own internal listener)."""
    parts = urlsplit(url)
    return parts.scheme == "https" or (
        parts.scheme == "http" and (parts.hostname or "") in LOOPBACK_HOSTS
    )


def _secret(value: SecretStr | None) -> str:
    return "" if value is None else value.get_secret_value()


def parse_dev_clients(text: str) -> Mapping[str, frozenset[Scope]]:
    """``client=scope+scope,client=scope`` as a mapping, or the committed file when ``text`` is
    blank. An unknown scope or a line without ``=`` is a ValueError."""
    if not text.strip():
        return load_dev_clients_file(DEV_CLIENTS_FILE)
    clients: dict[str, frozenset[Scope]] = {}
    for item in text.split(","):
        client_id, separator, scopes = item.strip().partition("=")
        if not separator or not client_id.strip():
            raise ValueError(f"CW_IDENTITY_DEV_CLIENTS: {item.strip()!r} is not client=scope+scope")
        clients[client_id.strip()] = _scopes(scopes.split("+"), client_id.strip())
    return clients


def load_dev_clients_file(path: Path) -> Mapping[str, frozenset[Scope]]:
    """The clients of a dev clients file: one table per client with its ``scopes``."""
    tables = tomllib.loads(path.read_text(encoding="utf-8"))
    clients: dict[str, frozenset[Scope]] = {}
    for client_id, table in tables.items():
        scopes = table.get("scopes") if isinstance(table, dict) else None
        if not isinstance(scopes, list):
            raise ValueError(f"{path.name}: [{client_id}] needs a scopes list")
        clients[client_id] = _scopes(scopes, client_id)
    return clients


def _scopes(values: list[object] | list[str], client_id: str) -> frozenset[Scope]:
    known = {scope.value: scope for scope in Scope}
    found: set[Scope] = set()
    for value in values:
        text = value.strip() if isinstance(value, str) else value
        if not isinstance(text, str) or text not in known:
            raise ValueError(f"dev client {client_id}: {value!r} is not a scope")
        found.add(known[text])
    return frozenset(found)
