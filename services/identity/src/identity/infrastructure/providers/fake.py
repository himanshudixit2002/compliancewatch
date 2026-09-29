"""A fake identity provider for local runs, the demo and tests.

It signs provider tokens with HS256 and a secret: ``CW_IDENTITY_FAKE_PROVIDER_SECRET`` when it is
set, so several dev processes accept each other's tokens, or 32 random bytes made per process. A
token names a subject derived from the phone number or email address (uuid5), so the same person
gets the same subject every time; its claims are ``sub``, ``phone``, ``email``, ``aal``, ``iat``
and ``exp``. Accounts made by ``provision`` live in the process only.

The settings refuse this provider in production, and the dev route that issues its tokens answers
only in local and test.
"""

import secrets
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import jwt

from domain_kernel.events import utc_now
from identity.domain.errors import ProviderAccountExistsError, ProviderTokenInvalidError
from identity.domain.provider import AAL1, AAL_LEVELS, ProviderIdentity
from identity.domain.tenancy import Contact

NAME: Final = "fake"
ALGORITHM: Final = "HS256"
ISSUER: Final = "urn:compliancewatch:fake-identity-provider"
AUDIENCE: Final = "authenticated"
SUBJECT_NAMESPACE: Final = uuid.uuid5(uuid.NAMESPACE_URL, ISSUER)
DEFAULT_TTL: Final = timedelta(hours=1)
MIN_SECRET_BYTES: Final = 32


class FakeIdentityProvider:
    """Issues and verifies provider tokens with one shared secret."""

    def __init__(
        self,
        secret: bytes | None = None,
        *,
        ttl: timedelta = DEFAULT_TTL,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if secret is not None and len(secret) < MIN_SECRET_BYTES:
            raise ValueError(f"the fake provider's secret needs at least {MIN_SECRET_BYTES} bytes")
        self._secret = secret or secrets.token_bytes(MIN_SECRET_BYTES)
        self._ttl = ttl
        self._clock = clock
        self._accounts: dict[str, ProviderIdentity] = {}

    @property
    def name(self) -> str:
        return NAME

    @staticmethod
    def subject_for(contact: Contact) -> str:
        """The subject of the person with ``contact``: from the phone number when there is one,
        from the email address otherwise."""
        return str(uuid.uuid5(SUBJECT_NAMESPACE, contact.phone or contact.email))

    def issue(self, *, email: str = "", phone: str = "", aal: str = AAL1) -> str:
        """A provider token for the person with this email address or phone number, signed in
        at assurance level ``aal``."""
        if aal not in AAL_LEVELS:
            raise ValueError(f"aal must be one of {', '.join(AAL_LEVELS)}")
        contact = Contact.of(email=email, phone=phone)
        issued_at = self._clock().astimezone(UTC).replace(microsecond=0)
        claims: dict[str, Any] = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": self.subject_for(contact),
            "email": contact.email,
            "phone": contact.phone,
            "aal": aal,
            "iat": int(issued_at.timestamp()),
            "exp": int((issued_at + self._ttl).timestamp()),
        }
        return jwt.encode(claims, self._secret, algorithm=ALGORITHM)

    def verify(self, token: str) -> ProviderIdentity:
        try:
            claims = jwt.decode(
                token,
                self._secret,
                algorithms=[ALGORITHM],
                audience=AUDIENCE,
                issuer=ISSUER,
                options={"require": ["sub", "iat", "exp"]},
            )
            return ProviderIdentity(
                subject=claims["sub"],
                email=claims.get("email", ""),
                phone=claims.get("phone", ""),
                aal=claims.get("aal", AAL1),
                issued_at=datetime.fromtimestamp(claims["iat"], UTC),
            )
        except (jwt.PyJWTError, ValueError, TypeError) as exc:
            detail = f"the provider token failed verification: {exc}"
            raise ProviderTokenInvalidError(detail) from exc

    def provision(self, *, email: str = "", phone: str = "", display_name: str = "") -> str:
        contact = Contact.of(email=email, phone=phone)
        subject = self.subject_for(contact)
        if subject in self._accounts:
            raise ProviderAccountExistsError()
        self._accounts[subject] = ProviderIdentity(
            subject=subject, email=contact.email, phone=contact.phone
        )
        return subject

    def lookup(self, subject: str) -> ProviderIdentity | None:
        return self._accounts.get(subject)

    def delete(self, subject: str) -> None:
        self._accounts.pop(subject, None)
