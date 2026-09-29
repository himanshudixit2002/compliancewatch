"""Supabase Auth as the identity provider (ADR-014).

Sign-in tokens are verified against the project's signing keys, published at
``{url}/auth/v1/.well-known/jwks.json`` (ES256 or RS256 once asymmetric JWT signing keys are on)
and cached for an hour. A project still on the legacy shared secret signs with HS256; those tokens
are accepted only when ``CW_SUPABASE_JWT_SECRET`` is set. Every token must name the project as
issuer (``{url}/auth/v1``) and ``authenticated`` as audience, carry a subject and an expiry, and
not be an anonymous sign-in. ``aal`` is the assurance level: ``aal2`` after a second factor.

When the keys cannot be fetched and none are cached, verification answers
``ProviderUnavailableError``: new sign-ins fail closed.

Accounts are managed through the admin API, ``{url}/auth/v1/admin/users[/{id}]``, with the
service-role key in the ``apikey`` and ``Authorization: Bearer`` headers. A provisioned account
has its address marked confirmed, so the person signs in with a one-time code sent to it and
nothing is sent when the account is made. Transport errors, 5xx answers and a refused key are
``ProviderUnavailableError``.

Nothing here creates a Supabase project or changes its settings: the manual steps are in the
service README. These calls are checked against recorded responses only until a project exists.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import httpx2
import jwt
from jwt import PyJWK
from pydantic import SecretStr

from identity.domain.errors import (
    ProviderAccountExistsError,
    ProviderTokenInvalidError,
    ProviderUnavailableError,
)
from identity.domain.provider import AAL1, AAL_LEVELS, ProviderIdentity
from identity.domain.tenancy import Contact
from py_common.auth import AuthKeysUnavailableError, JwksUrlSource

NAME: Final = "supabase"
ASYMMETRIC: Final = ("ES256", "RS256")
LEGACY: Final = "HS256"
DEFAULT_AUDIENCE: Final = "authenticated"
LEEWAY: Final = timedelta(seconds=30)
JWKS_PATH: Final = "/auth/v1/.well-known/jwks.json"
ADMIN_USERS_PATH: Final = "/auth/v1/admin/users"
ACCOUNT_EXISTS_STATUSES: Final = frozenset({409, 422})


class SupabaseIdentityProvider:
    def __init__(
        self,
        url: str,
        service_role_key: SecretStr,
        *,
        audience: str = DEFAULT_AUDIENCE,
        jwt_secret: SecretStr | None = None,
        client: httpx2.Client | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        base = url.rstrip("/")
        if not base.startswith(("https://", "http://")):
            raise ValueError("the Supabase URL must be the project's http(s) URL")
        if not service_role_key.get_secret_value():
            raise ValueError("the Supabase provider needs the service-role key")
        self._base = base
        self._issuer = base + "/auth/v1"
        self._key = service_role_key
        self._audience = audience
        self._jwt_secret = jwt_secret
        self._client = client or httpx2.Client(timeout=timeout_seconds)
        self._keys = JwksUrlSource(base + JWKS_PATH, client=self._client)

    @property
    def name(self) -> str:
        return NAME

    @property
    def issuer(self) -> str:
        return self._issuer

    # ------------------------------------------------------------ sign-in tokens

    def verify(self, token: str) -> ProviderIdentity:
        key = self._key_for(token)
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=[*ASYMMETRIC, LEGACY],
                audience=self._audience,
                issuer=self._issuer,
                leeway=LEEWAY,
                options={"require": ["sub", "exp", "iat"]},
            )
        except jwt.PyJWTError as exc:
            detail = f"the Supabase token failed verification: {exc}"
            raise ProviderTokenInvalidError(detail) from exc
        if claims.get("is_anonymous") is True:
            raise ProviderTokenInvalidError("an anonymous Supabase sign-in names nobody")
        return _identity(claims)

    def _key_for(self, token: str) -> Any:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise ProviderTokenInvalidError("the Supabase token is not a well-formed JWT") from exc
        algorithm = header.get("alg")
        if algorithm == LEGACY:
            if self._jwt_secret is None or not self._jwt_secret.get_secret_value():
                raise ProviderTokenInvalidError(
                    "HS256 Supabase tokens are accepted only with CW_SUPABASE_JWT_SECRET"
                )
            return self._jwt_secret.get_secret_value().encode("utf-8")
        if algorithm not in ASYMMETRIC:
            raise ProviderTokenInvalidError(f"Supabase tokens signed with {algorithm} are refused")
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise ProviderTokenInvalidError("the Supabase token names no signing key")
        try:
            found: PyJWK | None = self._keys.key_for(kid)
        except AuthKeysUnavailableError as exc:
            raise ProviderUnavailableError(
                "the Supabase signing keys could not be fetched; sign-in fails closed"
            ) from exc
        if found is None or found.algorithm_name != algorithm:
            raise ProviderTokenInvalidError("the Supabase token is signed by an unknown key")
        return found.key

    # ------------------------------------------------------------ accounts

    def provision(self, *, email: str = "", phone: str = "", display_name: str = "") -> str:
        contact = Contact.of(email=email, phone=phone)
        body: dict[str, Any] = {"user_metadata": {"display_name": display_name.strip()}}
        if contact.email:
            body |= {"email": contact.email, "email_confirm": True}
        if contact.phone:
            body |= {"phone": contact.phone.removeprefix("+"), "phone_confirm": True}
        response = self._admin("POST", ADMIN_USERS_PATH, json=body)
        if response.status_code in ACCOUNT_EXISTS_STATUSES:
            raise ProviderAccountExistsError()
        _require_success(response)
        subject = _json(response).get("id")
        if not isinstance(subject, str) or not _is_uuid(subject):
            raise ProviderUnavailableError("Supabase answered a new account without its id")
        return subject

    def lookup(self, subject: str) -> ProviderIdentity | None:
        if not _is_uuid(subject):
            return None
        response = self._admin("GET", f"{ADMIN_USERS_PATH}/{subject}")
        if response.status_code == 404:
            return None
        _require_success(response)
        account = _json(response)
        return ProviderIdentity(
            subject=subject,
            email=_text(account.get("email")),
            phone=_text(account.get("phone")),
        )

    def delete(self, subject: str) -> None:
        if not _is_uuid(subject):
            return
        response = self._admin("DELETE", f"{ADMIN_USERS_PATH}/{subject}")
        if response.status_code != 404:
            _require_success(response)

    def _admin(self, method: str, path: str, *, json: object = None) -> httpx2.Response:
        key = self._key.get_secret_value()
        headers = {"apikey": key, "Authorization": f"Bearer {key}"}
        try:
            return self._client.request(method, self._base + path, headers=headers, json=json)
        except httpx2.HTTPError as exc:
            raise ProviderUnavailableError(
                f"Supabase could not be reached: {type(exc).__name__}"
            ) from exc


def _identity(claims: dict[str, Any]) -> ProviderIdentity:
    """The identity in verified claims. Supabase reports a phone number without its plus; the
    identity keeps the claims as they are and ``ProviderIdentity.contact`` normalises them. An
    assurance level this code does not know counts as one factor."""
    try:
        aal = claims.get("aal", AAL1)
        return ProviderIdentity(
            subject=claims["sub"],
            email=_text(claims.get("email")),
            phone=_text(claims.get("phone")),
            aal=aal if aal in AAL_LEVELS else AAL1,
            issued_at=datetime.fromtimestamp(claims["iat"], UTC),
        )
    except (ValueError, TypeError) as exc:
        detail = f"the Supabase token's claims are malformed: {exc}"
        raise ProviderTokenInvalidError(detail) from exc


def _require_success(response: httpx2.Response) -> None:
    if response.status_code >= 400:
        raise ProviderUnavailableError(
            f"Supabase's admin API answered {response.status_code}; check the URL and the "
            "service-role key"
        )


def _json(response: httpx2.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError as exc:
        raise ProviderUnavailableError("Supabase's admin API answered something not JSON") from exc
    if not isinstance(body, dict):
        raise ProviderUnavailableError("Supabase's admin API answered something not an object")
    return body


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True
