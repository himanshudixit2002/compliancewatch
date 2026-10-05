"""Where ``cw-product`` finds the running product, how it talks to it, and when it refuses.

``ProductSettings`` reads ``CW_*`` the way the services do (the environment, then ``.env``): the
environment and the auth mode, the listeners of ``cw-mvp serve`` and the worker's health port
(``MvpSettings``), the rulebook's write and review tokens, and the sink's file. The make targets
hand the tool the values they hand the stack, so the two agree.

``refusal`` says why the tool must not run at all. It writes synthetic tenants and a synthetic
publication, so it runs only where ``CW_ENV`` is local or test; and it acts for a tenant through
``x-tenant-id`` and for the pipeline and the analysts through the rulebook's shared tokens, which
only ``header`` and ``dual`` mode read.

``Product`` holds the HTTP clients. Every call goes to the internal listener (8080), as the web
app's do on the local stack; the check also probes the public listener (8000) and the worker's
health port. ``ok`` reads the answer a step needs, and anything else becomes ``ProductError``
with the service's problem type and detail.
"""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Self
from uuid import UUID

import httpx2
from pydantic import SecretStr

from cw_mvp.settings import MvpSettings
from py_common.settings import Settings

REPO: Final = Path(__file__).resolve().parents[5]
GOLDEN: Final = REPO / "evals" / "golden"
"""The golden sets: the recorded notifications and the world that cites them."""
STATE_PATH: Final = REPO / "var" / "seed" / "last.json"
"""Where the web app's development sign-in finds the last seeded tenant."""
LOCAL_ENVIRONMENTS: Final = frozenset({"local", "test"})
HEADER_MODES: Final = frozenset({"header", "dual"})
TENANT_HEADER: Final = "x-tenant-id"
WRITE_TOKEN_HEADER: Final = "x-cw-write-token"
REVIEW_TOKEN_HEADER: Final = "x-cw-review-token"
REQUEST_SECONDS: Final = 30.0
SERVICE_NAME: Final = "cw-product"


class ProductError(RuntimeError):
    """A step could not be done; the message says which and why."""


class ProductSettings(MvpSettings):
    """``product_records_url`` is the database the check reads what no route serves (the
    business directory, the audit rows of no tenant) on a read-only session; empty, the steps
    that need it fail (``records``)."""

    rulebook_write_token: SecretStr | None = None
    rulebook_review_token: SecretStr | None = None
    notification_sink_path: str = "var/notification/sink.jsonl"
    product_records_url: str = ""


def refusal(settings: Settings) -> str | None:
    """Why the tool must not run against these settings, or None."""
    if settings.env not in LOCAL_ENVIRONMENTS:
        return (
            f"cw-product writes synthetic tenants and a synthetic publication: it runs only when "
            f"CW_ENV is local or test, not {settings.env}"
        )
    if settings.auth_mode not in HEADER_MODES:
        return (
            "cw-product acts through x-tenant-id and the rulebook's shared tokens: it needs "
            f"CW_AUTH_MODE header or dual, not {settings.auth_mode}"
        )
    return None


def loopback(host: str) -> str:
    """Where a client on this machine reaches a listener bound to ``host``."""
    if host in ("", "::", "0.0.0.0"):
        return "127.0.0.1"
    return f"[{host}]" if ":" in host else host


def problem_slug(response: httpx2.Response) -> str:
    """The last part of a problem's type, ``rulebook-duplicate-approver``; '' for another body."""
    try:
        body = response.json()
    except ValueError:
        return ""
    kind = body.get("type") if isinstance(body, dict) else None
    return kind.rsplit(":", 1)[-1] if isinstance(kind, str) else ""


def describe(response: httpx2.Response) -> str:
    """The status with the problem's type and detail, or the start of the body."""
    slug = problem_slug(response)
    if slug:
        detail = response.json().get("detail") or ""
        return f"{response.status_code} {slug}: {detail}".rstrip(": ")
    return f"{response.status_code} {response.text[:200]}"


def ok(response: httpx2.Response, *statuses: int) -> Any:
    """The JSON body when the status is one of ``statuses`` (200 when none are given)."""
    if response.status_code in (statuses or (200,)):
        return response.json() if response.content else None
    request = response.request
    raise ProductError(f"{request.method} {request.url.path}: {describe(response)}")


def as_tenant(tenant_id: UUID, **headers: str) -> dict[str, str]:
    return {TENANT_HEADER: str(tenant_id), **headers}


@dataclass(frozen=True, slots=True)
class Product:
    """The running product as the tool reaches it."""

    settings: ProductSettings
    internal: httpx2.Client
    public: httpx2.Client
    worker: httpx2.Client

    @classmethod
    @contextmanager
    def connect(
        cls, settings: ProductSettings, *, timeout: float = REQUEST_SECONDS
    ) -> Iterator[Self]:
        host = loopback(settings.mvp_host)
        urls = {
            "internal": settings.mvp_internal_url,
            "public": f"http://{host}:{settings.mvp_public_port}",
            "worker": f"http://{host}:{settings.mvp_worker_health_port}",
        }
        clients = {name: httpx2.Client(base_url=url, timeout=timeout) for name, url in urls.items()}
        try:
            yield cls(settings, clients["internal"], clients["public"], clients["worker"])
        finally:
            for client in clients.values():
                client.close()

    @property
    def internal_url(self) -> str:
        return str(self.internal.base_url).rstrip("/")

    def write_token(self) -> str:
        """The pipeline's shared write token, which the document registrations carry."""
        return _secret(self.settings.rulebook_write_token, "WRITE")

    def write_headers(self) -> Mapping[str, str]:
        return {WRITE_TOKEN_HEADER: self.write_token()}

    def review_headers(self) -> Mapping[str, str]:
        """The analysts' shared review token, which citing, review and publishing carry."""
        return {REVIEW_TOKEN_HEADER: _secret(self.settings.rulebook_review_token, "REVIEW")}

    @property
    def sink_path(self) -> Path:
        return Path(self.settings.notification_sink_path)


def _secret(value: SecretStr | None, name: str) -> str:
    secret = "" if value is None else value.get_secret_value()
    if not secret:
        raise ProductError(
            f"CW_RULEBOOK_{name}_TOKEN is not set; give the tool the rulebook's own value "
            "(make product passes it to both)"
        )
    return secret
